import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

test.setTimeout(45_000)
const base = 'http://127.0.0.1:8002/api/v1'
const password = 'synthetic import review password'

async function setup(page: Page, request: APIRequestContext, extra = 0) {
  const email = `review-ui-${randomUUID()}@example.com`
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'Synthetic Reviewer', email, password },
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
      name: 'Conta sintética revisão',
      type: 'checking',
      opening_balance: '1000.00',
      opening_date: '2026-01-01',
    },
  })
  expect(account.status()).toBe(201)
  const accountId = (await account.json()).id as string
  const category = await api.post(base + '/categories', {
    headers,
    data: { name: 'Categoria sintética revisão', type: 'expense' },
  })
  expect(category.status()).toBe(201)
  const categoryId = (await category.json()).id as string
  const csv = [
    'Date;Description;Amount',
    '2026-01-01;Corrigir abertura;-10.20',
    '2026-01-02;Revisar compra;-20.00',
    ...Array.from({ length: extra }, (_, i) => `2026-01-02;Compra sintética ${i};-2.50`),
  ].join('\n')
  const job = await api.post(base + '/imports', {
    headers: { ...headers, 'Idempotency-Key': randomUUID() },
    data: {
      account_id: accountId,
      filename: 'synthetic-review.csv',
      content_base64: Buffer.from(csv).toString('base64'),
      mapping: {
        date_column: 0,
        description_column: 1,
        amount_column: 2,
        date_format: 'iso',
        money_format: 'decimal-dot',
      },
    },
  })
  expect(job.status()).toBe(201)
  const jobId = (await job.json()).id as string
  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await page.getByRole('button', { name: 'Consultar prévia', exact: true }).click()
  const preview = page.getByRole('region', { name: 'Consulta da prévia', exact: true })
  await expect(
    preview.getByRole('checkbox', { name: 'Selecionar registro 2', exact: true }),
  ).toBeDisabled()
  return { api, headers, accountId, categoryId, jobId, preview }
}

test('review repairs invalid CSV rows at 320px and preserves loaded pages with explicit selection and no financial posting', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { api, accountId, categoryId, jobId, preview } = await setup(page, request, 50)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  await expect(preview.getByRole('checkbox', { checked: true })).toHaveCount(0)
  await preview
    .getByRole('button', { name: 'Carregar mais registros da prévia', exact: true })
    .click()
  await expect(preview.getByRole('heading', { name: 'Registro 53', exact: true })).toBeVisible()
  await preview.getByRole('button', { name: 'Revisar registro 2', exact: true }).click()
  await page.getByLabel('Data do registro', { exact: true }).fill('2026-01-03')
  await page
    .getByLabel('Descrição do registro', { exact: true })
    .fill('Despesa corrigida sintética')
  await page.getByLabel('Valor absoluto (R$)', { exact: true }).fill('12,34')
  const category = page.getByRole('combobox', { name: 'Categoria do registro', exact: true })
  await category.selectOption(categoryId)
  await page.getByRole('combobox', { name: 'Tipo do registro', exact: true }).selectOption('income')
  await expect(category).toHaveValue('')
  await page
    .getByRole('combobox', { name: 'Tipo do registro', exact: true })
    .selectOption('expense')
  await category.selectOption(categoryId)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  let edits = 0
  page.on('request', (req) => {
    if (
      req.method() === 'PATCH' &&
      /\/imports\/[^/]+\/rows\/[^/]+$/.test(new URL(req.url()).pathname)
    )
      edits++
  })
  await page
    .getByRole('button', { name: 'Salvar correção do registro', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  await expect(
    preview.getByText('Registro atualizado e desmarcado. Confira antes de selecionar.', {
      exact: true,
    }),
  ).toBeVisible()
  expect(edits).toBe(1)
  await expect(
    page.getByRole('region', { name: 'Histórico de prévias', exact: true }),
  ).toContainText('0 inválidos')
  await expect(preview.getByRole('heading', { name: 'Registro 53', exact: true })).toBeVisible()
  const selection = preview.getByRole('checkbox', { name: 'Selecionar registro 2', exact: true })
  await expect(selection).not.toBeChecked()
  await selection.click()
  await expect(selection).toBeChecked()
  await expect(
    preview.getByText('Registro selecionado para revisão. Nenhum lançamento foi criado.', {
      exact: true,
    }),
  ).toBeVisible()
  await expect(preview.getByRole('heading', { name: 'Registro 53', exact: true })).toBeVisible()
  await expect
    .poll(async () => (await (await api.get(`${base}/imports/${jobId}`)).json()).selected_rows)
    .toBe(1)
  await preview.getByRole('button', { name: 'Revisar registro 2', exact: true }).click()
  await page
    .getByLabel('Descrição do registro', { exact: true })
    .fill('Despesa conferida novamente')
  await page.getByRole('button', { name: 'Salvar correção do registro', exact: true }).click()
  await expect(selection).not.toBeChecked()
  await expect
    .poll(async () => (await (await api.get(`${base}/imports/${jobId}`)).json()).selected_rows)
    .toBe(0)
  await expect(preview.getByRole('heading', { name: 'Registro 53', exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect((await (await api.get(base + '/transactions')).json()).items).toEqual([])
  expect(
    (await (await api.get(`${base}/accounts/${accountId}/balance?as_of=2026-01-31`)).json())
      .balance,
  ).toBe('1000.00')
})

test('review preserves conflict drafts, recovers lost selection responses and allows deselection after category archival', async ({
  page,
  request,
}) => {
  const { api, headers, categoryId, jobId, preview } = await setup(page, request)
  const rows = (await (await api.get(`${base}/imports/${jobId}/rows`)).json()).items as {
    id: string
    row_number: number
  }[]
  const rowId = rows.find((row) => row.row_number === 3)!.id
  const path = `${base}/imports/${jobId}/rows/${rowId}`
  await preview.getByRole('button', { name: 'Revisar registro 3', exact: true }).click()
  await page.getByLabel('Descrição do registro', { exact: true }).fill('Rascunho local preservado')
  const current = await api.get(path)
  expect(
    (
      await api.patch(path, {
        headers: { ...headers, 'If-Match': current.headers().etag },
        data: {
          transaction_date: '2026-01-02',
          description: 'Versão externa sintética',
          amount: '25.00',
          type: 'expense',
          category_id: categoryId,
        },
      })
    ).status(),
  ).toBe(200)
  await page.getByRole('button', { name: 'Salvar correção do registro', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('mudou em outra operação')
  await expect(page.getByLabel('Descrição do registro', { exact: true })).toHaveValue(
    'Rascunho local preservado',
  )
  await expect(
    page.getByRole('button', { name: 'Salvar correção do registro', exact: true }),
  ).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar revisão do registro', exact: true }).click()
  await expect(page.getByLabel('Descrição do registro', { exact: true })).toHaveValue(
    'Versão externa sintética',
  )
  await page.getByRole('button', { name: 'Salvar correção do registro', exact: true }).click()
  const selection = preview.getByRole('checkbox', { name: 'Selecionar registro 3', exact: true })
  await expect(selection).toBeEnabled()
  let lost = false
  await page.route('**/api/v1/imports/*/rows/*/selection', async (route) => {
    if (lost || route.request().method() !== 'PATCH') {
      await route.continue()
      return
    }
    lost = true
    const response = await route.fetch().catch(() => {
      throw new Error('Synthetic selection forwarding failed; sensitive details suppressed.')
    })
    expect(response.status()).toBe(200)
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"detail":"Synthetic lost response"}',
    })
  })
  await selection.click()
  await expect(preview.getByRole('alert')).toContainText('Recarregue a prévia')
  await expect(selection).toBeDisabled()
  await preview.getByRole('button', { name: 'Recarregar prévia', exact: true }).click()
  await expect(selection).toBeChecked()
  const category = await api.get(`${base}/categories/${categoryId}`)
  expect(
    (
      await api.patch(`${base}/categories/${categoryId}`, {
        headers: {
          ...headers,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': category.headers().etag,
        },
        data: { is_active: false },
      })
    ).status(),
  ).toBe(200)
  await preview.getByRole('button', { name: 'Recarregar prévia', exact: true }).click()
  await expect(selection).toBeChecked()
  await expect(selection).toBeEnabled()
  await selection.click()
  await expect(selection).not.toBeChecked()
  await expect(selection).toBeDisabled()
  expect((await (await api.get(base + '/transactions')).json()).items).toEqual([])
})
