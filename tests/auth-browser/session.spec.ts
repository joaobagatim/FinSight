import { expect, test } from '@playwright/test'

test('browser enforces cookie visibility and sends CORS/CSRF credentials', async ({
  page,
  context,
}) => {
  await page.goto('/')
  const outcome = await page.evaluate(async () => {
    const api = 'http://127.0.0.1:8002/api/v1/auth/'
    const bootstrap = await fetch(api + 'csrf', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Bootstrap': '1' },
      body: '{}',
    })
    const { csrf_token: csrf } = await bootstrap.json()
    const login = await fetch(api + 'login', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ email: 'alice@example.com', password: 'synthetic session password' }),
    })
    const profile = await fetch(api + 'me', { credentials: 'include' })
    const visibleNames = document.cookie.split(';').map((item) => item.trim().split('=')[0])
    const exposed = visibleNames.some((name) =>
      ['finsight_access', 'finsight_refresh', 'finsight_preauth'].includes(name),
    )
    const currentCsrf = document.cookie
      .split(';')
      .map((item) => item.trim())
      .find((item) => item.startsWith('finsight_csrf='))
      ?.slice('finsight_csrf='.length)
    if (!currentCsrf) throw new Error('Browser session CSRF is unavailable.')
    const invalid = await fetch(api + 'logout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': 'invalid-synthetic' },
      body: '{}',
    })
    return {
      login: login.status,
      profile: profile.status,
      email: (await profile.json()).email,
      exposed,
      invalid: invalid.status,
      storageEmpty: localStorage.length === 0 && sessionStorage.length === 0,
    }
  })
  expect(outcome).toEqual({
    login: 204,
    profile: 200,
    email: 'alice@example.com',
    exposed: false,
    invalid: 403,
    storageEmpty: true,
  })
  const cookieFlags = (await context.cookies())
    .filter((cookie) => cookie.name.startsWith('finsight_'))
    .map(({ name, httpOnly, secure, sameSite, path }) => ({
      name,
      httpOnly,
      secure,
      sameSite,
      path,
    }))
  expect(cookieFlags.map((cookie) => cookie.name).sort()).toEqual([
    'finsight_access',
    'finsight_csrf',
    'finsight_refresh',
  ])
  expect(
    cookieFlags
      .filter((cookie) => cookie.name !== 'finsight_csrf')
      .every((cookie) => cookie.httpOnly),
  ).toBe(true)
  expect(cookieFlags.every((cookie) => cookie.sameSite === 'Lax' && cookie.path === '/')).toBe(true)
  const logout = await page.evaluate(async () => {
    const csrf = document.cookie
      .split(';')
      .map((item) => item.trim())
      .find((item) => item.startsWith('finsight_csrf='))
      ?.slice('finsight_csrf='.length)
    const response = await fetch('http://127.0.0.1:8002/api/v1/auth/logout', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf ?? '' },
      body: '{}',
    })
    return response.status
  })
  expect(logout).toBe(204)
  const status = await page.evaluate(
    async () =>
      (await fetch('http://127.0.0.1:8002/api/v1/auth/me', { credentials: 'include' })).status,
  )
  expect(status).toBe(401)
})
