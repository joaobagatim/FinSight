import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic balance history password'
async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `history-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic History Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const ids: string[] = []
    for (const [name, opening_date] of [
      ['Conta histórica', '2026-01-01'],
      ['Destino histórico', '2026-01-03'],
    ]) {
      const response = await api.post('/api/v1/accounts', {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: { name, opening_date, type: 'checking', opening_balance: '1000.00' },
      })
      expect(response.status()).toBe(201)
      ids.push((await response.json()).id as string)
    }
    const category = await api.post('/api/v1/categories', {
      headers,
      data: { name: 'Synthetic history expense', type: 'expense' },
    })
    expect(category.status()).toBe(201)
    const categoryId = (await category.json()).id as string
    for (const [amount, effective_date, status] of [
      ['150.00', '2026-01-02', 'posted'],
      ['0.10', '2026-01-04', 'posted'],
      ['999.00', '2026-01-04', 'planned'],
    ]) {
      expect(
        (
          await api.post('/api/v1/transactions', {
            headers: { ...headers, 'Idempotency-Key': randomUUID() },
            data: {
              account_id: ids[0],
              category_id: categoryId,
              description: 'Synthetic daily closing',
              amount,
              effective_date,
              status,
              type: 'expense',
            },
          })
        ).status(),
      ).toBe(201)
    }
    expect(
      (
        await api.post('/api/v1/transfers', {
          headers: { ...headers, 'Idempotency-Key': randomUUID() },
          data: {
            from_account_id: ids[0],
            to_account_id: ids[1],
            amount: '500.00',
            effective_date: '2026-01-04',
            status: 'posted',
          },
        })
      ).status(),
    ).toBe(201)
    const account = await api.get(`/api/v1/accounts/${ids[1]}`)
    expect(
      (
        await api.patch(`/api/v1/accounts/${ids[1]}`, {
          headers: { ...headers, 'If-Match': account.headers().etag },
          data: { is_active: false },
        })
      ).status(),
    ).toBe(200)
    return { email, from: ids[0], to: ids[1] }
  } finally {
    await api.dispose()
  }
}
async function enter(page: Page, email: string, account: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Saldos', exact: true }).click()
  await expect(page.getByLabel('Conta da evolução')).toBeEnabled()
  await page.getByLabel('Conta da evolução').selectOption(account)
  await page.getByLabel('Evolução a partir de').fill('2026-01-01')
  await page.getByLabel('Evolução até', { exact: true }).fill('2026-01-05')
}

test('daily closing graph and exact table include transfers, flat days and archived accounts at 320px', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await page.setViewportSize({ width: 320, height: 950 })
  await enter(page, data.email, data.from)
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  const panel = page.getByRole('region', { name: 'Evolução do saldo', exact: true })
  const consult = panel.getByRole('button', { name: 'Consultar evolução', exact: true })
  let requests = 0
  page.on('request', (request) => {
    if (request.url().includes('/balance/history?')) requests++
  })
  await page.getByLabel('Evolução até', { exact: true }).fill('2026-04-04')
  await consult.click()
  await expect(panel.getByRole('alert')).toContainText('1 a 93 dias')
  expect(requests).toBe(0)
  await page.getByLabel('Evolução até', { exact: true }).fill('2026-01-05')
  await consult.click()
  await expect(panel.locator('.history-chart svg')).toHaveCount(1)
  await expect(panel.locator('.balance-history-result')).toContainText('R$ 349,90')
  await panel.getByText('Ver valores diários (5 dias)', { exact: true }).click()
  const table = panel.getByRole('table')
  await expect(table.getByRole('row')).toHaveCount(6)
  await expect(
    table
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: '02/01/2026', exact: true }) }),
  ).toContainText('R$ 850,00')
  await expect(
    table
      .getByRole('row')
      .filter({ has: page.getByRole('rowheader', { name: '03/01/2026', exact: true }) }),
  ).toContainText('R$ 850,00')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByLabel('Conta da evolução').selectOption(data.to)
  await expect(panel.locator('.balance-history-result')).toHaveCount(0)
  await expect(
    page
      .getByLabel('Conta da evolução')
      .getByRole('option', { name: 'Destino histórico · Arquivada', exact: true }),
  ).toHaveCount(1)
  await consult.click()
  await expect(panel.getByRole('alert')).toContainText('data de abertura')
  await page.getByLabel('Evolução a partir de').fill('2026-01-03')
  await consult.click()
  await expect(panel.locator('.balance-history-result')).toContainText('R$ 1.500,00')
})

test('chart loading failure keeps exact values and failed or partial history never becomes a balance', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await page.route(/BalanceHistoryChart.*\.js$/, (route) => route.abort())
  await enter(page, data.email, data.from)
  const panel = page.getByRole('region', { name: 'Evolução do saldo', exact: true })
  const consult = panel.getByRole('button', { name: 'Consultar evolução', exact: true })
  await consult.click()
  await expect(
    panel.getByText('Não foi possível carregar o gráfico.', { exact: false }),
  ).toBeVisible()
  await panel.getByText('Ver valores diários (5 dias)', { exact: true }).click()
  await expect(panel.getByRole('table')).toContainText('R$ 349,90')
  await page.route('**/balance/history?**', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic history unavailable' }),
    }),
  )
  await consult.click()
  await expect(panel.getByRole('alert')).toContainText('Não conseguimos acessar o serviço')
  await expect(panel.locator('.balance-history-result')).toHaveCount(0)
  await page.unroute('**/balance/history?**')
  await page.route('**/balance/history?**', async (route) => {
    const response = await route.fetch()
    const body = await response.json()
    body.points.pop()
    await route.fulfill({ response, json: body })
  })
  await consult.click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível consultar a evolução')
  await expect(panel.locator('.balance-history-result')).toHaveCount(0)
})
