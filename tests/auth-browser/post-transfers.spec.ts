import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic transfer confirmation password'
async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `transfer-post-${randomUUID()}@example.com`
  try {
    expect(
      (
        await api.post('/api/v1/auth/register', {
          data: { name: 'Synthetic Transfer Owner', email, password },
        })
      ).status(),
    ).toBe(200)
    await loginSession(api, email, password)
    const ids: string[] = []
    for (const [name, date] of [
      ['Conta origem', '2026-01-01'],
      ['Conta destino', '2026-01-03'],
    ]) {
      const response = await api.post('/api/v1/accounts', {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'Idempotency-Key': randomUUID(),
        },
        data: { name, type: 'checking', opening_balance: '1000.00', opening_date: date },
      })
      expect(response.status()).toBe(201)
      ids.push((await response.json()).id as string)
    }
    const key = randomUUID()
    const body = {
      from_account_id: ids[0],
      to_account_id: ids[1],
      amount: '500.00',
      status: 'planned',
      effective_date: '2026-01-04',
      description: 'Synthetic planned transfer',
    }
    const response = await api.post('/api/v1/transfers', {
      headers: {
        Origin: sessionOrigin,
        'X-CSRF-Token': await sessionCsrf(api),
        'Idempotency-Key': key,
      },
      data: body,
    })
    expect(response.status()).toBe(201)
    return { email, from: ids[0], to: ids[1], id: (await response.json()).id as string, body, key }
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
  await page.getByRole('button', { name: 'Transferências', exact: true }).click()
  await expect(
    page.getByRole('button', { name: 'Cadastrar transferência', exact: true }),
  ).toBeEnabled()
}
async function consult(page: Page, id: string, value: string) {
  await page.getByLabel('Conta para consultar saldo').selectOption(id)
  await page.getByLabel('Saldo até a data').fill('2026-01-04')
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText(value)
}

test('explicit confirmation in two tabs posts the same transfer once and preserves its original creation key', async ({
  page,
  context,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await consult(page, data.from, 'R$ 1.000,00')
  await page.getByRole('button', { name: 'Efetivar transferência', exact: true }).click()
  const panel = page.locator('.posting-panel')
  await expect(panel.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  await expect(panel).toContainText('Conta origem → Conta destino')
  await expect(panel).toContainText('500,00 em 04/01/2026')
  await expect(
    page.getByRole('button', { name: 'Cadastrar transferência', exact: true }),
  ).toBeDisabled()
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await tab.getByRole('button', { name: 'Transferências', exact: true }).click()
  await tab.getByRole('button', { name: 'Efetivar transferência', exact: true }).click()
  await expect(tab.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  let posts = 0
  for (const current of [page, tab])
    current.on('request', (request) => {
      if (request.method() === 'POST' && request.url().endsWith(`/${data.id}/post`)) posts += 1
    })
  await panel.getByRole('button', { name: 'Confirmar efetivação' }).evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await expect(panel.getByRole('status')).toContainText('Esta transferência já está efetivada.')
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await tab.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(tab.locator('.posting-panel').getByRole('status')).toContainText(
    'Esta transferência já está efetivada.',
  )
  expect(posts).toBe(2)
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await expect(page.getByRole('heading', { name: 'Suas transferências' })).toBeFocused()
  const list = page.getByRole('list', { name: 'Transferências cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('Efetivada')
  await consult(page, data.from, 'R$ 500,00')
  await consult(page, data.to, 'R$ 1.500,00')
  const api = privateApi(page.request)
  const replay = await api.post(base + '/api/v1/transfers', {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'Idempotency-Key': data.key,
    },
    data: data.body,
  })
  expect(replay.status()).toBe(201)
  expect(await replay.json()).toEqual({ id: data.id })
  expect((await (await api.get(base + `/api/v1/transfers/${data.id}`)).json()).status).toBe(
    'posted',
  )
  expect((await (await api.get(base + '/api/v1/transactions')).json()).items).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await tab.close()
})

test('changed account names require review and a lost successful confirmation is resolved by GET', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  await page.getByRole('button', { name: 'Efetivar transferência', exact: true }).click()
  const panel = page.locator('.posting-panel')
  await expect(panel.getByRole('button', { name: 'Confirmar efetivação' })).toBeEnabled()
  const api = privateApi(page.request)
  const account = await api.get(base + `/api/v1/accounts/${data.to}`)
  expect(
    (
      await api.patch(base + `/api/v1/accounts/${data.to}`, {
        headers: {
          Origin: sessionOrigin,
          'X-CSRF-Token': await sessionCsrf(api),
          'If-Match': account.headers().etag,
        },
        data: { name: 'Destino revisado' },
      })
    ).status(),
  ).toBe(200)
  let posts = 0
  await page.route(`**/api/v1/transfers/${data.id}/post`, async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    posts += 1
    if (posts === 2) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic confirmation forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(200)
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost transfer confirmation response' }),
      })
    }
    return route.continue()
  })
  await panel.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(panel.getByRole('alert')).toContainText('Os dados desta transferência mudaram')
  await expect(panel.getByRole('button', { name: 'Confirmar efetivação' })).toBeDisabled()
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel).toContainText('Destino revisado')
  await panel.getByRole('button', { name: 'Confirmar efetivação' }).click()
  await expect(panel.getByRole('alert')).toContainText('Não foi possível confirmar o resultado')
  await panel.getByRole('button', { name: 'Recarregar situação' }).click()
  await expect(panel.getByRole('status')).toContainText('Esta transferência já está efetivada.')
  expect(posts).toBe(2)
  await expect(panel.getByRole('button', { name: 'Confirmar efetivação' })).toHaveCount(0)
  await panel.getByRole('button', { name: 'Voltar ao histórico' }).click()
  await consult(page, data.from, 'R$ 500,00')
  await consult(page, data.to, 'R$ 1.500,00')
  await expect(
    page.getByRole('list', { name: 'Transferências cadastradas' }).getByRole('listitem'),
  ).toHaveCount(1)
})
