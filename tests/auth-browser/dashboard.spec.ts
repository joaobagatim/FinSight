import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test.setTimeout(45_000)
const base = 'http://127.0.0.1:8002/api/v1'
const password = 'synthetic dashboard screen password'

async function register(request: APIRequestContext) {
  const email = `dashboard-${randomUUID()}@example.com`
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'Synthetic Dashboard Owner', email, password },
      })
    ).status(),
  ).toBe(200)
  return email
}

async function login(page: Page, email: string) {
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
}

async function seed(page: Page, request: APIRequestContext) {
  const email = await register(request)
  await page.goto('/')
  await login(page, email)
  const api = privateApi(page.request)
  const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
  const ids: string[] = []
  for (const name of ['Conta sintética ativa', 'Conta sintética arquivada']) {
    const response = await api.post(base + '/accounts', {
      headers: { ...headers, 'Idempotency-Key': randomUUID() },
      data: { name, type: 'checking', opening_balance: '1000.00', opening_date: '2026-01-01' },
    })
    expect(response.status()).toBe(201)
    ids.push((await response.json()).id as string)
  }
  for (const kind of ['income', 'expense']) {
    const category = await api.post(base + '/categories', {
      headers,
      data: { name: `Synthetic ${kind}`, type: kind },
    })
    expect(category.status()).toBe(201)
    const categoryId = (await category.json()).id as string
    const amounts =
      kind === 'income'
        ? [['100.10', ids[0], '2026-01-02']]
        : [
            ['30.01', ids[0], '2026-01-31'],
            ['20.00', ids[1], '2026-01-15'],
          ]
    for (const [amount, accountId, date] of amounts) {
      expect(
        (
          await api.post(base + '/transactions', {
            headers: { ...headers, 'Idempotency-Key': randomUUID() },
            data: {
              account_id: accountId,
              category_id: categoryId,
              description: 'Synthetic dashboard movement',
              amount,
              type: kind,
              status: 'posted',
              effective_date: date,
            },
          })
        ).status(),
      ).toBe(201)
    }
  }
  const account = await api.get(`${base}/accounts/${ids[1]}`)
  expect(
    (
      await api.patch(`${base}/accounts/${ids[1]}`, {
        headers: { ...headers, 'If-Match': account.headers().etag },
        data: { is_active: false },
      })
    ).status(),
  ).toBe(200)
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  const result = page.getByRole('region', { name: 'Indicadores consultados', exact: true })
  await expect(result).toBeVisible()
  return { result }
}

async function period(page: Page) {
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-01-02')
  await page.getByLabel('Data final', { exact: true }).fill('2026-01-31')
}

test('dashboard at 320px shows exact period cards for active, all and selected archived accounts with explicit empty states', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { result } = await seed(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  await period(page)
  await expect(result).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result).toContainText('De 02/01/2026 a 31/01/2026, inclusive.')
  await expect(result).toContainText('2 lançamento(s)')
  await expect(result.locator('dd')).toHaveText(['R$ 100,10', 'R$ 30,01', 'R$ 70,09'])
  const scope = page.getByLabel('Contas incluídas nos indicadores', { exact: true })
  await scope.selectOption('all')
  await expect(result).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result.locator('dd')).toHaveText(['R$ 100,10', 'R$ 50,01', 'R$ 50,09'])
  await scope.selectOption('selected')
  await page
    .getByRole('checkbox', { name: 'Conta sintética arquivada · Arquivada', exact: true })
    .check()
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result.locator('dd')).toHaveText(['R$ 0,00', 'R$ 20,00', '−R$ 20,00'])
  await expect(
    result.getByRole('list', { name: 'Contas consultadas nos indicadores' }),
  ).toContainText('Conta sintética arquivada')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-01-16')
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result.locator('dd')).toHaveText(['R$ 0,00', 'R$ 0,00', 'R$ 0,00'])
  await expect(result).toContainText('Nenhum lançamento efetivado neste período')
  await page
    .getByRole('button', { name: 'Atualizar contas e limpar seleção dos indicadores', exact: true })
    .click()
  await expect(result).toHaveCount(0)
  await expect(page.getByRole('checkbox', { checked: true })).toHaveCount(0)
  await page.getByLabel('Data inicial', { exact: true }).fill('2026-02-01')
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('período válido de até 366 dias')
})

test('dashboard discards late filter responses, hides malformed totals and clears financial data at owner change', async ({
  page,
  request,
}) => {
  const { result } = await seed(page, request)
  await period(page)
  let release!: () => void
  let ready!: () => void
  const pending = new Promise<void>((resolve) => {
    release = resolve
  })
  const started = new Promise<void>((resolve) => {
    ready = resolve
  })
  await page.route(
    '**/api/v1/dashboard/summary?**',
    async (route) => {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic forwarding failed; sensitive details suppressed.')
      })
      ready()
      await pending
      await route.fulfill({ response })
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await started
  await page.getByLabel('Data final', { exact: true }).fill('2026-01-30')
  const finished = page.waitForResponse((response) =>
    response.url().includes('/dashboard/summary?'),
  )
  release()
  await finished
  await page.evaluate(
    () =>
      new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      ),
  )
  await expect(result).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result.locator('dd')).toHaveText(['R$ 100,10', 'R$ 0,00', 'R$ 100,10'])
  await page.route(
    '**/api/v1/dashboard/summary?**',
    async (route) => {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic forwarding failed; sensitive details suppressed.')
      })
      const data = await response.json()
      await route.fulfill({ response, json: { ...data, net: '999.99' } })
    },
    { times: 1 },
  )
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não conseguimos acessar o serviço')
  await expect(result).toHaveCount(0)
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  await expect(result).toContainText('R$ 100,10')
  const other = await register(request)
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await login(page, other)
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  await expect(result).toContainText('0 conta(s) · 0 lançamento(s)')
  await expect(result.locator('dd')).toHaveText(['R$ 0,00', 'R$ 0,00', 'R$ 0,00'])
  expect(
    await page.evaluate(
      () => Object.keys(localStorage).length + Object.keys(sessionStorage).length,
    ),
  ).toBe(0)
})
