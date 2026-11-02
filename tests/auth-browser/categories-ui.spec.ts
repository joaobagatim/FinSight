import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi } from '../support/session-client.js'

async function enter(page: Page, request: APIRequestContext) {
  const email = `categories-ui-${randomUUID()}@example.com`
  const password = 'synthetic category interface password'
  const response = await privateApi(request).post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: { name: 'Synthetic Category Owner', email, password },
  })
  expect(response.status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Categorias', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Atualizar categorias' })).toBeEnabled()
}

async function create(page: Page, name: string, type = 'expense') {
  await page.getByLabel('Nome da categoria', { exact: true }).fill(name)
  await page.getByLabel('Tipo de categoria', { exact: true }).selectOption(type)
  await page.getByRole('button', { name: 'Cadastrar categoria', exact: true }).click()
}

test('category lifecycle preserves classification and separates owners on a narrow screen', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await enter(page, request)
  const list = page.getByRole('list', { name: 'Categorias cadastradas' })
  await create(page, 'Alimentação')
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await create(page, 'alimentação')
  await expect(page.getByRole('alert')).toContainText('Já existe uma categoria')
  await create(page, 'Alimentação', 'income')
  await expect(list.getByRole('listitem')).toHaveCount(2)
  const expense = list.getByRole('listitem').filter({ hasText: 'Despesa' })
  await expense.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(page.getByLabel('Tipo de categoria', { exact: true })).toBeDisabled()
  await page.getByLabel('Nome da categoria', { exact: true }).fill('Mercado')
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(expense).toContainText('Mercado')
  await expense.getByRole('button', { name: 'Desativar', exact: true }).click()
  await expect(page.getByRole('form', { name: 'Desativar categoria' })).toContainText(
    'histórico serão preservados',
  )
  await page.getByRole('button', { name: 'Confirmar alteração' }).click()
  await expect(expense).toContainText('Desativada')
  await expense.getByRole('button', { name: 'Reativar', exact: true }).click()
  await page.getByRole('button', { name: 'Confirmar alteração' }).click()
  await expect(expense).not.toContainText('Desativada')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await page.getByRole('button', { name: 'Sair', exact: true }).click()
  await enter(page, request)
  await expect(list.getByRole('listitem')).toHaveCount(0)
})

test('stale category drafts and lost creation responses require reconciliation', async ({
  page,
  request,
  context,
}) => {
  await enter(page, request)
  await create(page, 'Original')
  const list = page.getByRole('list', { name: 'Categorias cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await list.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(page.getByLabel('Nome da categoria')).toHaveValue('Original')
  await page.getByLabel('Nome da categoria').fill('Rascunho antigo')
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await tab.getByRole('button', { name: 'Categorias', exact: true }).click()
  await tab.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(tab.getByLabel('Nome da categoria')).toHaveValue('Original')
  await tab.getByLabel('Nome da categoria').fill('Nome mais recente')
  await tab.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(tab.getByRole('list', { name: 'Categorias cadastradas' })).toContainText(
    'Nome mais recente',
  )
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(page.getByRole('alert')).toContainText('alterada em outro lugar')
  await expect(page.getByLabel('Nome da categoria')).toHaveValue('Rascunho antigo')
  await expect(page.getByRole('button', { name: 'Salvar alterações' })).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar dados' }).click()
  await expect(page.getByLabel('Nome da categoria')).toHaveValue('Nome mais recente')
  await page.getByRole('button', { name: 'Voltar para categorias' }).click()
  let posts = 0
  await page.route('**/api/v1/categories', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    posts += 1
    const response = await route.fetch().catch(() => {
      throw new Error('Synthetic category forwarding failed; sensitive details suppressed.')
    })
    expect(response.status()).toBe(201)
    return route.fulfill({
      response,
      status: 503,
      body: JSON.stringify({ detail: 'Synthetic lost creation response' }),
    })
  })
  await create(page, 'Resposta perdida')
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar')
  await expect(page.getByRole('button', { name: 'Cadastrar categoria' })).toBeDisabled()
  expect(posts).toBe(1)
  await page.getByRole('button', { name: 'Conferir categorias' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(2)
  await expect(list).toContainText('Resposta perdida')
  await expect(page.getByRole('button', { name: 'Cadastrar categoria' })).toBeEnabled()
  expect(posts).toBe(1)
  await tab.close()
})
