import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const current = 'synthetic current password'
const replacement = 'synthetic replacement password'
const path = '/api/v1/users/me/change-password'

async function createUser(api: APIRequestContext) {
  const email = `password-${randomUUID()}@example.com`
  const response = await api.post('/api/v1/auth/register', {
    data: { name: 'Synthetic password owner', email, password: current },
  })
  expect(response.status()).toBe(200)
  return email
}

test('password change logs out every owned device but preserves another user', async ({
  request,
  playwright,
}) => {
  request = privateApi(request)
  const device = privateApi(
    await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' }),
  )
  const other = privateApi(
    await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' }),
  )
  try {
    const email = await createUser(request)
    const otherEmail = await createUser(other)
    await loginSession(request, email, current)
    await loginSession(device, email, current)
    await loginSession(other, otherEmail, current)
    const response = await request.post(path, {
      data: { current_password: current, new_password: replacement },
      headers: { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(request) },
    })
    expect(response.status()).toBe(204)
    expect((await response.body()).length).toBe(0)
    expect(response.headers()['cache-control']).toBe('no-store')
    expect(
      (await request.storageState()).cookies.filter((cookie) => cookie.name.startsWith('finsight_'))
        .length,
    ).toBe(0)
    expect((await device.get('/api/v1/auth/me')).status()).toBe(401)
    expect((await other.get('/api/v1/auth/me')).status()).toBe(200)
    await loginSession(request, email, replacement)
    expect((await request.get('/api/v1/auth/me')).status()).toBe(200)
  } finally {
    await device.dispose()
    await other.dispose()
  }
})

test('wrong current password and invalid CSRF preserve the active session', async ({ request }) => {
  request = privateApi(request)
  const email = await createUser(request)
  await loginSession(request, email, current)
  const body = { current_password: 'synthetic-private-password-marker', new_password: replacement }
  const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(request) }
  const wrong = await request.post(path, { data: body, headers })
  expect(wrong.status()).toBe(401)
  expect(wrong.headers()['set-cookie']).toBeUndefined()
  expect(await wrong.text()).not.toContain(body.current_password)
  const rejected = await request.post(path, {
    data: { current_password: current, new_password: replacement },
    headers: { ...headers, 'X-CSRF-Token': 'invalid-synthetic-csrf' },
  })
  expect(rejected.status()).toBe(403)
  expect(rejected.headers()['set-cookie']).toBeUndefined()
  expect((await request.get('/api/v1/auth/me')).status()).toBe(200)
})
