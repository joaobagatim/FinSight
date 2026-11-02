import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const password = 'synthetic movements interface password'

function deferred() {
  let resolve = () => {}
  const promise = new Promise<void>((ready) => {
    resolve = ready
  })
  return { promise, resolve: () => resolve() }
}

async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `movement-ui-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Movement Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const account = await api.post('/api/v1/accounts', {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: {
        name: 'Conta sintética',
        type: 'checking',
        opening_balance: '1000.00',
        opening_date: '2026-01-01',
      },
    })
    expect(account.status()).toBe(201)
    for (const [name, type] of [
      ['Alimentação', 'expense'],
      ['Salário', 'income'],
    ])
      expect(
        (await api.post('/api/v1/categories', { headers, data: { name, type } })).status(),
      ).toBe(201)
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
  await page.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Atualizar contas e categorias' })).toBeEnabled()
}

async function fill(
  page: Page,
  description: string,
  amount: string,
  status = 'posted',
  type = 'expense',
) {
  await page.getByLabel('Tipo de lançamento', { exact: true }).selectOption(type)
  await page.getByLabel('Descrição', { exact: true }).fill(description)
  await page
    .getByLabel('Conta do lançamento', { exact: true })
    .selectOption({ label: 'Conta sintética' })
  await page
    .getByLabel('Categoria do lançamento', { exact: true })
    .selectOption({ label: type === 'income' ? 'Salário' : 'Alimentação' })
  await page.getByLabel('Valor (R$)', { exact: true }).fill(amount)
  await page.getByLabel('Data do lançamento', { exact: true }).fill('2026-01-02')
  await page.getByLabel('Situação do lançamento', { exact: true }).selectOption(status)
}

async function consult(page: Page, day = '2026-01-04') {
  await page
    .getByLabel('Conta para consultar saldo', { exact: true })
    .selectOption({ label: 'Conta sintética' })
  await page.getByLabel('Saldo até a data', { exact: true }).fill(day)
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
}

test('manual movement screen validates inputs and separates real and planned balances at 320px', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await enter(
    page,
    await seed(await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' })),
  )
  await expect(page.getByText('Seu histórico começa aqui.')).toBeVisible()
  await fill(page, 'Mercado sintético', '-10,00')
  await page.getByLabel('Observações (opcional)', { exact: true }).fill('Anotação sintética')
  await expect(
    page
      .getByLabel('Categoria do lançamento')
      .getByRole('option', { name: 'Salário', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).click()
  await expect(page.getByRole('alert')).toContainText('valor maior que zero')
  await page.getByLabel('Valor (R$)', { exact: true }).fill('150,25')
  await page.getByLabel('Data do lançamento', { exact: true }).fill('2026-01-01')
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).click()
  await expect(page.getByRole('alert')).toContainText('posterior a 01/01/2026')
  await page.getByLabel('Data do lançamento', { exact: true }).fill('2026-01-02')
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).click()
  const list = page.getByRole('list', { name: 'Lançamentos cadastrados' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('Conta sintética · Alimentação')
  await expect(list).toContainText('−R$ 150,25')
  await list.getByText('Observações', { exact: true }).click()
  await expect(list).toContainText('Anotação sintética')
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 849,75')
  await fill(page, 'Entrada sintética', '0,10', 'posted', 'income')
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(2)
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 849,85')
  await fill(page, 'Despesa planejada', '200,00', 'planned')
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(3)
  await expect(list).toContainText('Planejado')
  await consult(page)
  await expect(page.locator('.balance-result')).toContainText('R$ 849,85')
  await page.getByLabel('Saldo até a data').fill('2026-01-01')
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText('R$ 1.000,00')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('lost financial response survives navigation with one key and clears after logout', async ({
  page,
  playwright,
}) => {
  await enter(
    page,
    await seed(await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' })),
  )
  const keys: string[] = []
  const bodies: unknown[] = []
  const saved = deferred()
  const released = deferred()
  await page.route('**/api/v1/transactions', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push((await route.request().headerValue('Idempotency-Key')) ?? '')
    bodies.push(route.request().postDataJSON())
    if (keys.length === 1) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic movement forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(201)
      saved.resolve()
      await released.promise
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost response' }),
      })
    }
    if (keys.length === 2)
      return route.fulfill({
        status: 403,
        headers: {
          'Access-Control-Allow-Origin': sessionOrigin,
          'Access-Control-Allow-Credentials': 'true',
          'Cache-Control': 'no-store',
        },
        body: JSON.stringify({ detail: 'Synthetic rejected retry' }),
        contentType: 'application/json',
      })
    return route.continue()
  })
  await fill(page, 'Tentativa preservada', '123,45')
  await page.getByRole('button', { name: 'Cadastrar lançamento' }).evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await saved.promise
  expect(keys).toHaveLength(1)
  await page.getByRole('button', { name: 'Categorias', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas categorias' })).toBeVisible()
  released.resolve()
  await expect(page.getByRole('button', { name: 'Atualizar categorias' })).toBeEnabled()
  await page.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await expect(page.getByLabel('Descrição', { exact: true })).toHaveValue('Tentativa preservada')
  await expect(page.getByLabel('Descrição', { exact: true })).toBeDisabled()
  expect(keys).toHaveLength(1)
  await page.getByRole('button', { name: 'Conferir e repetir tentativa' }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível validar')
  await expect(page.getByLabel('Descrição', { exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Revisar dados da tentativa' })).toHaveCount(0)
  expect(keys).toHaveLength(2)
  await page.getByRole('button', { name: 'Conferir e repetir tentativa' }).click()
  await expect(
    page.getByText('Lançamento cadastrado. Consulte o saldo na data desejada.'),
  ).toBeVisible()
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(1)
  await expect(page.getByRole('button', { name: 'Conferir e repetir tentativa' })).toHaveCount(0)
  expect(keys).toHaveLength(3)
  expect(keys[0]).toBe(keys[1])
  expect(keys[0]).toBe(keys[2])
  expect(bodies[0]).toEqual(bodies[1])
  expect(bodies[0]).toEqual(bodies[2])
  await page.unroute('**/api/v1/transactions')
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await enter(
    page,
    await seed(await playwright.request.newContext({ baseURL: 'http://127.0.0.1:8002' })),
  )
  await expect(
    page.getByRole('list', { name: 'Lançamentos cadastrados' }).getByRole('listitem'),
  ).toHaveCount(0)
  await expect(page.getByLabel('Descrição', { exact: true })).toHaveValue('')
  await expect(page.getByRole('button', { name: 'Conferir e repetir tentativa' })).toHaveCount(0)
})
