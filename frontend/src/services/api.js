import { validateBreakdown } from '@/lib/dashboard'

// Cookies stay in the browser; only the session-bound CSRF value is used by JavaScript.
const sessionEvents =
  typeof BroadcastChannel === 'function' ? new BroadcastChannel('finsight-session-events') : null
if (import.meta.hot) import.meta.hot.dispose(() => sessionEvents?.close())

export function watchSessionChanges(callback) {
  const receive = (event) => {
    if (event.data === 'session-changed') callback()
  }
  sessionEvents?.addEventListener('message', receive)
  return () => sessionEvents?.removeEventListener('message', receive)
}
export class ApiError extends Error {
  constructor(status) {
    super('Não foi possível concluir a solicitação.')
    this.status = status
  }
}

function apiUrl(path) {
  const local = ['localhost', '127.0.0.1', '[::1]']
  const configured = import.meta.env.VITE_API_BASE_URL
  const fallback = local.includes(window.location.hostname)
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : window.location.origin
  let base
  try {
    base = new URL(configured || fallback)
  } catch {
    throw new ApiError(0)
  }
  if (
    !['http:', 'https:'].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    base.pathname !== '/' ||
    (import.meta.env.PROD && base.protocol !== 'https:' && !local.includes(base.hostname))
  )
    throw new ApiError(0)
  return base.origin + '/api/v1' + path
}

async function send(
  path,
  { method = 'GET', data, headers = {}, credentials = 'include', versioned = false } = {},
) {
  let response
  try {
    response = await fetch(apiUrl(path), {
      method,
      credentials,
      cache: 'no-store',
      headers: {
        Accept: 'application/json',
        ...(data === undefined ? {} : { 'Content-Type': 'application/json' }),
        ...headers,
      },
      ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    })
  } catch {
    throw new ApiError(0)
  }
  if (!response.ok) throw new ApiError(response.status)
  if (response.status === 204) return undefined
  try {
    const data = await response.json()
    if (!versioned) return data
    const etag = response.headers.get('etag')
    if (!/^"[0-9a-f]{64}"$/.test(etag || '')) throw new ApiError(0)
    return { data, etag }
  } catch {
    throw new ApiError(0)
  }
}

let queue = Promise.resolve()
function coordinated(task) {
  if (navigator.locks?.request) return navigator.locks.request('finsight-session', task)
  // Without cross-tab locks, explicit actions are serialized in this tab; refresh is disabled.
  const result = queue.then(task, task)
  queue = result.catch(() => {})
  return result
}

async function bootstrap() {
  const data = await send('/auth/csrf', {
    method: 'POST',
    data: {},
    headers: { 'X-CSRF-Bootstrap': '1' },
  })
  if (typeof data?.csrf_token !== 'string') throw new ApiError(0)
  return data.csrf_token
}

async function renewUnlocked() {
  try {
    return await send('/users/me')
  } catch (error) {
    if (error.status !== 401) throw error
  }
  if (!navigator.locks?.request) throw new ApiError(401)
  const csrf = await bootstrap()
  await send('/auth/refresh', { method: 'POST', data: {}, headers: { 'X-CSRF-Token': csrf } })
  return send('/users/me')
}

async function authenticatedRead(path) {
  try {
    return await send(path)
  } catch (error) {
    if (error.status !== 401) throw error
  }
  return coordinated(async () => {
    // Another tab may already have renewed the shared cookies while this tab waited.
    await renewUnlocked()
    return send(path)
  })
}

function validImportAmounts(result) {
  const amounts = [
    'income_total',
    'expense_total',
    'bank_balance_before',
    'bank_balance_after',
    'reserved_amount',
    'free_balance_after',
    'uncovered_reserved_after',
  ]
  return (
    result &&
    amounts.every(
      (field) => typeof result[field] === 'string' && /^-?\d+\.\d{2}$/.test(result[field]),
    ) &&
    typeof result.as_of === 'string' &&
    /^\d{4}-\d{2}-\d{2}$/.test(result.as_of)
  )
}

function validateImportReceipt(result, jobId) {
  if (
    !validImportAmounts(result) ||
    result?.job_id !== jobId ||
    !Number.isSafeInteger(result.imported_rows) ||
    result.imported_rows < 1 ||
    !Number.isSafeInteger(result.not_imported_rows) ||
    result.not_imported_rows < 0 ||
    !Number.isFinite(Date.parse(result.completed_at))
  )
    throw new ApiError(0)
}

export const api = {
  createGoal: (ownerId, data, key) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send('/goals', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key },
        })
        if (
          typeof result?.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(result.id)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  goal: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/goals/${encodeURIComponent(id)}`, { versioned: true })
      if (
        result.data?.id !== id ||
        !['active', 'completed', 'cancelled'].includes(result.data.status)
      )
        throw new ApiError(0)
      return result
    }),
  updateGoal: (ownerId, id, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/goals/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          data,
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (
          result.data?.id !== id ||
          !['active', 'completed', 'cancelled'].includes(result.data.status)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  goals: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/goals?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),

  correctAccountOpening: (ownerId, id, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/accounts/${encodeURIComponent(id)}/opening`, {
          method: 'PATCH',
          data,
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (
          result.data?.id !== id ||
          result.data.opening_balance !== data.opening_balance ||
          result.data.opening_date !== data.opening_date
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),

  deleteTransfer: (ownerId, id, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const remove = async () => {
        const csrf = await bootstrap()
        return send(`/transfers/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          data: {},
          headers: { 'If-Match': etag, 'X-CSRF-Token': csrf },
        })
      }
      try {
        return await remove()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return remove()
      }
    }),
  updateTransfer: (ownerId, id, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/transfers/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          data,
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (result.data?.id !== id || !['planned', 'posted'].includes(result.data.status))
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  dashboardBreakdown: (ownerId, scope, dateFrom, dateTo, accountIds = []) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const ids = scope === 'selected' ? [...accountIds].sort() : []
      const query = new URLSearchParams({ scope, date_from: dateFrom, date_to: dateTo })
      ids.forEach((id) => query.append('account_id', id))
      const result = await send(`/dashboard/breakdown?${query}`)
      if (
        result?.date_from !== dateFrom ||
        result.date_to !== dateTo ||
        result.scope !== scope ||
        result.currency !== 'BRL' ||
        typeof result.as_of !== 'string' ||
        !/^\d{4}-\d{2}-\d{2}$/.test(result.as_of) ||
        result.as_of < dateTo ||
        !['account_count', 'transaction_count'].every(
          (field) => Number.isSafeInteger(result[field]) && result[field] >= 0,
        ) ||
        !['income', 'expense'].every(
          (field) => typeof result[field] === 'string' && /^\d+\.\d{2}$/.test(result[field]),
        ) ||
        typeof result.net !== 'string' ||
        !/^-?\d+\.\d{2}$/.test(result.net) ||
        (scope === 'selected'
          ? result.account_count !== ids.length ||
            JSON.stringify(result.account_ids) !== JSON.stringify(ids)
          : result.account_ids !== null)
      )
        throw new ApiError(0)
      const cents = (value) => BigInt(value.replace('.', ''))
      if (cents(result.income) - cents(result.expense) !== cents(result.net)) throw new ApiError(0)
      try {
        validateBreakdown(result)
      } catch {
        throw new ApiError(0)
      }
      return result
    }),
  balanceHistory: (ownerId, accountId, dateFrom, dateTo) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const query = new URLSearchParams({ date_from: dateFrom, date_to: dateTo })
      return send(`/accounts/${encodeURIComponent(accountId)}/balance/history?${query}`)
    }),
  projectedBalance: (ownerId, scope, baseDate, targetDate, overduePolicy, accountIds) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const query = new URLSearchParams({
        scope,
        base_date: baseDate,
        target_date: targetDate,
        overdue_policy: overduePolicy,
      })
      if (scope === 'selected') accountIds.forEach((id) => query.append('account_id', id))
      return send(`/accounts/balances/projected?${query}`)
    }),
  consolidatedBalance: (ownerId, scope, asOf, accountIds) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const query = new URLSearchParams({ scope, as_of: asOf })
      if (scope === 'selected') accountIds.forEach((id) => query.append('account_id', id))
      return send(`/accounts/balances/consolidated?${query}`)
    }),
  transfer: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/transfers/${encodeURIComponent(id)}`, { versioned: true })
      if (result.data?.id !== id || !['planned', 'posted'].includes(result.data.status))
        throw new ApiError(0)
      return result
    }),
  postTransfer: (ownerId, id, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/transfers/${encodeURIComponent(id)}/post`, {
          method: 'POST',
          data: {},
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (result.data?.id !== id || result.data.status !== 'posted') throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  transfers: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/transfers?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  createTransfer: (ownerId, data, key) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send('/transfers', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key },
        })
        if (
          typeof result?.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(result.id)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  transaction: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/transactions/${encodeURIComponent(id)}`, { versioned: true })
      if (result.data?.id !== id || !['planned', 'posted'].includes(result.data.status))
        throw new ApiError(0)
      return result
    }),
  deleteTransaction: (ownerId, id, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const remove = async () => {
        const csrf = await bootstrap()
        return send(`/transactions/${encodeURIComponent(id)}`, {
          method: 'DELETE',
          data: {},
          headers: { 'If-Match': etag, 'X-CSRF-Token': csrf },
        })
      }
      try {
        return await remove()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return remove()
      }
    }),
  updateTransaction: (ownerId, id, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/transactions/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          data,
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (result.data?.id !== id) throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  postTransaction: (ownerId, id, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/transactions/${encodeURIComponent(id)}/post`, {
          method: 'POST',
          data: {},
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
        if (result.data?.id !== id || result.data.status !== 'posted') throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  transactions: (ownerId, offset = 0, filters = {}) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const query = new URLSearchParams({ limit: '50', offset: String(offset) })
      for (const field of [
        'account_id',
        'category_id',
        'type',
        'status',
        'date_from',
        'date_to',
        'q',
      ]) {
        if (filters[field]) query.set(field, filters[field])
      }
      const result = await send(`/transactions?${query}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  balance: (ownerId, id, asOf) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      return send(`/accounts/${encodeURIComponent(id)}/balance?as_of=${encodeURIComponent(asOf)}`)
    }),
  createTransaction: (ownerId, data, key) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send('/transactions', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key },
        })
        if (
          typeof result?.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(result.id)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  categories: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/categories?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  category: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      return send(`/categories/${encodeURIComponent(id)}`, { versioned: true })
    }),
  saveCategory: (ownerId, data, id, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      return send(id ? `/categories/${encodeURIComponent(id)}` : '/categories', {
        method: id ? 'PATCH' : 'POST',
        data,
        versioned: true,
        headers: { 'X-CSRF-Token': await bootstrap(), ...(id ? { 'If-Match': etag } : {}) },
      })
    }),
  account: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      return send(`/accounts/${encodeURIComponent(id)}`, { versioned: true })
    }),
  updateAccount: (ownerId, id, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () =>
        send(`/accounts/${encodeURIComponent(id)}`, {
          method: 'PATCH',
          data,
          versioned: true,
          headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
        })
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  accounts: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/accounts?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  createAccount: (ownerId, data, key) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () =>
        send('/accounts', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key },
        })
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit() // Keep the same key and payload after an authenticated retry.
      }
    }),
  goalFunding: (ownerId, goalId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      return send(`/goals/${encodeURIComponent(goalId)}/funding`)
    }),
  allocationContext: (ownerId, goalId, accountId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(
        `/goals/${encodeURIComponent(goalId)}/allocation-context?account_id=${encodeURIComponent(accountId)}`,
        { versioned: true },
      )
      if (
        result.data?.funding?.goal?.id !== goalId ||
        result.data?.availability?.account?.id !== accountId
      )
        throw new ApiError(0)
      return result
    }),
  allocations: (ownerId, goalId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(
        `/goals/${encodeURIComponent(goalId)}/allocations?limit=50&offset=${offset}`,
      )
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  reservationAlerts: (ownerId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send('/reservations/alerts')
      if (
        !Array.isArray(result?.items) ||
        !Number.isSafeInteger(result?.account_count) ||
        result.account_count < 0
      )
        throw new ApiError(0)
      return result
    }),
  createAllocation: (ownerId, goalId, data, key, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/goals/${encodeURIComponent(goalId)}/allocations`, {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key, 'If-Match': etag },
        })
        if (
          typeof result?.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(result.id)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        const renewed = await renewUnlocked()
        if (renewed.id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  inspectImport: (ownerId, data) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send('/imports/inspect', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap() },
        })
        if (
          result?.account_id !== data.account_id ||
          !Array.isArray(result.headers) ||
          !Array.isArray(result.sample)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        if ((await renewUnlocked()).id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  createImport: (ownerId, data, key) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send('/imports', {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key },
        })
        if (
          typeof result?.id !== 'string' ||
          !/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(result.id)
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        if ((await renewUnlocked()).id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  imports: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/imports?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  importJob: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/imports/${encodeURIComponent(id)}`)
      if (result?.id !== id) throw new ApiError(0)
      return result
    }),
  importRows: (ownerId, id, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/imports/${encodeURIComponent(id)}/rows?limit=50&offset=${offset}`)
      if (!Array.isArray(result?.items)) throw new ApiError(0)
      return result
    }),
  importConfirmation: (ownerId, jobId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/imports/${encodeURIComponent(jobId)}/confirmation`, {
        versioned: true,
      })
      if (
        !validImportAmounts(result.data) ||
        typeof result.data.eligible !== 'boolean' ||
        result.data?.job_id !== jobId ||
        result.data.etag !== result.etag ||
        !Array.isArray(result.data.selected_rows) ||
        !Array.isArray(result.data.issues) ||
        !Number.isSafeInteger(result.data.selected_count) ||
        result.data.selected_rows.length !== result.data.selected_count
      )
        throw new ApiError(0)
      if (result.data.receipt) validateImportReceipt(result.data.receipt, jobId)
      return result
    }),
  confirmImport: (ownerId, jobId, data, key, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(`/imports/${encodeURIComponent(jobId)}/confirm`, {
          method: 'POST',
          data,
          headers: { 'X-CSRF-Token': await bootstrap(), 'Idempotency-Key': key, 'If-Match': etag },
        })
        validateImportReceipt(result, jobId)
        return result
      }
      try {
        return await submit()
      } catch (failure) {
        if (failure.status !== 401) throw failure
        if ((await renewUnlocked()).id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  importDuplicates: (ownerId, jobId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/imports/${encodeURIComponent(jobId)}/duplicates`)
      if (result?.job_id !== jobId || !Array.isArray(result.items)) throw new ApiError(0)
      return result
    }),
  importRow: (ownerId, jobId, rowId) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(
        `/imports/${encodeURIComponent(jobId)}/rows/${encodeURIComponent(rowId)}`,
        { versioned: true },
      )
      if (result.data?.id !== rowId || result.data.etag !== result.etag) throw new ApiError(0)
      return result
    }),
  updateImportRow: (ownerId, jobId, rowId, data, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(
          `/imports/${encodeURIComponent(jobId)}/rows/${encodeURIComponent(rowId)}`,
          {
            method: 'PATCH',
            data,
            versioned: true,
            headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
          },
        )
        if (
          result.data?.id !== rowId ||
          result.data.etag !== result.etag ||
          result.data.selected !== false
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        if ((await renewUnlocked()).id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  selectImportRow: (ownerId, jobId, rowId, selected, etag) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const submit = async () => {
        const result = await send(
          `/imports/${encodeURIComponent(jobId)}/rows/${encodeURIComponent(rowId)}/selection`,
          {
            method: 'PATCH',
            data: { selected },
            versioned: true,
            headers: { 'If-Match': etag, 'X-CSRF-Token': await bootstrap() },
          },
        )
        if (
          result.data?.id !== rowId ||
          result.data.etag !== result.etag ||
          result.data.selected !== selected
        )
          throw new ApiError(0)
        return result
      }
      try {
        return await submit()
      } catch (error) {
        if (error.status !== 401) throw error
        if ((await renewUnlocked()).id !== ownerId) throw new ApiError(401)
        return submit()
      }
    }),
  profile: () => authenticatedRead('/users/me'),
  register: (data) => send('/auth/register', { method: 'POST', data, credentials: 'omit' }),
  login: (email, password) =>
    coordinated(async () => {
      // Explicit sign-in replaces any stale recognized session before starting a new one.
      let csrf = await bootstrap()
      await send('/auth/logout', { method: 'POST', data: {}, headers: { 'X-CSRF-Token': csrf } })
      sessionEvents?.postMessage('session-changed')
      csrf = await bootstrap()
      await send('/auth/login', {
        method: 'POST',
        data: { email, password },
        headers: { 'X-CSRF-Token': csrf },
      })
      return send('/users/me')
    }),
  logout: () =>
    coordinated(async () => {
      const csrf = await bootstrap()
      await send('/auth/logout', { method: 'POST', data: {}, headers: { 'X-CSRF-Token': csrf } })
      sessionEvents?.postMessage('session-changed')
    }),
}

export function errorMessage(error, fallback) {
  if (error.status === 410)
    return 'Este lançamento foi excluído. Atualize o histórico para conferir.'
  if (error.status === 429) return 'Muitas tentativas. Espere um pouco e tente novamente.'
  if (error.status === 0 || error.status >= 500)
    return 'Não conseguimos acessar o serviço. Tente novamente em instantes.'
  if (error.status === 403) return 'Não foi possível validar esta tentativa. Tente novamente.'
  return fallback
}
