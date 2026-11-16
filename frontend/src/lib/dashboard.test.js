import assert from 'node:assert/strict'
import test from 'node:test'
import { categoryRows, dashboardPlotData, validateBreakdown } from './dashboard.js'

function snapshot() {
  return {
    date_from: '2026-01-02',
    date_to: '2026-01-03',
    as_of: '2026-01-31',
    transaction_count: 21,
    income: '0.00',
    expense: '209999999999999.79',
    net: '-209999999999999.79',
    daily: [
      { date: '2026-01-02', transaction_count: 0, income: '0.00', expense: '0.00', net: '0.00' },
      {
        date: '2026-01-03',
        transaction_count: 21,
        income: '0.00',
        expense: '209999999999999.79',
        net: '-209999999999999.79',
      },
    ],
    category_limit: 20,
    expense_category_count: 21,
    expense_categories: Array.from({ length: 20 }, (_, i) => ({
      category_id: `00000000-0000-4000-8000-${String(i + 1).padStart(12, '0')}`,
      name: i === 0 ? 'Demais categorias' : `Synthetic category ${i + 1}`,
      amount: '9999999999999.99',
      transaction_count: 1,
    })),
    other_expenses: { category_count: 1, transaction_count: 1, amount: '9999999999999.99' },
  }
}

test('dashboard preserves high precision totals and named remainder while producing bounded drawing ratios', () => {
  const data = snapshot()
  assert.doesNotThrow(() => validateBreakdown(data))
  const before = JSON.stringify(data)
  const plot = dashboardPlotData(data)
  assert.deepEqual(
    plot.daily.map((point) => point.expensePosition),
    [0, 100],
  )
  assert.equal(plot.daily[1].expense, '209999999999999.79')
  assert.equal(plot.categories.length, 21)
  assert.equal(plot.categories[0].name, 'Demais categorias')
  assert.equal(plot.categories[20].name, 'Demais categorias (1)')
  assert.equal(plot.categories[20].key, 'other')
  assert.ok(plot.categories.every((row) => row.position === 100))
  assert.equal(categoryRows(data).length, 21)
  assert.equal(JSON.stringify(data), before)
})

test('dashboard rejects incomplete or inconsistent chart snapshots instead of accepting matching summary alone', () => {
  for (const corrupt of [
    (data) => {
      data.daily[1].expense = '209999999999999.78'
    },
    (data) => {
      data.daily[1].date = '2026-01-02'
    },
    (data) => {
      data.expense_categories[1].category_id = data.expense_categories[0].category_id
    },
    (data) => {
      data.other_expenses.amount = '0.00'
    },
  ]) {
    const data = snapshot()
    corrupt(data)
    assert.throws(() => validateBreakdown(data))
  }
})
