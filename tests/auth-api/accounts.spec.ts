import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test('account creation retries preserve money and isolate two owners', async ({
  request,
  playwright,
}) => {
  request = privateApi(request)
  const other = privateApi(
    await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' }),
  )
  const password = 'synthetic account password'
  try {
    for (const api of [request, other]) {
      const email = `accounts-${randomUUID()}@example.com`
      expect(
        (
          await api.post('/api/v1/auth/register', {
            data: { name: 'Synthetic Owner', email, password },
          })
        ).status(),
      ).toBe(200)
      await loginSession(api, email, password)
    }
    const data = {
      name: 'Synthetic account',
      type: 'checking',
      opening_balance: '-10.25',
      opening_date: '2026-01-01',
    }
    const key = randomUUID()
    const headers = {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(request),
      'Idempotency-Key': key,
    }
    const created = await request.post('/api/v1/accounts', { data, headers })
    expect(created.status()).toBe(201)
    const id = (await created.json()).id as string
    const replay = await request.post('/api/v1/accounts', { data, headers })
    expect(replay.status()).toBe(201)
    expect(await replay.json()).toEqual({ id })
    expect(
      (
        await request.post('/api/v1/accounts', { data: { ...data, name: 'Different' }, headers })
      ).status(),
    ).toBe(409)
    const account = await request.get(`/api/v1/accounts/${id}`)
    expect((await account.json()).opening_balance).toBe('-10.25')
    expect(account.headers()['cache-control']).toBe('no-store')
    expect((await other.get(`/api/v1/accounts/${id}`)).status()).toBe(404)
    expect((await (await other.get('/api/v1/accounts')).json()).items).toEqual([])
    expect((await (await request.get('/api/v1/accounts')).json()).items.length).toBe(1)
  } finally {
    await other.dispose()
  }
})
