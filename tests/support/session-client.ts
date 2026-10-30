import type { APIRequestContext } from '@playwright/test'

export const sessionOrigin = 'http://127.0.0.1:4175'

export function privateApi(api: APIRequestContext): APIRequestContext {
  return new Proxy(api, {
    get(target, key) {
      const value = Reflect.get(target, key)
      if (typeof value !== 'function') return value
      return async (...args: unknown[]) => {
        try {
          return await Reflect.apply(value, target, args)
        } catch {
          // Never report Playwright call logs containing Cookie/CSRF/password values.
          throw new Error('Isolated API operation failed; sensitive details suppressed.')
        }
      }
    },
  })
}

export async function loginSession(api: APIRequestContext, email: string, password: string) {
  const bootstrap = await api.post('/api/v1/auth/csrf', {
    data: {},
    headers: { Origin: sessionOrigin, 'X-CSRF-Bootstrap': '1' },
  })
  if (bootstrap.status() !== 200) throw new Error('Session bootstrap failed.')
  const { csrf_token: csrf } = await bootstrap.json()
  const response = await api.post('/api/v1/auth/login', {
    data: { email, password },
    headers: { Origin: sessionOrigin, 'X-CSRF-Token': csrf },
  })
  if (response.status() !== 204 || (await response.body()).length !== 0) {
    throw new Error('Session login contract failed.')
  }
}

export async function sessionCsrf(api: APIRequestContext) {
  const state = await api.storageState()
  const value = state.cookies.find((cookie) => cookie.name === 'finsight_csrf')?.value
  if (!value) throw new Error('Session CSRF cookie is missing.')
  return value
}
