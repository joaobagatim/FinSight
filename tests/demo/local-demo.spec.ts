import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

test('isolated demo shows synthetic finances through normal login', async ({ page, context }) => {
  const local = Object.fromEntries(
    readFileSync(new URL('../../.demo/.env', import.meta.url), 'utf8')
      .trim()
      .split(/\r?\n/)
      .map((line) => line.split('=')),
  )
  await page.goto('/')
  await expect(page.getByRole('note')).toContainText('Ambiente de demonstração')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(local.DEMO_EMAIL)
  await page.getByLabel('Senha', { exact: true }).fill(local.DEMO_PASSWORD)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByText('Conta corrente fictícia', { exact: true })).toBeVisible()
  const cookies = await context.cookies()
  expect(cookies.filter((cookie) => cookie.name.startsWith('finsight_')).length).toBeGreaterThan(0)
  expect(cookies.every((cookie) => cookie.domain === '127.0.0.2')).toBe(true)
  await page.getByRole('button', { name: 'Lançamentos', exact: true }).click()
  await expect(page.getByText('Receita mensal de exemplo', { exact: true })).toBeVisible()
  await expect(page.getByText('Próximo aluguel de exemplo', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Saldos', exact: true }).click()
  await page
    .getByLabel('Conta para consultar saldo')
    .selectOption({ label: 'Conta corrente fictícia' })
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText('3.754,20')
  await page.setViewportSize({ width: 320, height: 740 })
  await expect(page.getByRole('note')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas metas', exact: true })).toBeVisible()
  await expect(page.getByText('Carregando metas…', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)

  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Importações de CSV', exact: true })).toBeVisible()
  await expect(page.getByText('Carregando histórico…', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)

  await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
  const seed = JSON.parse(
    readFileSync(new URL('../../.demo/seed.json', import.meta.url), 'utf8'),
  ) as { opening: string }
  await page.getByLabel('Data inicial', { exact: true }).fill(seed.opening)
  await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
  const indicators = page.getByRole('region', { name: 'Indicadores consultados', exact: true })
  await expect(indicators).toBeVisible()
  await expect(
    indicators
      .getByRole('figure', { name: 'Entradas e saídas por dia', exact: true })
      .locator('svg')
      .first(),
  ).toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Acessar FinSight' })).toBeVisible()
})
