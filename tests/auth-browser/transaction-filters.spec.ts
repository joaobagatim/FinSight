import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic transaction filters password'
async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `filters-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Filter Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const accounts: string[] = []
    for (const name of ['Conta principal', 'Conta secundária']) {
      const response = await api.post('/api/v1/accounts', {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: { name, type: 'checking', opening_balance: '1000.00', opening_date: '2026-01-01' },
      })
      expect(response.status()).toBe(201)
      accounts.push((await response.json()).id as string)
    }
    const categories: string[] = []
    for (const [name, type] of [
      ['Casa', 'expense'],
      ['Salário', 'income'],
    ]) {
      const response = await api.post('/api/v1/categories', { headers, data: { name, type } })
      expect(response.status()).toBe(201)
      categories.push((await response.json()).id as string)
    }
    const records = [
      ['Mercado 100%_/ Café efetivado', 'posted', '2026-01-02', 0, 0, 'expense'],
      ['Mercado 100%_/ Café planejado A', 'planned', '2026-01-03', 0, 0, 'expense'],
      ['Mercado 100%_/ Café planejado B', 'planned', '2026-01-04', 0, 0, 'expense'],
      ['Mercado 100xx/ Café', 'posted', '2026-01-03', 1, 0, 'expense'],
      ['Pagamento sintético', 'posted', '2026-01-04', 1, 1, 'income'],
    ] as const
    for (const [description, status, date, account, category, type] of records) {
      expect(
        (
          await api.post('/api/v1/transactions', {
            headers: { ...headers, 'Idempotency-Key': randomUUID() },
            data: {
              account_id: accounts[account],
              category_id: categories[category],
              description,
              status,
              effective_date: date,
              type,
              amount: '10.00',
            },
          })
        ).status(),
      ).toBe(201)
    }
    return { email, account: accounts[0], category: categories[0] }
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
  await expect(page.getByRole('button', { name: 'Aplicar filtros', exact: true })).toBeEnabled()
}

test('combined history filters keep their query across pages, clear safely and fit 320px', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  const queries: URLSearchParams[] = []
  // Use real API pagination with one row per page to exercise append without seeding 51 rows.
  await page.route('**/api/v1/transactions?**', async (route) => {
    const url = new URL(route.request().url())
    queries.push(new URLSearchParams(url.search))
    if (url.searchParams.has('q')) url.searchParams.set('limit', '1')
    await route.continue({ url: url.toString() })
  })
  await enter(page, data.email)
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  const form = page.getByRole('form', { name: 'Filtrar lançamentos' })
  const cards = page.getByRole('list', { name: 'Lançamentos cadastrados' })
  await form.getByLabel('Pesquisar na descrição').fill('100%_/ cAFÉ')
  await expect(cards).toHaveCount(0)
  await form.getByLabel('Conta do histórico').selectOption(data.account)
  await form.getByLabel('Categoria do histórico').selectOption(data.category)
  await form.getByLabel('Tipo do movimento').selectOption('expense')
  await form.getByLabel('Situação do movimento').selectOption('planned')
  await form.getByLabel('Data inicial (inclusive)').fill('2026-01-03')
  await form.getByLabel('Data final (inclusive)').fill('2026-01-04')
  await form.getByRole('button', { name: 'Aplicar filtros', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(1)
  await expect(cards).toContainText('Mercado 100%_/ Café planejado B')
  await page.getByRole('button', { name: 'Carregar mais lançamentos', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(2)
  const appended = queries.find((query) => query.get('offset') === '1')
  expect(appended && Object.fromEntries(appended)).toMatchObject({
    q: '100%_/ cAFÉ',
    account_id: data.account,
    category_id: data.category,
    type: 'expense',
    status: 'planned',
    date_from: '2026-01-03',
    date_to: '2026-01-04',
  })
  await form.getByLabel('Data final (inclusive)').fill('2026-01-02')
  await form.getByRole('button', { name: 'Aplicar filtros', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('data inicial')
  await expect(cards).toHaveCount(0)
  await form.getByRole('button', { name: 'Limpar filtros', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(5)
  await expect(form.getByLabel('Pesquisar na descrição')).toHaveValue('')
  expect(queries.at(-1)?.get('q')).toBeNull()
  expect(queries.at(-1)?.get('offset')).toBe('0')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('posting reapplies the active history filter and unavailable search never fabricates empty results', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  const form = page.getByRole('form', { name: 'Filtrar lançamentos' })
  const cards = page.getByRole('list', { name: 'Lançamentos cadastrados' })
  await form.getByLabel('Pesquisar na descrição').fill('Café planejado A')
  await form.getByLabel('Situação do movimento').selectOption('planned')
  await form.getByRole('button', { name: 'Aplicar filtros', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(1)
  await cards.getByRole('button', { name: 'Efetivar', exact: true }).click()
  await expect(form.getByLabel('Pesquisar na descrição')).toBeDisabled()
  await page.getByRole('button', { name: 'Confirmar efetivação', exact: true }).click()
  await expect(page.getByText('Este lançamento já está efetivado.', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Voltar ao histórico', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Nenhum lançamento encontrado.', exact: true }),
  ).toBeVisible()
  await expect(form.getByLabel('Situação do movimento')).toHaveValue('planned')
  await form.getByLabel('Situação do movimento').selectOption('posted')
  await form.getByRole('button', { name: 'Aplicar filtros', exact: true }).click()
  await expect(cards.getByRole('listitem')).toHaveCount(1)
  await page.route('**/api/v1/transactions?**', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic search unavailable' }),
    }),
  )
  await form.getByLabel('Pesquisar na descrição').fill('outro termo')
  await form.getByRole('button', { name: 'Aplicar filtros', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não conseguimos acessar o serviço')
  await expect(cards.getByRole('listitem')).toHaveCount(0)
  await expect(
    page.getByRole('heading', { name: 'Nenhum lançamento encontrado.', exact: true }),
  ).toHaveCount(0)
})
