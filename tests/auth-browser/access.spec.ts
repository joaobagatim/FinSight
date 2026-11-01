import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'

test('visitor registers, signs in and signs out through accessible forms', async ({ page }) => {
  const email = `access-ui-${randomUUID()}@example.com`
  const password = 'synthetic interface password'
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByRole('button', { name: 'Criar acesso', exact: true }).click()
  await page.getByLabel('Nome', { exact: true }).fill('Synthetic Interface')
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Criar acesso', exact: true }).first().click()
  await expect(page.getByRole('status')).toContainText('Solicitação recebida')
  await expect(page.getByLabel('Senha', { exact: true })).toHaveValue('')
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Olá, Synthetic Interface.' })).toBeVisible()
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Mais clareza para cuidar do seu amanhã.',
  )
  await expect(page.getByLabel('Senha', { exact: true })).toHaveCount(0)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})
