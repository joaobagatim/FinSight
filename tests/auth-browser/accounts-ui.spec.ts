import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi } from '../support/session-client.js'

const password = 'synthetic accounts interface password'

async function seed(api: APIRequestContext) {
  api = privateApi(api)
  const email = `accounts-ui-${randomUUID()}@example.com`
  const result = await api.post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: { name: 'Synthetic Account Owner', email, password },
  })
  expect(result.status()).toBe(200)
  return email
}

async function login(page: Page, email: string, checkFailure = false) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  if (checkFailure) {
    await page.getByLabel('Senha', { exact: true }).fill('synthetic wrong password')
    await page.getByRole('button', { name: 'Entrar', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Não foi possível entrar')
    await expect(page.getByLabel('Senha', { exact: true })).toHaveValue('')
  }
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Atualizar lista' })).toBeEnabled()
}

test('account screens preserve decimal values and clear another owners data after logout', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await login(page, await seed(request), true)
  await expect(page.getByText('Sua primeira conta começa aqui.')).toBeVisible()
  await page.getByLabel('Nome da conta', { exact: true }).fill('Conta sintética')
  await page.getByLabel('Nome da conta', { exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Tipo de conta', { exact: true })).toBeFocused()
  await page.getByLabel('Saldo inicial (R$)', { exact: true }).fill('-1.234,56')
  await page.getByLabel('Data de abertura', { exact: true }).fill('2026-01-01')
  await page.getByRole('button', { name: 'Cadastrar conta', exact: true }).click()
  const list = page.getByRole('list', { name: 'Contas cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('−R$ 1.234,56')
  await expect(list).toContainText('01/01/2026')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Acessar FinSight' })).toBeVisible()
  await login(page, await seed(request))
  await expect(page.getByText('Sua primeira conta começa aqui.')).toBeVisible()
  await expect(page.getByText('Conta sintética', { exact: true })).toHaveCount(0)
})

test('lost creation response reuses its key and two tabs renew one shared session', async ({
  page,
  context,
  request,
}) => {
  await login(page, await seed(request))
  const keys: string[] = []
  await page.route('**/api/v1/accounts', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push((await route.request().headerValue('Idempotency-Key')) ?? '')
    if (keys.length === 1) {
      const response = await route.fetch().catch(() => {
        throw new Error('Isolated account forwarding failed; sensitive details suppressed.')
      })
      expect(response.status()).toBe(201)
      return route.fulfill({
        response,
        status: 503,
        body: JSON.stringify({ detail: 'Synthetic lost response' }),
      })
    }
    return route.continue()
  })
  await page.getByLabel('Nome da conta', { exact: true }).fill('Conta de repetição')
  await page.getByLabel('Saldo inicial (R$)', { exact: true }).fill('0,10')
  await page.getByLabel('Data de abertura', { exact: true }).fill('2026-01-01')
  await page.getByRole('button', { name: 'Cadastrar conta', exact: true }).evaluate((button) => {
    ;(button as HTMLButtonElement).click()
    ;(button as HTMLButtonElement).click()
  })
  await expect(page.getByRole('button', { name: 'Tentar novamente', exact: true })).toBeVisible()
  await expect(page.getByLabel('Nome da conta', { exact: true })).toBeDisabled()
  expect(keys.length).toBe(1)
  await page.getByRole('button', { name: 'Tentar novamente', exact: true }).click()
  const list = page.getByRole('list', { name: 'Contas cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  expect(keys.length).toBe(2)
  expect(keys[0]).not.toBe('')
  expect(keys[1]).toBe(keys[0])
  await page.unroute('**/api/v1/accounts')
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await expect(
    tab.getByRole('list', { name: 'Contas cadastradas' }).getByRole('listitem'),
  ).toHaveCount(1)
  await expect(tab.getByRole('button', { name: 'Atualizar lista' })).toBeEnabled()
  let refreshes = 0
  for (const current of [page, tab])
    current.on('request', (event) => {
      if (event.method() === 'POST' && event.url().endsWith('/api/v1/auth/refresh')) refreshes += 1
    })
  await context.clearCookies({ name: 'finsight_access' })
  await Promise.all([
    page.getByRole('button', { name: 'Atualizar lista' }).click(),
    tab.getByRole('button', { name: 'Atualizar lista' }).click(),
  ])
  await expect(page.getByRole('button', { name: 'Atualizar lista' })).toBeEnabled()
  await expect(tab.getByRole('button', { name: 'Atualizar lista' })).toBeEnabled()
  expect(refreshes).toBe(1)
  const profile = await privateApi(page.request).get('http://127.0.0.1:8002/api/v1/users/me')
  expect(profile.status()).toBe(200)
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(tab.getByRole('button', { name: 'Acessar FinSight' })).toBeVisible()
  await expect(tab.getByRole('list', { name: 'Contas cadastradas' })).toHaveCount(0)
  await tab.close()
})
