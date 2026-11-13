import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test.setTimeout(45_000)
const base = 'http://127.0.0.1:8002/api/v1'
const password = 'synthetic import screen password'

async function signIn(page: Page, email: string) {
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
}

async function setup(page: Page, request: APIRequestContext) {
  const email = `imports-ui-${randomUUID()}@example.com`
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'Synthetic Import Owner', email, password },
      })
    ).status(),
  ).toBe(200)
  await page.goto('/')
  await signIn(page, email)
  const api = privateApi(page.request)
  const account = await api.post(base + '/accounts', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': randomUUID(),
    },
    data: {
      name: 'Conta sintética CSV',
      type: 'checking',
      opening_balance: '1000.00',
      opening_date: '2026-01-01',
    },
  })
  expect(account.status()).toBe(201)
  const accountId = (await account.json()).id as string
  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await expect(page.getByText('Nenhuma prévia guardada.', { exact: true })).toBeVisible()
  await page
    .getByRole('combobox', { name: 'Conta de destino', exact: true })
    .selectOption(accountId)
  return { api, accountId }
}

async function map(page: Page, format: 'comma' | 'dot', split = false) {
  const form = page.getByRole('form', { name: 'Mapear colunas do CSV', exact: true })
  await form.getByRole('combobox', { name: 'Coluna de data', exact: true }).selectOption('0')
  await form.getByRole('combobox', { name: 'Coluna de descrição', exact: true }).selectOption('1')
  if (split) {
    await form
      .getByRole('combobox', { name: 'Organização dos valores', exact: true })
      .selectOption('split')
    await form.getByRole('combobox', { name: 'Coluna de débito', exact: true }).selectOption('2')
    await form.getByRole('combobox', { name: 'Coluna de crédito', exact: true }).selectOption('3')
  } else {
    await form.getByRole('combobox', { name: 'Coluna de valor', exact: true }).selectOption('2')
  }
  await form
    .getByRole('combobox', { name: 'Formato das datas', exact: true })
    .selectOption(format === 'comma' ? 'day-first' : 'iso')
  await form
    .getByRole('combobox', { name: 'Formato dos valores', exact: true })
    .selectOption(format === 'comma' ? 'decimal-comma' : 'decimal-dot')
  return form
}

test('CSV preview at 320px rejects oversized input and duplicate mapping, then shows exact paginated rows without changing balances', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { api, accountId } = await setup(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  let inspections = 0,
    creations = 0
  page.on('request', (req) => {
    if (req.method() !== 'POST') return
    const path = new URL(req.url()).pathname
    if (path === '/api/v1/imports/inspect') inspections++
    if (path === '/api/v1/imports') creations++
  })
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles({
    name: 'oversized.csv',
    mimeType: 'text/csv',
    buffer: Buffer.alloc(1024 * 1024 + 1),
  })
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('no máximo 1 MiB')
  expect(inspections).toBe(0)
  const content = [
    '\ufeffQuando;Texto;Quantia;Codigo',
    '02/01/2026;Compra sintética;-1.234,56;synthetic-1',
    '02/01/2026;Compra sintética;-1.234,56;synthetic-1',
    '01/01/2026;Abertura;12,00;synthetic-2',
    '03/01/2026;<img src=x onerror=window.__csvExecuted=1>;0;synthetic-3',
    ...Array.from(
      { length: 48 },
      (_, index) => `04/01/2026;Receita sintética ${index};2,50;synthetic-${index + 4}`,
    ),
  ].join('\r\n')
  const file = { name: 'synthetic-52.csv', mimeType: 'text/csv', buffer: Buffer.from(content) }
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles(file)
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Amostra e mapeamento', exact: true }),
  ).toBeVisible()
  expect((await (await api.get(base + '/imports')).json()).items).toEqual([])
  const form = await map(page, 'comma')
  await form
    .getByRole('combobox', { name: 'Coluna de referência (opcional)', exact: true })
    .selectOption('3')
  await form.getByRole('combobox', { name: 'Coluna de descrição', exact: true }).selectOption('0')
  await form.getByRole('button', { name: 'Guardar prévia para revisão', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('coluna diferente')
  expect(creations).toBe(0)
  await form.getByRole('combobox', { name: 'Coluna de descrição', exact: true }).selectOption('1')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await form
    .getByRole('button', { name: 'Guardar prévia para revisão', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  const preview = page.getByRole('region', { name: 'Consulta da prévia', exact: true })
  const rows = preview
    .getByRole('list', { name: 'Registros da prévia', exact: true })
    .getByRole('listitem')
    .filter({ has: page.getByRole('heading', { level: 4 }) })
  await expect(rows).toHaveCount(50)
  await expect(rows.nth(0)).toContainText('R$ 1.234,56')
  await expect(rows.nth(1)).toContainText('R$ 1.234,56')
  await expect(rows.nth(2)).toContainText('anterior ou igual à abertura')
  await expect(rows.nth(3)).toContainText('Valor inválido')
  await expect(page.locator('img[src="x"]')).toHaveCount(0)
  expect(await page.evaluate(() => '__csvExecuted' in window)).toBe(false)
  await preview
    .getByRole('button', { name: 'Carregar mais registros da prévia', exact: true })
    .click()
  await expect(rows).toHaveCount(52)
  expect(creations).toBe(1)
  expect(
    (await (await api.get(`${base}/accounts/${accountId}/balance?as_of=2026-01-31`)).json())
      .balance,
  ).toBe('1000.00')
  expect((await (await api.get(base + '/transactions')).json()).items).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await preview.getByRole('button', { name: 'Voltar ao envio de CSV', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Conta de destino', exact: true })
    .selectOption(accountId)
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles(file)
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  await expect(page.getByText(/Já existem 1 prévia\(s\) com esse mesmo arquivo/)).toBeVisible()
})

test('lost preview response reuses its key across navigation and archival; logout clears an unfinished file before another owner signs in', async ({
  page,
  request,
}) => {
  const { api, accountId } = await setup(page, request)
  const keys: string[] = []
  await page.route('**/api/v1/imports', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'])
    if (keys.length === 3)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic unavailable response' }),
      })
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    if (keys.length === 1)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic lost preview response' }),
      })
    return route.fulfill({ response })
  })
  const file = {
    name: 'private-synthetic-retry.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      'Data,Descricao,Debito,Credito\n2026-01-02,Despesa sintética,10.20,\n2026-01-03,Receita sintética,,30.00\n',
    ),
  }
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles(file)
  await page.getByRole('combobox', { name: 'Separador do arquivo', exact: true }).selectOption(',')
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Amostra e mapeamento', exact: true }),
  ).toBeVisible()
  const form = await map(page, 'dot', true)
  await form.getByRole('button', { name: 'Guardar prévia para revisão', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  const current = await api.get(`${base}/accounts/${accountId}`)
  expect(
    (
      await api.patch(`${base}/accounts/${accountId}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': current.headers().etag,
        },
        data: { is_active: false },
      })
    ).status(),
  ).toBe(200)
  await page
    .getByRole('button', { name: 'Conferir e repetir envio da prévia', exact: true })
    .click()
  await expect(page.getByRole('region', { name: 'Consulta da prévia', exact: true })).toContainText(
    'Conta arquivada',
  )
  await expect(
    page.getByText('Prévia guardada. Nenhum lançamento foi criado.', { exact: true }),
  ).toBeVisible()
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  expect((await (await api.get(base + '/imports')).json()).items).toHaveLength(1)
  const archived = await api.get(`${base}/accounts/${accountId}`)
  expect(
    (
      await api.patch(`${base}/accounts/${accountId}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': archived.headers().etag,
        },
        data: { is_active: true },
      })
    ).status(),
  ).toBe(200)
  await page.getByRole('button', { name: 'Voltar ao envio de CSV', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Conta de destino', exact: true })
    .selectOption(accountId)
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles(file)
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Amostra e mapeamento', exact: true }),
  ).toBeVisible()
  await map(page, 'dot', true)
  await page.getByRole('button', { name: 'Guardar prévia para revisão', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Conferir e repetir envio da prévia', exact: true }),
  ).toBeVisible()
  const other = `imports-other-${randomUUID()}@example.com`
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'Synthetic Other Import Owner', email: other, password },
      })
    ).status(),
  ).toBe(200)
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await signIn(page, other)
  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await expect(page.getByText('Nenhuma prévia guardada.', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Conferir e repetir envio da prévia', exact: true }),
  ).toHaveCount(0)
  await expect(page.getByText(file.name, { exact: true })).toHaveCount(0)
  expect(keys).toHaveLength(3)
})
