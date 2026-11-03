import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic consolidated balance password'
async function seed(context: APIRequestContext, empty = false) {
  const api = privateApi(context)
  const email = `consolidated-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Transfer Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    if (empty) return { email, from: '', to: '' }
    const ids: string[] = []
    for (const [name, date] of [
      ['Conta origem', '2026-01-01'],
      ['Conta destino', '2026-01-03'],
    ]) {
      const response = await api.post('/api/v1/accounts', {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'Idempotency-Key': randomUUID(),
        },
        data: { name, type: 'checking', opening_balance: '1000.00', opening_date: date },
      })
      expect(response.status()).toBe(201)
      ids.push((await response.json()).id as string)
    }
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const category = await api.post('/api/v1/categories', {
      headers,
      data: { name: 'Synthetic expense', type: 'expense' },
    })
    expect(category.status()).toBe(201)
    const categoryId = (await category.json()).id as string
    const transfer = await api.post('/api/v1/transfers', {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: {
        from_account_id: ids[0],
        to_account_id: ids[1],
        amount: '500.00',
        status: 'posted',
        effective_date: '2026-01-04',
      },
    })
    expect(transfer.status()).toBe(201)
    for (const [status, amount] of [
      ['posted', '150.00'],
      ['planned', '200.00'],
    ]) {
      const movement = await api.post('/api/v1/transactions', {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: {
          account_id: ids[0],
          category_id: categoryId,
          description: 'Synthetic movement',
          amount,
          type: 'expense',
          status,
          effective_date: '2026-01-04',
        },
      })
      expect(movement.status()).toBe(201)
    }
    return { email, from: ids[0], to: ids[1] }
  } finally {
    await api.dispose()
  }
}
async function enter(page: Page, email: string) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Saldos', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Consultar consolidado', exact: true }),
  ).toBeEnabled()
}

async function consult(page: Page, value: string) {
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.locator('.consolidated-result')).toContainText(value)
}

test('consolidated filters explain archived accounts and conserve internal transfers without duplicating expenses', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  // Larger base text exercises wrapping across different system fonts at 320px.
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  await page.getByLabel('Consolidado até a data').fill('2026-01-04')
  await consult(page, 'R$ 1.850,00')
  await expect(page.locator('.consolidated-result')).toContainText('2 conta(s)')
  await page.getByLabel('Consolidado até a data').fill('2026-01-02')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('abertura igual ou anterior')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await page.getByLabel('Consolidado até a data').fill('2026-01-04')
  const api = privateApi(page.request)
  const detail = await api.get(base + `/api/v1/accounts/${data.to}`)
  expect(
    (
      await api.patch(base + `/api/v1/accounts/${data.to}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': detail.headers().etag,
        },
        data: { is_active: false },
      })
    ).status(),
  ).toBe(200)
  await consult(page, 'R$ 350,00')
  await expect(page.locator('.consolidated-result')).toContainText('1 conta(s)')
  await page.getByLabel('Contas incluídas no consolidado').selectOption('all')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await consult(page, 'R$ 1.850,00')
  await page.getByLabel('Contas incluídas no consolidado').selectOption('selected')
  await page.getByRole('button', { name: 'Atualizar contas e limpar seleção' }).click()
  await expect(page.getByRole('checkbox', { name: 'Conta destino · Arquivada' })).toBeEnabled()
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('1 a 100 contas')
  await page.getByRole('checkbox', { name: 'Conta destino · Arquivada' }).check()
  await consult(page, 'R$ 1.500,00')
  await page.getByRole('checkbox', { name: 'Conta origem', exact: true }).check()
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await consult(page, 'R$ 1.850,00')
  await page.getByRole('checkbox', { name: 'Conta destino · Arquivada' }).uncheck()
  await consult(page, 'R$ 350,00')
  await page.getByLabel('Consolidado até a data').fill('2026-01-02')
  await consult(page, 'R$ 1.000,00')
  await page.getByRole('checkbox', { name: 'Conta destino · Arquivada' }).check()
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('abertura de todas as contas selecionadas')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await expect(
    page.getByText('Uma transferência entre duas contas incluídas se cancela no total.', {
      exact: false,
    }),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('an empty account scope is explicit and service failure never shows a fabricated zero balance', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }), true)
  await enter(page, data.email)
  await page.getByLabel('Consolidado até a data').fill('2026-01-04')
  await consult(page, 'R$ 0,00')
  await expect(page.locator('.consolidated-result')).toContainText(
    'Nenhuma conta incluída neste filtro',
  )
  let fail = true
  await page.route('**/api/v1/accounts/balances/consolidated**', async (route) => {
    if (fail) {
      fail = false
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic unavailable balance' }),
      })
    }
    return route.continue()
  })
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não conseguimos acessar o serviço')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await consult(page, 'R$ 0,00')
  await page.getByLabel('Contas incluídas no consolidado').selectOption('selected')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await expect(page.getByText('Nenhuma conta disponível para selecionar.')).toBeVisible()
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('1 a 100 contas')
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
})
