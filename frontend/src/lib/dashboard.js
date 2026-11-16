import { dayNumber, shiftDay } from './balance-history.js'

function ensure(condition) {
  if (!condition) throw new Error('Unexpected dashboard response')
}

const count = (value) => Number.isSafeInteger(value) && value >= 0
function cents(value, signed = false) {
  ensure(typeof value === 'string' && value.length <= 64)
  ensure((signed ? /^-?\d+\.\d{2}$/ : /^\d+\.\d{2}$/).test(value))
  return BigInt(value.replace('.', ''))
}

// Reject inconsistent snapshots before cards, charts or tables can display them.
export function validateBreakdown(result) {
  const start = dayNumber(result.date_from),
    end = dayNumber(result.date_to)
  const asOf = dayNumber(result.as_of)
  ensure(
    start !== null &&
      end !== null &&
      asOf !== null &&
      end >= start &&
      end - start < 366 &&
      end <= asOf,
  )
  ensure(count(result.transaction_count) && count(result.expense_category_count))
  const income = cents(result.income),
    expense = cents(result.expense)
  ensure(income - expense === cents(result.net, true))
  ensure(Array.isArray(result.daily) && result.daily.length === end - start + 1)
  let dailyIncome = 0n,
    dailyExpense = 0n,
    dailyCount = 0n
  result.daily.forEach((point, index) => {
    ensure(point?.date === shiftDay(result.date_from, index) && count(point.transaction_count))
    const incoming = cents(point.income),
      outgoing = cents(point.expense)
    ensure(incoming - outgoing === cents(point.net, true))
    ensure((point.transaction_count === 0) === (incoming + outgoing === 0n))
    dailyIncome += incoming
    dailyExpense += outgoing
    dailyCount += BigInt(point.transaction_count)
  })
  ensure(
    dailyIncome === income &&
      dailyExpense === expense &&
      dailyCount === BigInt(result.transaction_count),
  )
  ensure(result.category_limit === 20 && Array.isArray(result.expense_categories))
  ensure(result.expense_categories.length === Math.min(20, result.expense_category_count))
  const seen = new Set()
  let groupedExpense = 0n,
    expenseCount = 0n,
    previous = null
  result.expense_categories.forEach((category) => {
    ensure(
      typeof category?.category_id === 'string' &&
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
          category.category_id,
        ),
    )
    ensure(!seen.has(category.category_id))
    seen.add(category.category_id)
    ensure(typeof category.name === 'string' && category.name.trim() && category.name.length <= 255)
    const amount = cents(category.amount)
    ensure(amount > 0n && count(category.transaction_count) && category.transaction_count > 0)
    if (previous)
      ensure(
        previous.amount > amount ||
          (previous.amount === amount && previous.id < category.category_id),
      )
    previous = { amount, id: category.category_id }
    groupedExpense += amount
    expenseCount += BigInt(category.transaction_count)
  })
  const other = result.other_expenses
  ensure(other && count(other.category_count) && count(other.transaction_count))
  const remainder = cents(other.amount)
  ensure(BigInt(result.expense_category_count) === BigInt(seen.size) + BigInt(other.category_count))
  ensure(
    other.category_count === 0
      ? remainder === 0n && other.transaction_count === 0
      : remainder > 0n && other.transaction_count >= other.category_count,
  )
  ensure(groupedExpense + remainder === expense)
  expenseCount += BigInt(other.transaction_count)
  ensure(expenseCount <= BigInt(result.transaction_count))
  ensure((expense === 0n) === (result.expense_category_count === 0))
}

export function categoryRows(result) {
  const rows = result.expense_categories.map((item) => ({ ...item, key: item.category_id }))
  if (result.other_expenses.category_count > 0)
    rows.push({
      ...result.other_expenses,
      key: 'other',
      name: `Demais categorias (${result.other_expenses.category_count})`,
    })
  return rows
}

export function dashboardPlotData(result) {
  const maximum = (values) =>
    values.reduce((max, value) => (cents(value) > cents(max) ? value : max), '0.00')
  const dailyMaximum = maximum(result.daily.flatMap((point) => [point.income, point.expense]))
  const categories = categoryRows(result)
  const categoryMaximum = maximum(categories.map((category) => category.amount))
  // Only bounded drawing coordinates become Number. Money remains the original string.
  const position = (value, max) =>
    cents(max) === 0n ? 0 : Number((cents(value) * 10000n) / cents(max)) / 100
  return {
    dailyMaximum,
    categoryMaximum,
    daily: result.daily.map((point) => ({
      ...point,
      incomePosition: position(point.income, dailyMaximum),
      expensePosition: position(point.expense, dailyMaximum),
    })),
    categories: categories.map((category, index) => ({
      ...category,
      label: String(index + 1),
      position: position(category.amount, categoryMaximum),
    })),
  }
}
