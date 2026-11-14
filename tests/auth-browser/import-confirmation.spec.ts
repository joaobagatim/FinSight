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

async function ready(page: Page, request: APIRequestContext) {
  const result = await setup(page, request)
  const { api, jobId, categoryId } = result
  const rows = (await (await api.get(`${base}/imports/${jobId}/rows`)).json()).items as {
    id: string
    row_number: number
  }[]
  const rowId = rows.find((row) => row.row_number === 3)!.id
  const path = `${base}/imports/${jobId}/rows/${rowId}`
  const snapshot = await api.get(path)
  const edited = await api.patch(path, {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'If-Match': snapshot.headers().etag,
    },
    data: {
      transaction_date: '2026-01-02',
      description: '<img src=x onerror=window.__confirmation=1>',
      amount: '20.00',
      type: 'expense',
      category_id: categoryId,
    },
  })
  expect(edited.status()).toBe(200)
  expect(
    (
      await api.patch(path + '/selection', {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': edited.headers().etag,
        },
        data: { selected: true },
      })
    ).status(),
  ).toBe(200)
  return result
}

async function acknowledge(page: Page) {
  const form = page.getByRole('form', { name: 'Confirmar seleção CSV', exact: true })
  await expect(form).toBeVisible()
  await expect(form.getByRole('checkbox')).toHaveCount(3)
  for (const checkbox of await form.getByRole('checkbox').all()) await checkbox.check()
  return form.getByRole('button', { name: /Confirmar importação de/ })
}

test('CSV confirmation at 320px requires explicit review, posts once and refreshes receipt and reserve alerts', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { api, accountId, preview } = await ready(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  const goal = await api.post(base + '/goals', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': randomUUID(),
    },
    data: { name: 'Meta sintética confirmação', target_amount: '1500.00' },
  })
  expect(goal.status()).toBe(201)
  const goalId = (await goal.json()).id as string
  const position = await api.get(
    `${base}/goals/${goalId}/allocation-context?account_id=${accountId}`,
  )
  const day = (await position.json()).availability.as_of as string
  expect(
    (
      await api.post(`${base}/goals/${goalId}/allocations`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'Idempotency-Key': randomUUID(),
          'If-Match': position.headers().etag,
        },
        data: { account_id: accountId, kind: 'reserve', amount: '995.00', allocation_date: day },
      })
    ).status(),
  ).toBe(201)
  let posts = 0
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname.endsWith('/confirm')) posts++
  })
  await preview
    .getByRole('button', { name: 'Conferir confirmação da seleção', exact: true })
    .click()
  const confirmation = page.getByRole('region', {
    name: 'Conferir e confirmar importação',
    exact: true,
  })
  await expect(confirmation).toContainText('1 de 2 registro(s) selecionado(s)')
  await expect(confirmation).toContainText('comprometem reservas em R$ 15,00')
  await expect(confirmation.getByRole('button', { name: /Confirmar importação de/ })).toBeDisabled()
  expect(posts).toBe(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  expect(await page.evaluate(() => '__confirmation' in window)).toBe(false)
  await expect(page.locator('img[src="x"]')).toHaveCount(0)
  const confirm = await acknowledge(page)
  await confirm.evaluate((button: HTMLButtonElement) => {
    button.click()
    button.click()
  })
  const receipt = page.getByRole('region', { name: 'Recibo da importação', exact: true })
  await expect(receipt).toContainText('Importação concluída: 1 lançamento(s) criado(s).')
  await expect(receipt).toContainText('1 registro(s) não importado(s), incluindo 1 inválido(s)')
  await expect(receipt).toContainText('R$ 980,00')
  expect(posts).toBe(1)
  await expect(
    page.getByRole('region', { name: 'Alertas de reservas', exact: true }),
  ).toContainText('R$ 15,00 da reserva sem cobertura')
  await expect(
    page.getByRole('region', { name: 'Histórico de prévias', exact: true }),
  ).toContainText('1 lançamentos criados')
  expect((await (await api.get(`${base}/goals/${goalId}/funding`)).json()).reserved_amount).toBe(
    '995.00',
  )
  expect(
    (await (await api.get(`${base}/accounts/${accountId}/balance?as_of=${day}`)).json()).balance,
  ).toBe('980.00')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await receipt.getByRole('button', { name: 'Voltar à prévia', exact: true }).click()
  await page.getByRole('button', { name: 'Consultar recibo da importação', exact: true }).click()
  await expect(receipt).toContainText('1 lançamento(s) criado(s)')
  expect(posts).toBe(1)
})

test('CSV confirmation preserves the same attempt across navigation and recovers a lost receipt after archival', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  const { api, accountId, categoryId, preview } = await ready(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  const sent: { key: string | undefined; etag: string | undefined; body: string | null }[] = []
  await page.route('**/api/v1/imports/*/confirm', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    const headers = route.request().headers()
    sent.push({
      key: headers['idempotency-key'],
      etag: headers['if-match'],
      body: route.request().postData(),
    })
    if (sent.length === 1) {
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: '{"detail":"Synthetic request unavailable"}',
      })
      return
    }
    const response = await route.fetch().catch(() => {
      throw new Error('Synthetic forwarding failed; sensitive details suppressed.')
    })
    expect(response.status()).toBe(200)
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"detail":"Synthetic lost receipt"}',
    })
  })
  await preview
    .getByRole('button', { name: 'Conferir confirmação da seleção', exact: true })
    .click()
  await (await acknowledge(page)).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  await expect(page.getByText(/Há uma confirmação CSV pendente/)).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByRole('button', { name: 'Consultar confirmação CSV', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Repetir mesma confirmação', exact: true }),
  ).toBeEnabled()
  expect(sent).toHaveLength(1)
  await page.getByRole('button', { name: 'Repetir mesma confirmação', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  expect(sent).toHaveLength(2)
  expect(sent[1]).toEqual(sent[0])
  for (const [resource, id] of [
    ['accounts', accountId],
    ['categories', categoryId],
  ]) {
    const current = await api.get(`${base}/${resource}/${id}`)
    expect(
      (
        await api.patch(`${base}/${resource}/${id}`, {
          headers: {
            Origin: sessionOrigin,
            'X-CSRF-Token': await sessionCsrf(api),
            'If-Match': current.headers().etag,
          },
          data: { is_active: false },
        })
      ).status(),
    ).toBe(200)
  }
  await page
    .getByRole('button', { name: 'Consultar resultado da confirmação', exact: true })
    .click()
  await expect(
    page.getByRole('region', { name: 'Recibo da importação', exact: true }),
  ).toContainText('1 lançamento(s) criado(s)')
  expect(sent).toHaveLength(2)
  expect((await (await api.get(base + '/transactions')).json()).items).toHaveLength(1)
  expect(
    await page.evaluate(
      () => Object.keys(localStorage).length + Object.keys(sessionStorage).length,
    ),
  ).toBe(0)
})

test('CSV confirmation requires new acknowledgements after a stale version and clears pending intent at owner change', async ({
  page,
  request,
}) => {
  const { api, categoryId, preview } = await ready(page, request)
  await preview
    .getByRole('button', { name: 'Conferir confirmação da seleção', exact: true })
    .click()
  await expect(page.getByRole('form', { name: 'Confirmar seleção CSV', exact: true })).toBeVisible()
  const category = await api.get(`${base}/categories/${categoryId}`)
  expect(
    (
      await api.patch(`${base}/categories/${categoryId}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': category.headers().etag,
        },
        data: { name: 'Categoria sintética atualizada' },
      })
    ).status(),
  ).toBe(200)
  await (await acknowledge(page)).click()
  await expect(page.getByRole('alert')).toContainText('A seleção ou a posição financeira mudou')
  await expect(
    page.getByRole('button', { name: 'Repetir mesma confirmação', exact: true }),
  ).toBeDisabled()
  await expect(page.getByRole('button', { name: 'Revisar nova versão', exact: true })).toHaveCount(
    0,
  )
  await page
    .getByRole('button', { name: 'Consultar resultado da confirmação', exact: true })
    .click()
  await page.getByRole('button', { name: 'Revisar nova versão', exact: true }).click()
  await expect(
    page
      .getByRole('form', { name: 'Confirmar seleção CSV', exact: true })
      .getByRole('checkbox', { checked: true }),
  ).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Confirmar importação de/ })).toBeDisabled()
  await page.route('**/api/v1/imports/*/confirm', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"detail":"Synthetic pending attempt"}',
    }),
  )
  await (await acknowledge(page)).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  const email = `new-confirmation-owner-${randomUUID()}@example.com`
  expect(
    (
      await privateApi(request).post(base + '/auth/register', {
        data: { name: 'New Synthetic Owner', email, password },
      })
    ).status(),
  ).toBe(200)
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Consultar confirmação CSV', exact: true }),
  ).toHaveCount(0)
  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await expect(page.getByText('Nenhuma prévia guardada.', { exact: true })).toBeVisible()
  await expect(
    page.getByRole('button', { name: 'Retomar confirmação pendente', exact: true }),
  ).toHaveCount(0)
  await expect(
    page.getByRole('region', { name: 'Conferir e confirmar importação', exact: true }),
  ).toHaveCount(0)
})
