import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002/api/v1'

async function enter(page: Page, request: APIRequestContext) {
  const email = `reservations-${randomUUID()}@example.com`
  const password = 'synthetic reservations password'
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'Synthetic Reservation Owner', email, password },
      })
    ).status(),
  ).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
  const api = privateApi(page.request)
  const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
  const account = await api.post(base + '/accounts', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: {
      name: 'Conta sintética de reserva',
      type: 'checking',
      opening_balance: '1000.00',
      opening_date: '2026-01-01',
    },
  })
  expect(account.status()).toBe(201)
  const accountId = (await account.json()).id as string
  const goal = await api.post(base + '/goals', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: { name: 'Viagem sintética', target_amount: '500.00' },
  })
  expect(goal.status()).toBe(201)
  const goalId = (await goal.json()).id as string
  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await page.getByRole('button', { name: 'Reservas e progresso', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Conta da reserva', exact: true })
    .selectOption(accountId)
  const form = page.getByRole('form', { name: 'Reservar ou retirar valor', exact: true })
  await expect(
    form.getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true }),
  ).toBeEnabled()
  return { api, headers, accountId, goalId, form }
}

test('reserving and withdrawing preserve bank money; spending refreshes compromised reserve alerts', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { api, accountId, goalId, form } = await enter(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  await form.getByLabel('Valor da reserva ou retirada (R$)').fill('800,00')
  let posts = 0
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname.endsWith('/allocations')) posts++
  })
  await form
    .getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  await expect(page.getByText('Progresso: 160,00%', { exact: true })).toBeVisible()
  await expect(page.getByText('Excedente: R$ 300,00', { exact: true })).toBeVisible()
  await expect(form).toContainText('Saldo bancário: R$ 1.000,00')
  await expect(form).toContainText('Saldo livre: R$ 200,00')
  expect(posts).toBe(1)
  await form.getByRole('combobox', { name: 'Operação', exact: true }).selectOption('withdraw')
  await form.getByLabel('Valor da reserva ou retirada (R$)').fill('800,01')
  await form.getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('não pode superar')
  expect(posts).toBe(1)
  await form.getByLabel('Valor da reserva ou retirada (R$)').fill('200,00')
  await form.getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true }).click()
  await expect(page.getByText('Reservado na meta: R$ 600,00', { exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  const category = await api.post(base + '/categories', {
    headers: { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) },
    data: { name: 'Despesa sintética', type: 'expense' },
  })
  expect(category.status()).toBe(201)
  const categoryId = (await category.json()).id as string
  const position = await (await api.get(`${base}/goals/${goalId}/funding`)).json()
  // Seed the expense through the real API; navigation refreshes the same derived warning.
  const expense = await api.post(base + '/transactions', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': randomUUID(),
    },
    data: {
      account_id: accountId,
      category_id: categoryId,
      description: 'Despesa permitida',
      amount: '500.00',
      type: 'expense',
      status: 'posted',
      effective_date: position.as_of,
    },
  })
  expect(expense.status()).toBe(201)
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  const alerts = page.getByRole('region', { name: 'Alertas de reservas', exact: true })
  await expect(alerts).toContainText('As despesas continuam permitidas')
  await expect(alerts).toContainText('R$ 100,00 da reserva sem cobertura')
  expect((await (await api.get(`${base}/goals/${goalId}/funding`)).json()).reserved_amount).toBe(
    '600.00',
  )
})

test('a lost reservation response keeps its key across navigation and resolves once', async ({
  page,
  request,
}) => {
  const { api, goalId, form } = await enter(page, request)
  const keys: string[] = []
  await page.route('**/api/v1/goals/*/allocations', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'])
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    if (keys.length === 1)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic lost response' }),
      })
    return route.fulfill({ response })
  })
  await form.getByLabel('Valor da reserva ou retirada (R$)').fill('300,00')
  await form.getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await page
    .getByRole('button', { name: 'Conferir e repetir operação de reserva', exact: true })
    .click()
  await expect(page.getByText('Reservado na meta: R$ 300,00', { exact: true })).toBeVisible()
  await expect(
    page.getByText('Reserva registrada. O saldo bancário não foi reduzido.', { exact: true }),
  ).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  expect((await (await api.get(`${base}/goals/${goalId}/allocations`)).json()).items).toHaveLength(
    1,
  )
})
