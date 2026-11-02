import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test('manual movements have exact balances, safe retries and owner isolation over HTTP', async ({
  request,
  playwright,
}) => {
  request = privateApi(request)
  const other = privateApi(
    await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' }),
  )
  const password = 'synthetic manual transaction password'
  try {
    for (const api of [request, other]) {
      const email = `manual-${randomUUID()}@example.com`
      expect(
        (
          await api.post('/api/v1/auth/register', {
            data: { name: 'Synthetic Owner', email, password },
          })
        ).status(),
      ).toBe(200)
      await loginSession(api, email, password)
    }
    const security = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(request) }
    const account = await request.post('/api/v1/accounts', {
      headers: { ...security, 'Idempotency-Key': randomUUID() },
      data: {
        name: 'Synthetic HTTP account',
        type: 'checking',
        opening_balance: '1000.00',
        opening_date: '2026-01-01',
      },
    })
    expect(account.status()).toBe(201)
    const accountId = (await account.json()).id as string
    const category = await request.post('/api/v1/categories', {
      headers: security,
      data: { name: 'Synthetic HTTP expense', type: 'expense' },
    })
    expect(category.status()).toBe(201)
    const categoryId = (await category.json()).id as string
    const data = {
      account_id: accountId,
      category_id: categoryId,
      type: 'expense',
      status: 'posted',
      amount: '150.00',
      description: 'Synthetic HTTP movement',
      effective_date: '2026-01-02',
    }
    const headers = { ...security, 'Idempotency-Key': randomUUID() }
    const movement = await request.post('/api/v1/transactions', { headers, data })
    expect(movement.status()).toBe(201)
    const replay = await request.post('/api/v1/transactions', { headers, data })
    expect(replay.status()).toBe(201)
    expect(await replay.json()).toEqual(await movement.json())
    const balanceUrl = `/api/v1/accounts/${accountId}/balance?as_of=2026-01-04`
    expect((await (await request.get(balanceUrl)).json()).balance).toBe('850.00')
    expect(
      (
        await request.post('/api/v1/transactions', {
          headers: { ...security, 'Idempotency-Key': randomUUID() },
          data: { ...data, status: 'planned', amount: '200.00' },
        })
      ).status(),
    ).toBe(201)
    expect((await (await request.get(balanceUrl)).json()).balance).toBe('850.00')
    expect((await other.get(balanceUrl)).status()).toBe(404)
    expect((await other.get(movement.headers().location)).status()).toBe(404)
    const list = await request.get('/api/v1/transactions')
    expect((await list.json()).items).toHaveLength(2)
    expect(list.headers()['cache-control']).toBe('no-store')
    expect((await (await other.get('/api/v1/transactions')).json()).items).toEqual([])
  } finally {
    await other.dispose()
  }
})
