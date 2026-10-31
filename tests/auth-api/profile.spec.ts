import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test('owner edits profile and signs in with the new email after reauthentication', async ({
  request,
}) => {
  request = privateApi(request)
  const email = `profile-${randomUUID()}@example.com`
  const replacement = `updated-${randomUUID()}@example.com`
  const password = 'synthetic profile password'
  expect(
    (
      await request.post('/api/v1/auth/register', {
        data: { name: 'Synthetic Profile', email, password },
      })
    ).status(),
  ).toBe(200)
  await loginSession(request, email, password)
  const path = '/api/v1/users/me'
  const initial = await (await request.get(path)).json()
  const update = async (data: Record<string, string>) =>
    request.patch(path, {
      data,
      headers: { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(request) },
    })
  expect((await update({ name: 'Updated Profile' })).status()).toBe(204)
  expect(await (await request.get(path)).json()).toEqual({ ...initial, name: 'Updated Profile' })
  expect((await update({ email: replacement, current_password: password })).status()).toBe(204)
  expect((await request.get(path)).status()).toBe(401)
  await loginSession(request, replacement, password)
  expect(await (await request.get(path)).json()).toEqual({
    ...initial,
    name: 'Updated Profile',
    email: replacement,
  })
})
