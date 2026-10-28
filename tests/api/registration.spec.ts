import { expect, test } from '@playwright/test'

test('registration rejects invalid credentials without echoing input', async ({ request }) => {
  const marker = 'synthetic-private-input-marker'
  const response = await request.post('/api/v1/auth/register', {
    data: { name: 'Synthetic', email: marker, password: marker, [marker]: marker },
  })
  expect(response.status()).toBe(422)
  expect(response.headers()['cache-control']).toBe('no-store')
  expect(await response.text()).not.toContain(marker)
  expect(response.headers()['set-cookie']).toBeUndefined()
})

test('registration safely reports an unconfigured database', async ({ request }) => {
  const response = await request.post('/api/v1/auth/register', {
    data: {
      name: 'Synthetic User',
      email: 'synthetic@example.com',
      password: 'synthetic test password',
    },
  })
  expect(response.status()).toBe(503)
  expect(await response.json()).toEqual({ detail: 'Registration temporarily unavailable' })
  expect(response.headers()['cache-control']).toBe('no-store')
  expect(response.headers()['set-cookie']).toBeUndefined()
})

test('registration publishes a write-only password schema', async ({ request }) => {
  const response = await request.get('/openapi.json')
  const document = await response.json()
  expect(document.paths['/api/v1/auth/register'].post.responses).toHaveProperty('200')
  expect(document.components.schemas.RegistrationInput.properties.password.writeOnly).toBe(true)
  expect(document.components.schemas.RegistrationInput.additionalProperties).toBe(false)
})
