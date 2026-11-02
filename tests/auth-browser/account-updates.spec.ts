import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi } from '../support/session-client.js'

async function prepare(page: Page, request: APIRequestContext) {
  const email = `updates-${randomUUID()}@example.com`
  const password = 'synthetic account updates password'
  const response = await privateApi(request).post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: { name: 'Synthetic Updates Owner', email, password },
  })
  expect(response.status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight' }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByLabel('Nome da conta', { exact: true }).fill('Conta original')
  await page.getByLabel('Saldo inicial (R$)', { exact: true }).fill('-1.234,56')
  await page.getByLabel('Data de abertura', { exact: true }).fill('2026-01-01')
  await page.getByRole('button', { name: 'Cadastrar conta', exact: true }).click()
  await expect(
    page.getByRole('list', { name: 'Contas cadastradas' }).getByRole('listitem'),
  ).toHaveCount(1)
}

test('edit archive and reactivate preserve opening position on a narrow screen', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await prepare(page, request)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  const editor = page.getByRole('form', { name: 'Editar conta', exact: true })
  await expect(editor.getByLabel('Nome da conta')).toHaveValue('Conta original')
  await editor.getByLabel('Nome da conta').fill('Conta atualizada')
  await editor.getByLabel('Tipo de conta', { exact: true }).selectOption('savings')
  await expect(page.getByLabel('Saldo inicial (R$)', { exact: true })).toHaveCount(0)
  await expect(editor).toContainText('−R$ 1.234,56')
  await expect(editor).toContainText('01/01/2026')
  await editor.getByRole('button', { name: 'Salvar alterações' }).click()
  const list = page.getByRole('list', { name: 'Contas cadastradas' })
  await expect(list).toContainText('Conta atualizada')
  await expect(list).toContainText('Poupança')
  await list.getByRole('button', { name: 'Arquivar', exact: true }).click()
  await expect(page.getByRole('form', { name: 'Arquivar conta' })).toContainText(
    'histórico financeiro será preservado',
  )
  await page.getByRole('button', { name: 'Confirmar alteração' }).click()
  await expect(list).toContainText('Arquivada')
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await list.getByRole('button', { name: 'Reativar', exact: true }).click()
  await page.getByRole('button', { name: 'Confirmar alteração' }).click()
  await expect(list).not.toContainText('Arquivada')
  await expect(list).toContainText('−R$ 1.234,56')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
})

test('stale edits and a lost update response require reviewing current data', async ({
  page,
  request,
  context,
}) => {
  await prepare(page, request)
  await page.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(page.getByLabel('Nome da conta', { exact: true })).toHaveValue('Conta original')
  await page.getByLabel('Nome da conta', { exact: true }).fill('Rascunho antigo')
  const tab = await context.newPage()
  await tab.goto('/')
  await tab.getByRole('button', { name: 'Acessar FinSight' }).click()
  await tab.getByRole('button', { name: 'Editar', exact: true }).click()
  await expect(tab.getByLabel('Nome da conta', { exact: true })).toHaveValue('Conta original')
  await tab.getByLabel('Nome da conta', { exact: true }).fill('Edição mais recente')
  await tab.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(tab.getByRole('list', { name: 'Contas cadastradas' })).toContainText(
    'Edição mais recente',
  )
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(page.getByRole('alert')).toContainText('alterada em outro lugar')
  await expect(page.getByLabel('Nome da conta', { exact: true })).toHaveValue('Rascunho antigo')
  await expect(page.getByRole('button', { name: 'Salvar alterações' })).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar dados' }).click()
  await expect(page.getByLabel('Nome da conta', { exact: true })).toHaveValue('Edição mais recente')
  let patches = 0
  await page.route('**/api/v1/accounts/*', async (route) => {
    if (route.request().method() !== 'PATCH') return route.continue()
    patches += 1
    const response = await route.fetch().catch(() => {
      throw new Error('Synthetic update forwarding failed; sensitive details suppressed.')
    })
    expect(response.status()).toBe(200)
    return route.fulfill({
      response,
      status: 503,
      body: JSON.stringify({ detail: 'Synthetic lost update response' }),
    })
  })
  await page.getByLabel('Nome da conta', { exact: true }).fill('Edição confirmada no servidor')
  await page.getByRole('button', { name: 'Salvar alterações' }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar')
  await expect(page.getByRole('button', { name: 'Salvar alterações' })).toBeDisabled()
  expect(patches).toBe(1)
  await page.getByRole('button', { name: 'Recarregar dados' }).click()
  await expect(page.getByLabel('Nome da conta', { exact: true })).toHaveValue(
    'Edição confirmada no servidor',
  )
  await page.getByRole('button', { name: 'Voltar para contas' }).click()
  await expect(page.getByRole('list', { name: 'Contas cadastradas' })).toContainText(
    'Edição confirmada no servidor',
  )
  await tab.close()
})
