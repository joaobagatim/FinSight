import { expect, test } from '@playwright/test'

test('home renders the project and clearly identifies planned features', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text())
  })

  const response = await page.goto('/')
  expect(response?.status()).toBe(200)
  await expect(page).toHaveTitle(/FinSight/)
  await expect(page.locator('html')).toHaveAttribute('lang', 'pt-BR')
  await expect(page.getByRole('main')).toHaveCount(1)
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(
    'Mais clareza para cuidar do seu amanhã.',
  )
  await expect(page.getByText(/Em desenvolvimento/)).toBeVisible()
  await expect(page.getByText(/ainda não estão disponíveis/)).toBeVisible()
  await expect(page.getByRole('listitem')).toHaveCount(3)
  expect(errors).toEqual([])
})

test('keyboard skip link and navigation anchors reach their destinations', async ({ page }) => {
  await page.goto('/')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Pular para o conteúdo' })).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('main')).toBeFocused()
  await expect(page).toHaveURL(/#conteudo$/)

  const about = page.getByRole('link', { name: /Sobre o projeto/ })
  await about.focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#sobre$/)
  await expect(
    page.getByRole('heading', { name: 'Um olhar completo, passo a passo.' }),
  ).toBeVisible()

  await page.getByRole('link', { name: 'FinSight — início' }).click()
  await expect(page).toHaveURL(/#conteudo$/)
})

test('home remains usable on narrow and desktop viewports', async ({ page }) => {
  await page.goto('/')
  for (const width of [320, 390, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await expect(page.getByRole('link', { name: /Sobre o projeto/ })).toBeVisible()
    await expect(page.getByText(/Em desenvolvimento/)).toBeVisible()
    const hasOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    )
    expect(hasOverflow, `Horizontal overflow at ${width}px`).toBe(false)
  }
})
