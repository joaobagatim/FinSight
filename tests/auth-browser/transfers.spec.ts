import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'
import { loginSession, privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

const base = 'http://127.0.0.1:8002'
const password = 'synthetic internal transfer password'
async function seed(context: APIRequestContext) {
  const api = privateApi(context)
  const email = `transfer-${randomUUID()}@example.com`
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
    return { email, from: ids[0], to: ids[1] }
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
async function fill(page: Page, from: string, to: string) {
  await page.getByLabel('Conta de origem', { exact: true }).selectOption(from)
  await page.getByLabel('Conta de destino', { exact: true }).selectOption(to)
  await page.getByLabel('Valor da transferência (R$)').fill('500,00')
  await page.getByLabel('Data da transferência').fill('2026-01-04')
  await page.getByLabel('Situação da transferência').selectOption('posted')
}

test('transfers validate both accounts and dates, conserve balances and do not create income or expenses', async ({
  page,
  playwright,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  let posts = 0
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.url().endsWith('/transfers')) posts += 1
  })
  await fill(page, data.from, data.from)
  await page.getByRole('button', { name: 'Cadastrar transferência', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('distintas')
  await fill(page, data.from, data.to)
  await page.getByLabel('Data da transferência').fill('2026-01-03')
  await page.getByRole('button', { name: 'Cadastrar transferência', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('posterior à abertura')
  await page.getByLabel('Data da transferência').fill('2026-01-04')
  await page.getByLabel('Valor da transferência (R$)').fill('-1,00')
  await page.getByRole('button', { name: 'Cadastrar transferência', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('maior que zero')
  expect(posts).toBe(0)
  await page.getByLabel('Valor da transferência (R$)').fill('500,00')
  await page
    .getByRole('button', { name: 'Cadastrar transferência', exact: true })
    .evaluate((button) => {
      ;(button as HTMLButtonElement).click()
      ;(button as HTMLButtonElement).click()
    })
  await expect(
    page.getByText('Transferência cadastrada. Consulte o saldo das duas contas na data desejada.'),
  ).toBeVisible()
  expect(posts).toBe(1)
  const list = page.getByRole('list', { name: 'Transferências cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('Conta origem → Conta destino')
  await consult(page, data.from, 'R$ 500,00')
  await consult(page, data.to, 'R$ 1.500,00')
  await fill(page, data.from, data.to)
  await page.getByLabel('Situação da transferência').selectOption('planned')
  await page.getByRole('button', { name: 'Cadastrar transferência', exact: true }).click()
  await expect(list.getByRole('listitem')).toHaveCount(2)
  await expect(list).toContainText('Planejada')
  await expect(page.locator('.balance-result')).toHaveCount(0)
  await consult(page, data.from, 'R$ 500,00')
  const api = privateApi(page.request)
  expect((await (await api.get(base + '/api/v1/transactions')).json()).items).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('an uncertain transfer survives navigation and a rejected retry while keeping the same key and body', async ({
  page,
  playwright,
}) => {
  const data = await seed(await playwright.request.newContext({ baseURL: base }))
  await enter(page, data.email)
  const requests: { key: string | undefined; body: unknown }[] = []
  let release!: () => void
  let received!: () => void
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  const created = new Promise<void>((resolve) => {
    received = resolve
  })
  await page.route('**/api/v1/transfers', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    requests.push({
      key: route.request().headers()['idempotency-key'],
      body: route.request().postDataJSON(),
    })
    if (requests.length === 1) {
      const response = await route.fetch().catch(() => {
        throw new Error('Synthetic transfer forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(201)
      received()
      await gate
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost transfer response' }),
      })
    }
    if (requests.length === 2)
      return route.fulfill({
        status: 403,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic rejected retry' }),
      })
    return route.continue()
  })
  await fill(page, data.from, data.to)
  await page.getByRole('button', { name: 'Cadastrar transferência', exact: true }).click()
  await created
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  release()
  await page.getByRole('button', { name: 'Transferências', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Conferir e repetir transferência' })).toBeEnabled()
  await page.getByRole('button', { name: 'Conferir e repetir transferência' }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível validar')
  await expect(page.getByRole('button', { name: 'Revisar transferência' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Conferir e repetir transferência' }).click()
  await expect(
    page.getByText('Transferência cadastrada. Consulte o saldo das duas contas na data desejada.'),
  ).toBeVisible()
  expect(requests).toHaveLength(3)
  expect(requests[1]).toEqual(requests[0])
  expect(requests[2]).toEqual(requests[0])
  await expect(
    page.getByRole('list', { name: 'Transferências cadastradas' }).getByRole('listitem'),
  ).toHaveCount(1)
  await consult(page, data.from, 'R$ 500,00')
  await consult(page, data.to, 'R$ 1.500,00')
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(
    page.getByRole('heading', { name: 'Mais clareza para cuidar do seu amanhã.' }),
  ).toBeVisible()
})
