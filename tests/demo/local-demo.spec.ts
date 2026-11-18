import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'

test('isolated demo shows synthetic finances through normal login', async ({ page, context }) => {
  test.setTimeout(120_000)
  let limitedUntil = 0
  page.on('response', (response) => {
    if (!response.url().startsWith('http://127.0.0.2:8010/api/v1/') || response.status() !== 429)
      return
    const seconds = Number(response.headers()['retry-after'])
    if (Number.isInteger(seconds) && seconds >= 1 && seconds <= 60)
      limitedUntil = Math.max(limitedUntil, Date.now() + seconds * 1000)
  })
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
  await page
    .getByLabel('Conta para consultar saldo')
    .selectOption({ label: 'Conta corrente fictícia' })
  await page.getByRole('button', { name: 'Consultar saldo', exact: true }).click()
  await expect(page.locator('.balance-result')).toContainText('3.754,20')
  await page.getByRole('button', { name: 'Saldos', exact: true }).click()
  await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
  await expect(page.locator('.consolidated-result')).toContainText('6.604,20')
  await page.setViewportSize({ width: 320, height: 740 })
  await expect(page.getByRole('note')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)

  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas metas', exact: true })).toBeVisible()
  await expect(page.getByText('Carregando metas…', { exact: true })).not.toBeVisible()
  await expect(page.getByRole('alert')).toHaveCount(0)

  const goals = page.getByRole('list', { name: 'Metas cadastradas', exact: true })
  await expect(goals).toContainText('Reserva de emergência fictícia')
  await goals.getByRole('button', { name: 'Reservas e progresso', exact: true }).click()
  const fundingPanel = page.getByRole('region', { name: 'Reservas e progresso', exact: true })
  await expect(fundingPanel).toHaveAttribute('aria-busy', 'false')
  if ((await fundingPanel.getByRole('alert').count()) > 0 && limitedUntil > 0) {
    // The live demo keeps its normal rate limit. Retry only this read through its UI.
    const wait = Math.max(0, limitedUntil - Date.now()) + 100
    console.log(JSON.stringify({ event: 'demo_retry_after', wait_ms: wait }))
    await new Promise((resolve) => setTimeout(resolve, wait))
    await fundingPanel.getByRole('button', { name: 'Recarregar reservas', exact: true }).click()
  }
  await expect(page.locator('.funding-result')).toContainText('Progresso: 50,00%')
  await expect(page.locator('.funding-result')).toContainText('Reservado na meta: R$ 500,00')
  await page
    .getByRole('combobox', { name: 'Conta da reserva', exact: true })
    .selectOption({ label: 'Reserva fictícia' })
  const allocation = page.getByRole('form', { name: 'Reservar ou retirar valor', exact: true })
  await expect(allocation).toContainText('Saldo bancário: R$ 2.850,00')
  await expect(allocation).toContainText('Saldo livre: R$ 2.350,00')

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
