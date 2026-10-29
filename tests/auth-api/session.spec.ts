import { expect, test, type APIRequestContext } from '@playwright/test'

const origin = 'http://127.0.0.1:4175'
const prefix = '/api/v1/auth/'
const password = 'synthetic session password'

function privateApi(api: APIRequestContext): APIRequestContext {
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

async function login(api: APIRequestContext, name = 'alice') {
  const bootstrap = await api.post(prefix + 'csrf', {
    data: {},
    headers: { Origin: origin, 'X-CSRF-Bootstrap': '1' },
  })
  expect(bootstrap.status()).toBe(200)
  const { csrf_token: csrf } = await bootstrap.json()
  const response = await api.post(prefix + 'login', {
    data: { email: `${name}@example.com`, password },
    headers: { Origin: origin, 'X-CSRF-Token': csrf },
  })
  expect(response.status()).toBe(204)
  expect((await response.body()).length).toBe(0)
}

async function csrf(api: APIRequestContext) {
  const state = await api.storageState()
  const value = state.cookies.find((cookie) => cookie.name === 'finsight_csrf')?.value
  if (!value) throw new Error('Session CSRF cookie is missing.')
  return value
}

test('session round trip and two independent users', async ({ request, playwright }) => {
  request = privateApi(request)
  const other = privateApi(
    await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' }),
  )
  try {
    await login(request)
    await login(other, 'bob')
    const first = await request.get(prefix + 'me')
    const second = await other.get(prefix + 'me')
    expect(first.status()).toBe(200)
    expect(second.status()).toBe(200)
    const alice = await first.json()
    const bob = await second.json()
    expect(Object.keys(alice).sort()).toEqual(['email', 'id', 'name'])
    expect(alice.email).toBe('alice@example.com')
    expect(bob.email).toBe('bob@example.com')
    expect(alice.id).not.toBe(bob.id)
    const profile = await request.get(prefix + `me?user_id=${bob.id}`)
    expect((await profile.json()).email).toBe('alice@example.com')
    const headers = { Origin: origin, 'X-CSRF-Token': await csrf(request) }
    expect((await request.post(prefix + 'refresh', { data: {}, headers })).status()).toBe(204)
    expect((await request.post(prefix + 'logout', { data: {}, headers })).status()).toBe(204)
    expect((await request.get(prefix + 'me')).status()).toBe(401)
    expect((await other.get(prefix + 'me')).status()).toBe(200)
  } finally {
    await other.dispose()
  }
})

test('replayed refresh revokes even the freshly rotated credentials', async ({
  request,
  playwright,
}) => {
  request = privateApi(request)
  await login(request)
  const state = await request.storageState()
  const stale = privateApi(
    await playwright.request.newContext({
      baseURL: 'http://127.0.0.1:8002',
      storageState: state,
    }),
  )
  try {
    const headers = { Origin: origin, 'X-CSRF-Token': await csrf(request) }
    expect((await request.post(prefix + 'refresh', { data: {}, headers })).status()).toBe(204)
    const replay = await stale.post(prefix + 'refresh', { data: {}, headers })
    expect(replay.status()).toBe(401)
    expect(replay.headers()['cache-control']).toBe('no-store')
    expect((await request.get(prefix + 'me')).status()).toBe(401)
  } finally {
    await stale.dispose()
  }
})

test('invalid CSRF is rejected without logging out', async ({ request }) => {
  request = privateApi(request)
  await login(request)
  const denied = await request.post(prefix + 'logout', {
    data: {},
    headers: { Origin: origin, 'X-CSRF-Token': 'invalid-synthetic-csrf' },
  })
  expect(denied.status()).toBe(403)
  expect(denied.headers()['set-cookie']).toBeUndefined()
  expect((await request.get(prefix + 'me')).status()).toBe(200)
})
