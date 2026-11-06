import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic transfer editing password'
async function seed(context: APIRequestContext, status: 'posted' | 'planned' = 'posted') {
  const api = privateApi(context)
  const email = `transfer-edit-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Edit Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const headers = { Origin: sessionOrigin, 'X-CSRF-Token': await sessionCsrf(api) }
    const ids: string[] = []
    for (const [name, opening_date] of [
      ['Conta origem', '2026-01-01'],
      ['Conta destino', '2026-01-03'],
    ]) {
      const response = await api.post('/api/v1/accounts', {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: { name, opening_date, type: 'checking', opening_balance: '1000.00' },
      })
      expect(response.status()).toBe(201)
      ids.push((await response.json()).id as string)
    }
    const key = randomUUID()
    const body = {
      from_account_id: ids[0],
      to_account_id: ids[1],
      amount: '500.00',
      effective_date: '2026-01-04',
      description: 'Synthetic editable transfer',
      status,
    }
    const response = await api.post('/api/v1/transfers', {
      headers: { ...headers, 'Idempotency-Key': key },
      data: body,
    })
    expect(response.status()).toBe(201)
    return { email, from: ids[0], to: ids[1], key, body, id: (await response.json()).id as string }
  } finally {
    await api.dispose()
  }
}
async function openArea(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
}
async function enter(page: Page, email: string) {
  await openArea(page)
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Transferências', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Editar transferência', exact: true }),
  ).toBeEnabled()
}
async function consult(page: Page, account: string, day: string, amount: string) {
  await page.getByLabel('Conta para consultar saldo').selectOption(account)
  await page.getByLabel('Saldo até a data').fill(day)
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText(amount)
}

test('editing an executed transfer changes both sides and date without duplicate financial entries at 320px', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await page.setViewportSize({ width: 320, height: 950 })
  await enter(page, data.email)
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  await consult(page, data.from, '2026-01-04', 'R$ 500,00')
  await page.getByRole('button', { name: 'Editar transferência', exact: true }).click()
  const panel = page.locator('.transfer-edit-panel')
  await expect(panel.getByLabel('Valor da edição (R$)')).toHaveValue('500,00')
  let patches = 0
  page.on('request', (request) => {
    if (request.method() === 'PATCH' && request.url().endsWith(`/transfers/${data.id}`)) patches++
  })
  await panel.getByLabel('Valor da edição (R$)').fill('-1,00')
  await panel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .click()
  await expect(panel.getByRole('alert')).toContainText('maior que zero')
  await panel.getByLabel('Valor da edição (R$)').fill('250,10')
  await panel.getByLabel('Data da edição').fill('2026-01-03')
  await panel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .click()
  await expect(panel.getByRole('alert')).toContainText('posterior à abertura')
  expect(patches).toBe(0)
  await panel.getByLabel('Origem da edição').selectOption(data.to)
  await panel.getByLabel('Destino da edição').selectOption(data.from)
  await panel.getByLabel('Data da edição').fill('2026-01-05')
  await panel.getByLabel('Descrição da edição (opcional)').fill('Transferência ajustada')
  await panel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  await expect(panel.getByRole('status')).toContainText('Os dados conferidos estão salvos')
  await expect(panel).toContainText('Conta destino → Conta origem')
  expect(patches).toBe(1)
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await panel.getByRole('button', { name: 'Voltar às transferências', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Suas transferências', exact: true }),
  ).toBeFocused()
  await consult(page, data.from, '2026-01-04', 'R$ 1.000,00')
  await consult(page, data.from, '2026-01-05', 'R$ 1.250,10')
  await consult(page, data.to, '2026-01-05', 'R$ 749,90')
  const api = privateApi(page.request)
  expect((await api.get(base + '/api/v1/transactions')).ok()).toBeTruthy()
  expect((await (await api.get(base + '/api/v1/transactions')).json()).items).toEqual([])
  const repeated = await api.post(base + '/api/v1/transfers', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': data.key,
    },
    data: data.body,
  })
  expect(repeated.status()).toBe(201)
  expect((await repeated.json()).id).toBe(data.id)
  const history = await (await api.get(base + '/api/v1/transfers')).json()
  expect(history.items).toHaveLength(1)
  expect(history.items[0]).toMatchObject({
    id: data.id,
    amount: '250.10',
    status: 'posted',
    from_account_id: data.to,
    to_account_id: data.from,
  })
})

test('two-tab conflict needs review and a lost edit response is recovered by GET without another PATCH', async ({
  page,
  context,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }), 'planned')
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Editar transferência', exact: true }).click()
  const panel = page.locator('.transfer-edit-panel')
  await expect(panel.getByLabel('Valor da edição (R$)')).toHaveValue('500,00')
  const other = await context.newPage()
  await openArea(other)
  await other.getByRole('button', { name: 'Transferências', exact: true }).click()
  await other.getByRole('button', { name: 'Editar transferência', exact: true }).click()
  const otherPanel = other.locator('.transfer-edit-panel')
  await otherPanel.getByLabel('Valor da edição (R$)').fill('300,00')
  await otherPanel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .click()
  await expect(otherPanel.getByRole('status')).toContainText('Os dados conferidos estão salvos')
  await panel.getByLabel('Valor da edição (R$)').fill('400,00')
  await panel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .click()
  await expect(panel.getByRole('alert')).toContainText('mudou em outra operação')
  await expect(
    panel.getByRole('button', { name: 'Salvar alterações da transferência', exact: true }),
  ).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação', exact: true }).click()
  await expect(panel.getByLabel('Valor da edição (R$)')).toHaveValue('300,00')
  await expect(
    panel.getByRole('button', { name: 'Salvar alterações da transferência', exact: true }),
  ).toBeEnabled()
  let lostPatches = 0
  await page.route(`**/api/v1/transfers/${data.id}`, async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    lostPatches++
    const response = await route.fetch()
    expect(response.status()).toBe(200)
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic lost edit response' }),
    })
  })
  await panel.getByLabel('Valor da edição (R$)').fill('450,00')
  await panel
    .getByRole('button', { name: 'Salvar alterações da transferência', exact: true })
    .click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await panel.getByRole('button', { name: 'Recarregar situação', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('Os dados conferidos estão salvos')
  expect(lostPatches).toBe(1)
  await expect(panel).toContainText('Planejada')
  await panel.getByRole('button', { name: 'Voltar às transferências', exact: true }).click()
  await consult(page, data.from, '2026-01-04', 'R$ 1.000,00')
  await other.close()
})
