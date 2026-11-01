// Cookies stay in the browser; only the session-bound CSRF value is used by JavaScript.
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

async function send(path, { method = 'GET', data, headers = {}, credentials = 'include' } = {}) {
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
    return await response.json()
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
  profile: () => authenticatedRead('/users/me'),
  register: (data) => send('/auth/register', { method: 'POST', data, credentials: 'omit' }),
  login: (email, password) =>
    coordinated(async () => {
      // Explicit sign-in replaces any stale recognized session before starting a new one.
      let csrf = await bootstrap()
      await send('/auth/logout', { method: 'POST', data: {}, headers: { 'X-CSRF-Token': csrf } })
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
    }),
}

export function errorMessage(error, fallback) {
  if (error.status === 429) return 'Muitas tentativas. Espere um pouco e tente novamente.'
  if (error.status === 0 || error.status >= 500)
    return 'Não conseguimos acessar o serviço. Tente novamente em instantes.'
  if (error.status === 403) return 'Não foi possível validar esta tentativa. Tente novamente.'
  return fallback
}
