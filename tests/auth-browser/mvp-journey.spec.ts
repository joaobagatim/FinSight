import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'

test('MVP journey registers and imports through the UI, checks dashboard and balance, and funds a goal without spending money', async ({
  page,
}) => {
  test.setTimeout(60_000)
  await page.setViewportSize({ width: 320, height: 950 })
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const part = (type: string) => parts.find((item) => item.type === type)!.value
  const today = `${part('year')}-${part('month')}-${part('day')}`
  const before = (days: number) =>
    new Date(Date.parse(`${today}T00:00:00Z`) - days * 86400000).toISOString().slice(0, 10)
  const opening = before(3),
    incomeDay = before(2),
    expenseDay = before(1)
  const email = `journey-${randomUUID()}@example.com`
  const password = 'synthetic integrated journey password'

  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByRole('button', { name: 'Criar acesso', exact: true }).click()
  await page.getByLabel('Nome', { exact: true }).fill('Jornada MVP sintética')
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Criar acesso', exact: true }).first().click()
  await expect(page.getByRole('status')).toContainText('Solicitação recebida')
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Suas contas', exact: true })).toBeVisible()
  await page.addStyleTag({ content: 'html{font-size:18px}' })

  await page.getByLabel('Nome da conta', { exact: true }).fill('Conta sintética jornada')
  await page.getByLabel('Tipo de conta', { exact: true }).selectOption('checking')
  await page.getByLabel('Saldo inicial (R$)', { exact: true }).fill('1.000,00')
  await page.getByLabel('Data de abertura', { exact: true }).fill(opening)
  await page.getByRole('button', { name: 'Cadastrar conta', exact: true }).click()
  await expect(page.getByRole('list', { name: 'Contas cadastradas', exact: true })).toContainText(
    'Conta sintética jornada',
  )

  await page.getByRole('button', { name: 'Categorias', exact: true }).click()
  for (const [name, kind] of [
    ['Jornada receita', 'income'],
    ['Jornada despesa', 'expense'],
  ]) {
    await page.getByLabel('Nome da categoria', { exact: true }).fill(name)
    await page.getByLabel('Tipo de categoria', { exact: true }).selectOption(kind)
    await page.getByRole('button', { name: 'Cadastrar categoria', exact: true }).click()
    await expect(
      page.getByRole('list', { name: 'Categorias cadastradas', exact: true }),
    ).toContainText(name)
  }

  await page.getByRole('button', { name: 'Importações', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Conta de destino', exact: true })
    .selectOption({ label: 'Conta sintética jornada' })
  await page.getByLabel('Arquivo CSV', { exact: true }).setInputFiles({
    name: 'synthetic-mvp-journey.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(
      `Date;Description;Amount\n${incomeDay};Receita sintética;250.00\n${expenseDay};Despesa sintética;-50.00\n`,
    ),
  })
  await page.getByRole('button', { name: 'Analisar arquivo', exact: true }).click()
  const mapping = page.getByRole('form', { name: 'Mapear colunas do CSV', exact: true })
  for (const [label, value] of [
    ['Coluna de data', '0'],
    ['Coluna de descrição', '1'],
    ['Coluna de valor', '2'],
    ['Formato das datas', 'iso'],
    ['Formato dos valores', 'decimal-dot'],
  ])
    await mapping.getByRole('combobox', { name: label, exact: true }).selectOption(value)
  await mapping.getByRole('button', { name: 'Guardar prévia para revisão', exact: true }).click()
  const preview = page.getByRole('region', { name: 'Consulta da prévia', exact: true })
  for (const [row, category] of [
    [2, 'Jornada receita'],
    [3, 'Jornada despesa'],
  ] as const) {
    await preview.getByRole('button', { name: `Revisar registro ${row}`, exact: true }).click()
    await page
      .getByRole('combobox', { name: 'Categoria do registro', exact: true })
      .selectOption({ label: category })
    await page.getByRole('button', { name: 'Salvar correção do registro', exact: true }).click()
    const selected = preview.getByRole('checkbox', {
      name: `Selecionar registro ${row}`,
      exact: true,
    })
    await selected.click()
    await expect(selected).toBeChecked()
  }
  await preview
    .getByRole('button', { name: 'Conferir confirmação da seleção', exact: true })
    .click()
  const confirmation = page.getByRole('form', { name: 'Confirmar seleção CSV', exact: true })
  await expect(confirmation.getByRole('checkbox')).toHaveCount(3)
  for (const checkbox of await confirmation.getByRole('checkbox').all()) await checkbox.check()
  await confirmation.getByRole('button', { name: /Confirmar importação de/ }).click()
  await expect(
    page.getByRole('region', { name: 'Recibo da importação', exact: true }),
  ).toContainText('2 lançamento(s) criado(s)')

  async function dashboard(to: string) {
    await page.getByRole('button', { name: 'Dashboard', exact: true }).click()
    await page.getByLabel('Data inicial', { exact: true }).fill(incomeDay)
    await page.getByLabel('Data final', { exact: true }).fill(to)
    await page.getByRole('button', { name: 'Consultar indicadores', exact: true }).click()
    const result = page.getByRole('region', { name: 'Indicadores consultados', exact: true })
    await expect(result.locator('dd')).toHaveText(['R$ 250,00', 'R$ 50,00', 'R$ 200,00'])
    await expect(result).toContainText('2 lançamento(s)')
    return result
  }
  const indicators = await dashboard(expenseDay)
  await expect(
    indicators
      .getByRole('figure', { name: 'Entradas e saídas por dia', exact: true })
      .locator('svg')
      .first(),
  ).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  if (process.env.MVP_SCREENSHOT_PATH)
    await page.screenshot({ path: process.env.MVP_SCREENSHOT_PATH, fullPage: true })

  async function bank(asOf: string) {
    await page.getByRole('button', { name: 'Saldos', exact: true }).click()
    await page.getByLabel('Consolidado até a data', { exact: true }).fill(asOf)
    await page.getByRole('button', { name: 'Consultar consolidado', exact: true }).click()
    await expect(page.locator('.consolidated-result')).toContainText('R$ 1.200,00')
    await expect(page.locator('.consolidated-result')).toContainText(
      asOf.split('-').reverse().join('/'),
    )
  }
  await bank(expenseDay)
  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  const goal = page.getByRole('form', { name: 'Nova meta', exact: true })
  await goal.getByLabel('Nome da meta').fill('Meta sintética jornada')
  await goal.getByLabel('Valor alvo (R$)').fill('200,00')
  await goal.getByRole('button', { name: 'Cadastrar meta', exact: true }).click()
  const goals = page.getByRole('list', { name: 'Metas cadastradas', exact: true })
  await expect(goals).toContainText('Meta sintética jornada')
  await goals.getByRole('button', { name: 'Reservas e progresso', exact: true }).click()
  await page
    .getByRole('combobox', { name: 'Conta da reserva', exact: true })
    .selectOption({ label: 'Conta sintética jornada' })
  const allocation = page.getByRole('form', { name: 'Reservar ou retirar valor', exact: true })
  await expect(
    allocation.getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true }),
  ).toBeEnabled()
  await allocation.getByLabel('Valor da reserva ou retirada (R$)').fill('100,00')
  await allocation
    .getByRole('button', { name: 'Confirmar reserva ou retirada', exact: true })
    .click()
  const funding = page.locator('.funding-result')
  await expect(funding).toContainText('Progresso: 50,00%')
  await expect(funding).toContainText('Reservado na meta: R$ 100,00')
  await expect(allocation).toContainText('Saldo bancário: R$ 1.200,00')
  await expect(allocation).toContainText('Saldo livre: R$ 1.100,00')
  const position = await funding.getByText(/^Posição de /).textContent()
  const date = position!
    .match(/\d{2}\/\d{2}\/\d{4}/)![0]
    .split('/')
    .reverse()
    .join('-')
  await bank(date)
  await dashboard(date) // Includes the reservation day: reserving must not become an expense.
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Mais clareza para cuidar do seu amanhã.',
  )
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})
