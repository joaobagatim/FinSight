import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic planned posting password'

async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `posting-${randomUUID()}@example.com`
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
      status: 'planned',
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
  await expect(page.getByRole('button', { name: 'Efetivar', exact: true })).toBeEnabled()
}

async function consult(page: Page) {
  await page.getByLabel('Conta para consultar saldo').selectOption({ label: 'Conta de planejados' })
  await page.getByLabel('Saldo até a data').fill('2026-01-04')
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
}

test('explicit confirmation in two tabs posts the same movement once and preserves its creation key', async ({
  page,
  context,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 1.000,00')
  await page.getByRole('button', { name: 'Efetivar', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  await expect(page.locator('.posting-panel')).toContainText('150,00 em 02/01/2026')
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await tab.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await tab.getByRole('button', { name: 'Efetivar', exact: true }).click()
  await expect(tab.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  let posts = 0
  for (const current of [page, tab])
    current.on('request', (request) => {
      if (request.method() === 'POST' && request.url().endsWith(`/${data.id}/post`)) posts += 1
    })
  await page.getByRole('button', { name: 'Confirmar efetivação' }).evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await expect(page.getByText('Este lançamento já está efetivado.', { exact: true })).toBeVisible()
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await tab.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(tab.getByText('Este lançamento já está efetivado.', { exact: true })).toBeVisible()
  expect(posts).toBe(2)
  await page.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await expect(page.getByRole('heading', { name: 'Seus lançamentos' })).toBeFocused()
  const list = page.getByRole('list', { name: 'Lançamentos cadastrados' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('Efetivado')
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 850,00')
  const api = privateApi(page.request)
  const replay = await api.post(base + '/api/v1/transactions', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': data.key,
    },
    data: data.body,
  })
  expect(replay.status()).toBe(201)
  expect(await replay.json()).toEqual({ id: data.id })
  expect((await (await api.get(base + `/api/v1/transactions/${data.id}`)).json()).status).toBe(
    'posted',
  )
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await tab.close()
})

test('stale confirmation needs review and a lost posting response is resolved by reading', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Efetivar', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  const api = privateApi(page.request)
  const category = await api.get(base + `/api/v1/categories/${data.categoryId}`)
  expect(
    (
      await api.patch(base + `/api/v1/categories/${data.categoryId}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': category.headers().etag,
        },
        data: { name: 'Nome revisado' },
      })
    ).status(),
  ).toBe(200)
  let posts = 0
  await page.route(`**/api/v1/transactions/${data.id}/post`, async (route) => {
    posts += 1
    if (posts === 2) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic posting forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(200)
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost posting response' }),
      })
    }
    return route.continue()
  })
  await page.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(page.getByRole('alert')).toContainText('dados deste lançamento mudaram')
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(page.locator('.posting-panel')).toContainText('Nome revisado')
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  expect(posts).toBe(1)
  await page.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(page.getByText('Este lançamento já está efetivado.', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Confirmar efetivação' })).toHaveCount(0)
  expect(posts).toBe(2)
  await page.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 850,00')
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(1)
})
