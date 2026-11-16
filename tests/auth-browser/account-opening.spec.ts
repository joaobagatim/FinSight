import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

async function prepare(page: Page, request: APIRequestContext) {
  const email = `updates-${randomUUID()}@example.com`
  const password = 'synthetic account updates password'
  const response = await privateApi(request).post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: { name: 'Synthetic Updates Owner', email, password },
  })
  expect(response.status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByLabel('Nome da conta', { exact: true }).fill('Conta original')
  await page.getByLabel('Saldo inicial (R$)', { exact: true }).fill('-1.234,56')
  await page.getByLabel('Data de abertura', { exact: true }).fill('2026-01-01')
  await page.getByRole('button', { name: 'Cadastrar conta', exact: true }).click()
  await expect(
    page.getByRole('list', { name: 'Contas cadastradas' }).getByRole('listitem'),
  ).toHaveCount(1)
}

test('opening correction changes an unused account only after confirmation and preserves the exact position at 320px', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  await prepare(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  await page.getByRole('button', { name: 'Corrigir abertura', exact: true }).click()
  const editor = page.getByRole('form', { name: 'Corrigir abertura', exact: true })
  await expect(editor.getByLabel('Saldo de abertura corrigido (R$)')).toHaveValue('-1234,56')
  await expect(editor).toContainText('mesmo após exclusão')
  let patches = 0
  page.on('request', (req) => {
    if (req.method() === 'PATCH' && req.url().endsWith('/opening')) patches++
  })
  await editor.getByLabel('Saldo de abertura corrigido (R$)').fill('2.500,10')
  await editor.getByLabel('Data de abertura corrigida').fill('2026-01-03')
  expect(patches).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await editor
    .getByRole('button', { name: 'Confirmar correção da abertura', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  await expect(page.getByText('Abertura da conta atualizada.', { exact: true })).toBeVisible()
  expect(patches).toBe(1)
  const list = page.getByRole('list', { name: 'Contas cadastradas' })
  await expect(list).toContainText('R$ 2.500,10')
  await expect(list).toContainText('03/01/2026')
})

test('opening correction recovers an uncertain response by read and refuses accounts with financial history', async ({
  page,
  request,
}) => {
  await prepare(page, request)
  await page.getByRole('button', { name: 'Corrigir abertura', exact: true }).click()
  const editor = page.getByRole('form', { name: 'Corrigir abertura', exact: true })
  await editor.getByLabel('Saldo de abertura corrigido (R$)').fill('100,00')
  let patches = 0
  await page.route('**/api/v1/accounts/*/opening', async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    patches++
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic lost opening response' }),
    })
  })
  const confirm = editor.getByRole('button', {
    name: 'Confirmar correção da abertura',
    exact: true,
  })
  await confirm.click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar')
  await expect(confirm).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar dados', exact: true }).click()
  await expect(editor.getByLabel('Saldo de abertura corrigido (R$)')).toHaveValue('100,00')
  expect(patches).toBe(1)
  await page.unroute('**/api/v1/accounts/*/opening')
  const api = privateApi(page.request)
  const base = 'http://127.0.0.1:8002/api/v1'
  const account = (await (await api.get(base + '/accounts')).json()).items[0]
  const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
  const category = await api.post(base + '/categories', {
    headers,
    data: { name: 'Synthetic opening expense', type: 'expense' },
  })
  expect(category.status()).toBe(201)
  const transaction = await api.post(base + '/transactions', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: {
      account_id: account.id,
      category_id: (await category.json()).id,
      description: 'Synthetic first expense',
      amount: '1.00',
      type: 'expense',
      status: 'planned',
      effective_date: '2026-01-02',
    },
  })
  expect(transaction.status()).toBe(201)
  await editor.getByLabel('Saldo de abertura corrigido (R$)').fill('200,00')
  await confirm.click()
  await expect(page.getByRole('alert')).toContainText('A abertura está protegida')
  await expect(confirm).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar dados', exact: true }).click()
  await expect(editor.getByLabel('Saldo de abertura corrigido (R$)')).toHaveValue('100,00')
})
