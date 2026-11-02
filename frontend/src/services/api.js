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

export const api = {
  transaction: (ownerId, id) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/transactions/${encodeURIComponent(id)}`, { versioned: true })
      if (result.data?.id !== id || !['planned', 'posted'].includes(result.data.status))
        throw new ApiError(0)
      return result
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
  transactions: (ownerId, offset = 0) =>
    coordinated(async () => {
      const profile = await renewUnlocked()
      if (profile.id !== ownerId) throw new ApiError(401)
      const result = await send(`/transactions?limit=50&offset=${offset}`)
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
  if (error.status === 429) return 'Muitas tentativas. Espere um pouco e tente novamente.'
  if (error.status === 0 || error.status >= 500)
    return 'Não conseguimos acessar o serviço. Tente novamente em instantes.'
  if (error.status === 403) return 'Não foi possível validar esta tentativa. Tente novamente.'
  return fallback
}
