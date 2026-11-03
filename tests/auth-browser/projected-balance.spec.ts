import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic projected balance password'

async function seed(context: APIRequestContext, empty = false) {
  const api = privateApi(context)
  const email = `projection-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Projection Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    if (empty) return email
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const account = await api.post('/api/v1/accounts', {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: {
        name: 'Conta de simulação',
        type: 'checking',
        opening_balance: '1000.00',
        opening_date: '2026-01-01',
      },
    })
    expect(account.status()).toBe(201)
    const category = await api.post('/api/v1/categories', {
      headers,
      data: { name: 'Synthetic expense', type: 'expense' },
    })
    expect(category.status()).toBe(201)
    const accountId = (await account.json()).id as string
    const categoryId = (await category.json()).id as string
    for (const [amount, date, status] of [
      ['150.00', '2026-01-04', 'posted'],
      ['100.00', '2026-01-08', 'posted'],
      ['30.00', '2026-01-04', 'planned'],
      ['10.00', '2026-01-05', 'planned'],
      ['50.00', '2026-01-10', 'planned'],
      ['999.00', '2026-01-11', 'planned'],
    ]) {
      expect(
        (
          await api.post('/api/v1/transactions', {
            headers: { ...headers, 'Idempotency-Key': randomUUID() },
            data: {
              account_id: accountId,
              category_id: categoryId,
              description: 'Synthetic projection',
              amount,
              type: 'expense',
              status,
              effective_date: date,
            },
          })
        ).status(),
      ).toBe(201)
    }
    return email
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
  await page.getByLabel('Tipo de consulta').selectOption('projected')
  await page.getByLabel('Data-base da simulação').fill('2026-01-05')
  await page.getByLabel('Data futura da simulação').fill('2026-01-10')
}

test('projection explains its components and overdue policy without changing real balances at 320px', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const email = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, email)
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  const simulate = page.getByRole('button', { name: 'Simular saldo futuro', exact: true })
  // Missing policy is blocked by native required validation, with no projection request.
  let reads = 0
  page.on('request', (request) => {
    if (request.url().includes('/balances/projected')) reads++
  })
  await simulate.click()
  expect(reads).toBe(0)
  await expect(page.locator('.consolidated-result')).toHaveCount(0)
  await page.getByLabel('Planejados vencidos antes da data-base').selectOption('exclude')
  await simulate.click()
  const result = page.locator('.consolidated-result')
  await expect(result).toContainText('R$ 690,00')
  await expect(result).toContainText('R$ 850,00')
  await expect(result).toContainText('−R$ 100,00')
  await expect(result).toContainText('−R$ 60,00')
  await expect(result).toContainText('Desconsidera planejados vencidos')
  await page.getByLabel('Planejados vencidos antes da data-base').selectOption('include')
  await expect(result).toHaveCount(0)
  await simulate.click()
  await expect(result).toContainText('R$ 660,00')
  await expect(result).toContainText('Inclui planejados vencidos')
  await page.getByLabel('Data futura da simulação').fill('2026-01-05')
  await simulate.click()
  await expect(page.getByRole('alert')).toContainText('data futura à data-base')
  await expect(result).toHaveCount(0)
  await page.getByLabel('Data futura da simulação').fill('2026-01-10')
  await page.getByLabel('Contas incluídas no consolidado').selectOption('selected')
  await page.getByRole('checkbox', { name: 'Conta de simulação' }).check()
  await simulate.click()
  await expect(result).toContainText('R$ 660,00')
  await expect(result.getByRole('list', { name: 'Contas da consulta' })).toContainText(
    'Conta de simulação',
  )
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByLabel('Tipo de consulta').selectOption('real')
  await expect(result).toHaveCount(0)
  await page.getByLabel('Consolidado até a data').fill('2026-01-10')
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(result).toContainText('R$ 750,00')
})

test('empty projection is explicit and failed consultation hides previous totals', async ({
  page,
  playwright,
}) => {
  const email = await seed(await playwright.request.newContext({ baseURL: base }), true)
  await enter(page, email)
  await page.getByLabel('Planejados vencidos antes da data-base').selectOption('exclude')
  const simulate = page.getByRole('button', { name: 'Simular saldo futuro', exact: true })
  await simulate.click()
  const result = page.locator('.consolidated-result')
  await expect(result).toContainText('Nenhuma conta incluída neste filtro')
  await expect(result).toContainText('R$ 0,00')
  await page.route('**/api/v1/accounts/balances/projected**', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic unavailable projection' }),
    }),
  )
  await simulate.click()
  await expect(page.getByRole('alert')).toContainText('Não conseguimos acessar o serviço')
  await expect(result).toHaveCount(0)
})
