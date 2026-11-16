import { randomUUID } from 'node:crypto'
import { expect, test, type Page, type APIRequestContext } from '@playwright/test'
import { privateApi, sessionCsrf, sessionOrigin } from '../support/session-client.js'

async function enter(page: Page, request: APIRequestContext) {
  const email = `goals-${randomUUID()}@example.com`
  const password = 'synthetic goals password'
  const response = await privateApi(request).post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: { name: 'Synthetic Goal Owner', email, password },
  })
  expect(response.status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Acessar FinSight', exact: true }).click()
  await page.getByLabel('E-mail', { exact: true }).fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar', exact: true }).click()
  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await expect(page.getByText('Nenhuma meta cadastrada.', { exact: true })).toBeVisible()
}

test('create edit and explicitly complete a goal at 320px without financial movements', async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 320, height: 950 })
  await enter(page, request)
  await page.addStyleTag({ content: 'html{font-size:18px}' })
  const form = page.getByRole('form', { name: 'Nova meta', exact: true })
  await form.getByLabel('Nome da meta').fill('Intercâmbio sintético')
  await form.getByLabel('Valor alvo (R$)').fill('0,00')
  await form.getByRole('button', { name: 'Cadastrar meta', exact: true }).click()
  await expect(form.getByRole('alert')).toContainText('maior que zero')
  await form.getByLabel('Valor alvo (R$)').fill('12.345,67')
  await form.getByLabel('Prazo da meta (opcional)').fill('2027-12-31')
  let posts = 0
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname === '/api/v1/goals') posts++
  })
  await form
    .getByRole('button', { name: 'Cadastrar meta', exact: true })
    .evaluate((button: HTMLButtonElement) => {
      button.click()
      button.click()
    })
  const list = page.getByRole('list', { name: 'Metas cadastradas' })
  await expect(list.getByRole('listitem')).toHaveCount(1)
  await expect(list).toContainText('R$ 12.345,67')
  expect(posts).toBe(1)
  await list.getByRole('button', { name: 'Editar meta', exact: true }).click()
  const edit = page.getByRole('form', { name: 'Editar meta', exact: true })
  await expect(edit.getByLabel('Nome da meta')).toHaveValue('Intercâmbio sintético')
  await edit.getByLabel('Valor alvo (R$)').fill('20.000,10')
  await edit.getByLabel('Prazo da meta (opcional)').fill('')
  await edit.getByLabel('Situação do objetivo').selectOption('completed')
  await expect(edit).toContainText('Não comprova que o valor foi acumulado')
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false)
  await edit.getByRole('button', { name: 'Confirmar alterações da meta', exact: true }).click()
  await expect(list).toContainText('Concluída')
  await expect(list).toContainText('R$ 20.000,10')
  await expect(list).toContainText('Sem prazo definido')
  const api = privateApi(page.request)
  for (const path of ['transactions', 'transfers'])
    expect((await (await api.get('http://127.0.0.1:8002/api/v1/' + path)).json()).items).toEqual([])
})

test('lost creation response reuses its key across navigation and stale edits require a fresh read', async ({
  page,
  request,
}) => {
  await enter(page, request)
  const keys: string[] = []
  await page.route('**/api/v1/goals', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    keys.push(route.request().headers()['idempotency-key'])
    const response = await route.fetch()
    expect(response.status()).toBe(201)
    if (keys.length === 1)
      return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Synthetic lost goal response' }),
      })
    return route.fulfill({ response })
  })
  const form = page.getByRole('form', { name: 'Nova meta', exact: true })
  await form.getByLabel('Nome da meta').fill('Meta em conferência')
  await form.getByLabel('Valor alvo (R$)').fill('1.000,00')
  await form.getByRole('button', { name: 'Cadastrar meta', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Não foi possível confirmar o cadastro')
  await page.getByRole('button', { name: 'Contas', exact: true }).click()
  await page.getByRole('button', { name: 'Metas', exact: true }).click()
  await page
    .getByRole('button', { name: 'Conferir e repetir cadastro da meta', exact: true })
    .click()
  const list = page.getByRole('list', { name: 'Metas cadastradas' })
  await expect(
    page.getByText('Meta cadastrada. Nenhum dinheiro foi reservado ou movimentado.', {
      exact: true,
    }),
  ).toBeVisible()
  await expect(list.getByRole('listitem')).toHaveCount(1)
  expect(keys).toHaveLength(2)
  expect(keys[0]).toBe(keys[1])
  await list.getByRole('button', { name: 'Editar meta', exact: true }).click()
  const edit = page.getByRole('form', { name: 'Editar meta', exact: true })
  await expect(edit.getByLabel('Nome da meta')).toHaveValue('Meta em conferência')
  const api = privateApi(page.request),
    base = 'http://127.0.0.1:8002/api/v1/goals'
  const item = (await (await api.get(base)).json()).items[0]
  const snapshot = await api.get(base + '/' + item.id)
  const changed = await api.patch(base + '/' + item.id, {
    headers: {
      Origin: sessionOrigin,
      'X-CSRF-Token': await sessionCsrf(api),
      'If-Match': snapshot.headers().etag,
    },
    data: { name: 'Outra operação' },
  })
  expect(changed.status()).toBe(200)
  await edit.getByLabel('Nome da meta').fill('Rascunho antigo')
  await edit.getByRole('button', { name: 'Confirmar alterações da meta', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('mudou em outra operação')
  await expect(
    edit.getByRole('button', { name: 'Confirmar alterações da meta', exact: true }),
  ).toBeDisabled()
  await page.getByRole('button', { name: 'Recarregar situação da meta', exact: true }).click()
  await expect(edit.getByLabel('Nome da meta')).toHaveValue('Outra operação')
})
