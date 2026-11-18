import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { privateApi } from '../support/session-client.js'

test('reservation failure remains single across panels and clears after recovery', async ({
  page,
  request,
}) => {
  const email = `alert-navigation-${randomUUID()}@example.com`
  const password = 'synthetic alert navigation password'
  const registration = await privateApi(request).post(
    'http://127.0.0.1:8002/api/v1/auth/register',
    { data: { name: 'Synthetic Alert Owner', email, password } },
  )
  expect(registration.status()).toBe(200)
  let failing = true
  let alertRequests = 0
  const duplicateKeys: string[] = []
  page.on('console', (message) => {
    if (/same key|unique.*key/i.test(message.text())) duplicateKeys.push(message.type())
  })
  await page.route('**/api/v1/reservations/alerts', async (route) => {
    alertRequests++
    await route.fulfill({
      status: failing ? 503 : 200,
      contentType: 'application/json',
      body: JSON.stringify(
        failing
          ? { detail: 'Synthetic unavailable alert query' }
          : { account_count: 0, items: [], as_of: '2026-01-01' },
      ),
    })
  })
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  const notice = page.getByText(/Não foi possível conferir reservas\./)
  await expect(notice).toHaveCount(1)
  for (const name of ['Saldos', 'Categorias', 'Metas', 'Saldos']) {
    const before = alertRequests
    await page.getByRole('button', { name, exact: true }).click()
    await expect.poll(() => alertRequests).toBe(before + 1)
    await expect(notice).toHaveCount(1)
  }
  expect(duplicateKeys).toEqual([])
  failing = false
  await page.getByRole('button', { name: 'Conferir alertas de reservas', exact: true }).click()
  await expect(notice).toHaveCount(0)
  await expect(page.locator('.reservation-alerts')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Saldo consolidado', exact: true })).toBeVisible()
})

test('rapid panel navigation discards obsolete reads instead of blocking the selected panel', async ({
  page,
  request,
}) => {
  const email = `rapid-navigation-${randomUUID()}@example.com`
  const password = 'synthetic rapid navigation password'
  expect(
    (
      await privateApi(request).post('http://127.0.0.1:8002/api/v1/auth/register', {
        data: { name: 'Synthetic Navigation Owner', email, password },
      })
    ).status(),
  ).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
  await expect(page.getByText('Carregando contas…', { exact: true })).toHaveCount(0)
  let release = () => {}
  const gate = new Promise<void>((resolve) => {
    release = resolve
  })
  let meRequests = 0
  await page.route('**/api/v1/users/me', async (route) => {
    meRequests++
    if (meRequests === 1) await gate
    else await new Promise((resolve) => setTimeout(resolve, 200))
    await route.continue()
  })
  try {
    await page.getByRole('button', { name: 'Categorias', exact: true }).click()
    await expect.poll(() => meRequests).toBe(1)
    for (const name of ['Metas', 'Saldos', 'Contas', 'Categorias', 'Metas', 'Categorias']) {
      await page.getByRole('button', { name, exact: true }).click()
    }
    release()
    await expect(page.getByRole('heading', { name: 'Suas categorias', exact: true })).toBeVisible()
    await expect(page.getByText('Carregando categorias…', { exact: true })).toHaveCount(0)
    expect(meRequests).toBeLessThanOrEqual(3)
    await expect(page.locator('.reservation-alerts')).toHaveCount(0)
  } finally {
    release()
  }
})
