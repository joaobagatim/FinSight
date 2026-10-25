import { expect, test } from '@playwright/test'

test('process health returns the documented JSON contract', async ({ request }) => {
  const response = await request.get('/health')
  expect(response.status()).toBe(200)
  expect(response.headers()['content-type']).toContain('application/json')
  expect(await response.json()).toEqual({ status: 'ok' })
})

test('readiness reports an unconfigured database without affecting process health', async ({
  request,
}) => {
  const response = await request.get('/health/ready')
  expect(response.status()).toBe(503)
  expect(response.headers()['cache-control']).toBe('no-store')
  expect(await response.json()).toEqual({ status: 'unavailable', database: 'unavailable' })

  const health = await request.get('/health')
  expect(health.status()).toBe(200)
  expect(await health.json()).toEqual({ status: 'ok' })
})

test('OpenAPI documents success and unavailable readiness responses', async ({ request }) => {
  const response = await request.get('/openapi.json')
  expect(response.status()).toBe(200)
  const document = await response.json()
  expect(document.paths['/health'].get.responses).toHaveProperty('200')
  expect(document.paths['/health/ready'].get.responses).toHaveProperty('200')
  expect(document.paths['/health/ready'].get.responses).toHaveProperty('503')
})

test('an unknown endpoint returns a generic not-found response', async ({ request }) => {
  const response = await request.get('/nonexistent-test-endpoint')
  expect(response.status()).toBe(404)
  expect(await response.json()).toEqual({ detail: 'Not Found' })
})
