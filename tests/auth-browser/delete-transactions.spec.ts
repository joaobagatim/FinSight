import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic deletion password'

async function seed(context: APIRequestContext, status: 'planned' | 'posted' = 'posted') {
  const api = privateApi(context)
  const email = `deletion-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Posting Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const account = await api.post('/api/v1/accounts', {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: {
        name: 'Conta de planejados',
        type: 'checking',
        opening_balance: '1000.00',
        opening_date: '2026-01-01',
      },
    })
    expect(account.status()).toBe(201)
    const accountId = (await account.json()).id as string
    const category = await api.post('/api/v1/categories', {
      headers,
      data: { name: 'Despesa planejada', type: 'expense' },
    })
    expect(category.status()).toBe(201)
    const categoryId = (await category.json()).id as string
    const key = randomUUID()
    const body = {
      account_id: accountId,
      category_id: categoryId,
      description: 'Planejado sintético',
      amount: '150.00',
      type: 'expense',
      status,
      effective_date: '2026-01-02',
    }
    const movement = await api.post('/api/v1/transactions', {
      headers: { ...headers, 'Idempotency-Key': key },
      data: body,
    })
    expect(movement.status()).toBe(201)
    return { email, accountId, categoryId, id: (await movement.json()).id as string, body, key }
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
  await page.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Excluir', exact: true })).toBeEnabled()
}

async function consult(page: Page) {
  await page.getByLabel('Conta para consultar saldo').selectOption({ label: 'Conta de planejados' })
  await page.getByLabel('Saldo até a data').fill('2026-01-04')
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
}

test('deletion needs explicit confirmation, can be cancelled and repeated in two tabs without changing money twice', async ({
  page,
  context,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 850,00')
  let deletes = 0
  page.on('request', (request) => {
    if (request.method() === 'DELETE') deletes += 1
  })
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  const panel = page.locator('.deletion-panel')
  await expect(panel.getByRole('button', { name: 'Confirmar exclusão' })).toBeEnabled()
  await expect(panel).toContainText('150,00 em 02/01/2026')
  await expect(
    page.getByRole('button', { name: 'Cadastrar lançamento', exact: true }),
  ).toBeDisabled()
  await panel.getByRole('button', { name: 'Cancelar e voltar ao histórico' }).click()
  expect(deletes).toBe(0)
  await expect(page.getByRole('heading', { name: 'Seus lançamentos' })).toBeFocused()
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  await expect(panel.getByRole('button', { name: 'Confirmar exclusão' })).toBeEnabled()
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await tab.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await tab.getByRole('button', { name: 'Excluir', exact: true }).click()
  await expect(tab.getByRole('button', { name: 'Confirmar exclusão' })).toBeEnabled()
  await panel.getByRole('button', { name: 'Confirmar exclusão' }).evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await expect(panel.getByRole('status')).toContainText('excluído do histórico')
  expect(deletes).toBe(1)
  await tab.getByRole('button', { name: 'Confirmar exclusão' }).click()
  await expect(tab.locator('.deletion-panel').getByRole('status')).toContainText(
    'excluído do histórico',
  )
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(0)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 1.000,00')
  const api = privateApi(page.request)
  expect((await api.get(base + `/api/v1/transactions/${data.id}`)).status()).toBe(410)
  expect(
    (
      await api.post(base + '/api/v1/transactions', {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'Idempotency-Key': data.key,
        },
        data: data.body,
      })
    ).status(),
  ).toBe(410)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await tab.close()
})

test('stale deletion requires review and a lost successful DELETE is resolved by reading', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }), 'planned')
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Excluir', exact: true }).click()
  const panel = page.locator('.deletion-panel')
  await expect(panel.getByRole('button', { name: 'Confirmar exclusão' })).toBeEnabled()
  const api = privateApi(page.request)
  const detail = await api.get(base + `/api/v1/transactions/${data.id}`)
  expect(
    (
      await api.patch(base + `/api/v1/transactions/${data.id}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': detail.headers().etag,
        },
        data: { amount: '175.00' },
      })
    ).status(),
  ).toBe(200)
  let deletes = 0
  await page.route(`**/api/v1/transactions/${data.id}`, async (route) => {
    if (route.request().method() !== 'DELETE') return route.continue()
    deletes += 1
    if (deletes === 2) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic deletion forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(204)
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost deletion response' }),
      })
    }
    return route.continue()
  })
  await panel.getByRole('button', { name: 'Confirmar exclusão' }).click()
  await expect(panel.getByRole('alert')).toContainText('Os dados mudaram')
  await expect(panel.getByRole('button', { name: 'Confirmar exclusão' })).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel).toContainText('175,00')
  await panel.getByRole('button', { name: 'Confirmar exclusão' }).click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel.getByRole('status')).toContainText('excluído do histórico')
  expect(deletes).toBe(2)
  await expect(panel.getByRole('button', { name: 'Confirmar exclusão' })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 1.000,00')
})

test('retrying an uncertain creation after its deletion cannot recreate the movement', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  let createdId = ''
  let attempts = 0
  await page.route('**/api/v1/transactions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    attempts += 1
    if (attempts === 1) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic creation forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(201)
      createdId = (await response.json()).id as string
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost creation response' }),
      })
    }
    return route.continue()
  })
  await page.getByLabel('Descrição', { exact: true }).fill('Tentativa que foi excluída')
  await page.getByLabel('Conta do lançamento').selectOption(data.accountId)
  await page.getByLabel('Categoria do lançamento').selectOption(data.categoryId)
  await page.getByLabel('Valor (R$)', { exact: true }).fill('200,00')
  await page.getByLabel('Data do lançamento').fill('2026-01-03')
  await page.getByLabel('Situação do lançamento').selectOption('posted')
  await page.getByRole('button', { name: 'Cadastrar lançamento', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Conferir e repetir tentativa' })).toBeEnabled()
  const api = privateApi(page.request)
  const detail = await api.get(base + `/api/v1/transactions/${createdId}`)
  expect(
    (
      await api.delete(base + `/api/v1/transactions/${createdId}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': detail.headers().etag,
        },
        data: {},
      })
    ).status(),
  ).toBe(204)
  await page.getByRole('button', { name: 'Conferir e repetir tentativa' }).click()
  await expect(page.getByRole('alert')).toContainText('A repetição não criou outro')
  await expect(page.getByRole('button', { name: 'Conferir e repetir tentativa' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Conferi o histórico: encerrar tentativa' }).click()
  await page.getByRole('button', { name: 'Atualizar lançamentos' }).click()
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(1)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 850,00')
  expect(attempts).toBe(2)
})
