import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic editing password'

async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `editing-${randomUUID()}@example.com`
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
      status: 'posted',
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
  await expect(page.getByRole('button', { name: 'Editar', exact: true })).toBeEnabled()
}

async function consult(page: Page) {
  await page.getByLabel('Conta para consultar saldo').selectOption({ label: 'Conta de planejados' })
  await page.getByLabel('Saldo até a data').fill('2026-01-04')
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
}

test('manual editing validates money and date, moves balances and preserves one creation identity', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 850,00')
  const api = privateApi(page.request)
  const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
  const account = await api.post(base + '/api/v1/accounts', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: {
      name: 'Conta destino',
      type: 'savings',
      opening_balance: '10.00',
      opening_date: '2026-01-03',
    },
  })
  expect(account.status()).toBe(201)
  const targetId = (await account.json()).id as string
  const income = await api.post(base + '/api/v1/categories', {
    headers,
    data: { name: 'Receita da edição', type: 'income' },
  })
  expect(income.status()).toBe(201)
  await page.getByRole('button', { name: 'Atualizar contas e categorias', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Atualizar contas e categorias', exact: true }),
  ).toBeEnabled()
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const panel = page.locator('.editing-panel')
  await expect(panel.getByLabel('Descrição da edição')).toHaveValue('Planejado sintético')
  await expect(
    page.getByRole('button', { name: 'Cadastrar lançamento', exact: true }),
  ).toBeDisabled()
  let patches = 0
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && request.url().endsWith(`/${data.id}`)) patches += 1
  })
  await panel.getByLabel('Valor da edição (R$)').fill('-1,00')
  await panel.getByRole('button', { name: 'Salvar alterações do lançamento' }).click()
  await expect(panel.getByRole('alert')).toContainText('maior que zero')
  await panel.getByLabel('Valor da edição (R$)').fill('0,10')
  await panel.getByLabel('Conta da edição').selectOption({ label: 'Conta destino' })
  await panel.getByLabel('Data da edição').fill('2026-01-03')
  await panel.getByRole('button', { name: 'Salvar alterações do lançamento' }).click()
  await expect(panel.getByRole('alert')).toContainText('posterior à abertura')
  expect(patches).toBe(0)
  await panel.getByLabel('Data da edição').fill('2026-01-04')
  await panel.getByLabel('Descrição da edição').fill('Receita corrigida')
  await panel.getByLabel('Tipo da edição').selectOption('income')
  await panel.getByLabel('Categoria da edição').selectOption({ label: 'Receita da edição' })
  await panel.getByLabel('Observações da edição').fill('Nota sintética atualizada')
  await panel
    .getByRole('button', { name: 'Salvar alterações do lançamento' })
    .evaluate((button) => {
      ;(button as HTMLButtonElement).click()
      ;(button as HTMLButtonElement).click()
    })
  await expect(panel.getByRole('status')).toContainText('Os dados conferidos estão salvos')
  expect(patches).toBe(1)
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await expect(page.getByRole('heading', { name: 'Seus lançamentos' })).toBeFocused()
  const list = page.getByRole('list', { name: 'Lançamentos cadastrados' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('Receita corrigida')
  await expect(list).toContainText('Efetivado')
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 1.000,00')
  await page.getByLabel('Conta para consultar saldo').selectOption(targetId)
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText('R$ 10,10')
  const replay = await api.post(base + '/api/v1/transactions', {
    headers: { ...headers, 'X-CSRF-Token': await sessionCsrf(api), 'Idempotency-Key': data.key },
    data: data.body,
  })
  expect(replay.status()).toBe(201)
  expect(await replay.json()).toEqual({ id: data.id })
  expect((await (await api.get(base + `/api/v1/transactions/${data.id}`)).json()).description).toBe(
    'Receita corrigida',
  )
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('stale edits require review and a lost successful PATCH is resolved by GET without resubmission', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const panel = page.locator('.editing-panel')
  await expect(panel.getByLabel('Descrição da edição')).toBeEnabled()
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
        data: { description: 'Edição concorrente', amount: '175.00' },
      })
    ).status(),
  ).toBe(200)
  let patches = 0
  await page.route(`**/api/v1/transactions/${data.id}`, async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    patches += 1
    if (patches === 2) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(200)
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost editing response' }),
      })
    }
    return route.continue()
  })
  await panel.getByLabel('Valor da edição (R$)').fill('200,00')
  await panel.getByRole('button', { name: 'Salvar alterações do lançamento' }).click()
  await expect(panel.getByRole('alert')).toContainText('mudou em outra operação')
  await expect(
    panel.getByRole('button', { name: 'Salvar alterações do lançamento' }),
  ).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel.getByLabel('Descrição da edição')).toHaveValue('Edição concorrente')
  await expect(panel.getByLabel('Valor da edição (R$)')).toHaveValue('175,00')
  await panel.getByLabel('Valor da edição (R$)').fill('200,00')
  await panel.getByRole('button', { name: 'Salvar alterações do lançamento' }).click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel.getByRole('status')).toContainText('Os dados conferidos estão salvos')
  expect(patches).toBe(2)
  await expect(panel.getByRole('button', { name: 'Salvar alterações do lançamento' })).toHaveCount(
    0,
  )
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 800,00')
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(1)
})
