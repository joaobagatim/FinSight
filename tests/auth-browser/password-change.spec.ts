import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { privateApi } from '../support/session-client.js'

test('browser clears cookies after password change and accepts only the new password', async ({
  page,
  request,
  context,
}) => {
  request = privateApi(request)
  const credentials = {
    email: `browser-password-${randomUUID()}@example.com`,
    current: 'synthetic current password',
    replacement: 'synthetic browser replacement password',
  }
  const registration = await request.post('http://127.0.0.1:8002/api/v1/auth/register', {
    data: {
      name: 'Synthetic browser owner',
      email: credentials.email,
      password: credentials.current,
    },
  })
  expect(registration.status()).toBe(200)
  await page.goto('/')
  const outcome = await page.evaluate(async ({ email, current, replacement }) => {
    const base = 'http://127.0.0.1:8002/api/v1/'
    const bootstrap = async () => {
      const response = await fetch(base + 'auth/csrf', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Bootstrap': '1' },
        body: '{}',
      })
      return (await response.json()).csrf_token as string
    }
    const login = async (password: string) =>
      fetch(base + 'auth/login', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': await bootstrap() },
        body: JSON.stringify({ email, password }),
      })
    const initial = await login(current)
    const csrf = document.cookie
      .split(';')
      .map((value) => value.trim())
      .find((value) => value.startsWith('finsight_csrf='))
      ?.slice('finsight_csrf='.length)
    const changed = await fetch(base + 'users/me/change-password', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf ?? '' },
      body: JSON.stringify({ current_password: current, new_password: replacement }),
    })
    const visibleCleared = !document.cookie
      .split(';')
      .some((value) => value.trim().startsWith('finsight_'))
    const loggedOut = await fetch(base + 'auth/me', { credentials: 'include' })
    const old = await login(current)
    const renewed = await login(replacement)
    const profile = await fetch(base + 'auth/me', { credentials: 'include' })
    return {
      initial: initial.status,
      changed: changed.status,
      loggedOut: loggedOut.status,
      old: old.status,
      renewed: renewed.status,
      profile: profile.status,
      visibleCleared,
    }
  }, credentials)
  expect(outcome).toEqual({
    initial: 204,
    changed: 204,
    loggedOut: 401,
    old: 401,
    renewed: 204,
    profile: 200,
    visibleCleared: true,
  })
  const flags = (await context.cookies())
    .filter((cookie) => cookie.name.startsWith('finsight_'))
    .map(({ name, httpOnly }) => ({ name, httpOnly }))
  expect(
    flags.filter((cookie) => cookie.name !== 'finsight_csrf').every((cookie) => cookie.httpOnly),
  ).toBe(true)
})
