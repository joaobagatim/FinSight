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

test('deleting a posted transfer requires confirmation and removes both sides without restoring on creation retry at 320px', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await page.setViewportSize({ width: 320, height: 950 })
  await enter(page, data.email)
  await page.addStyleTag({ content: 'html { font-size: 18px; }' })
  await consult(page, data.from, '2026-01-04', 'R$ 500,00')
  let removals = 0
  page.on('request', (request) => {
    if (request.method() === 'DELETE' && request.url().endsWith(`/transfers/${data.id}`)) removals++
  })
  await page.getByRole('button', { name: 'Excluir transferência', exact: true }).click()
  const panel = page.locator('.transfer-deletion-panel')
  await expect(
    panel.getByRole('heading', { name: 'Excluir transferência', exact: true }),
  ).toBeFocused()
  await expect(panel).toContainText('Conta origem → Conta destino')
  await expect(panel).toContainText('R$ 500,00')
  await expect(panel).toContainText('Efetivada')
  expect(removals).toBe(0)
  await panel.getByRole('button', { name: 'Cancelar exclusão e voltar', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Suas transferências', exact: true }),
  ).toBeFocused()
  expect(removals).toBe(0)
  await page.getByRole('button', { name: 'Excluir transferência', exact: true }).click()
  await expect(
    panel.getByRole('button', { name: 'Confirmar exclusão da transferência', exact: true }),
  ).toBeEnabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await panel
    .getByRole('button', { name: 'Confirmar exclusão da transferência', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  await expect(panel.getByRole('status')).toContainText('não consta mais no histórico')
  expect(removals).toBe(1)
  await panel.getByRole('button', { name: 'Voltar às transferências', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Suas transferências', exact: true }),
  ).toBeFocused()
  await expect(page.getByText('Nenhuma transferência cadastrada.', { exact: true })).toBeVisible()
  await consult(page, data.from, '2026-01-04', 'R$ 1.000,00')
  await consult(page, data.to, '2026-01-04', 'R$ 1.000,00')
  const api = privateApi(page.request)
  const replay = await api.post(base + '/api/v1/transfers', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': data.key,
    },
    data: data.body,
  })
  expect(replay.status()).toBe(410)
  expect((await api.get(base + `/api/v1/transfers/${data.id}`)).status()).toBe(410)
})

test('conflicting transfer deletion needs fresh confirmation and a lost response is recovered by GET without another DELETE', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }), 'planned')
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Excluir transferência', exact: true }).click()
  const panel = page.locator('.transfer-deletion-panel')
  const confirm = panel.getByRole('button', {
    name: 'Confirmar exclusão da transferência',
    exact: true,
  })
  await expect(confirm).toBeEnabled()
  const api = privateApi(page.request)
  const current = await api.get(base + `/api/v1/transfers/${data.id}`)
  const patch = await api.patch(base + `/api/v1/transfers/${data.id}`, {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'If-Match': current.headers().etag,
    },
    data: { amount: '300.00' },
  })
  expect(patch.status()).toBe(200)
  await confirm.click()
  await expect(panel.getByRole('alert')).toContainText('Os dados mudaram')
  await expect(confirm).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação', exact: true }).click()
  await expect(panel).toContainText('R$ 300,00')
  await expect(confirm).toBeEnabled()
  let lostRemovals = 0
  await page.route(`**/api/v1/transfers/${data.id}`, async (route) => {
    if (route.request().method() !== 'DELETE') return route.continue()
    lostRemovals++
    const response = await route.fetch()
    expect(response.status()).toBe(204)
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Synthetic lost removal response' }),
    })
  })
  await confirm.click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await expect(confirm).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação', exact: true }).click()
  await expect(panel.getByRole('status')).toContainText('não consta mais no histórico')
  expect(lostRemovals).toBe(1)
  await panel.getByRole('button', { name: 'Voltar às transferências', exact: true }).click()
  await consult(page, data.from, '2026-01-04', 'R$ 1.000,00')
})
