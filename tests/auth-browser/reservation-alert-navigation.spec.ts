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
