import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { randomBytes, randomUUID } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'

const exec = promisify(execFile)
const root = fileURLToPath(new URL('../../', import.meta.url))
const image =
  'postgres:18.6-bookworm@sha256:bbf83594798e144bff365a9c191c5d779f181fb3135902064ab8ff11918020fc'
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

async function docker(...args: string[]) {
  const result = await exec('docker', args, { windowsHide: true, timeout: 180_000 })
  return result.stdout.trim()
}

async function ensurePortFree() {
  await new Promise<void>((resolve, reject) => {
    const probe = net.createServer()
    probe.once('error', () =>
      reject(new Error('Port 8002 must be free; existing servers are never reused.')),
    )
    probe.listen(8002, '127.0.0.1', () => probe.close(() => resolve()))
  })
}

async function stopChild(child: ChildProcess | undefined) {
  if (!child || child.exitCode !== null || child.signalCode !== null || !child.pid) return
  if (process.platform === 'win32') {
    // Kill only this owned process tree, including the Windows venv redirector child.
    await exec('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
  } else {
    child.kill('SIGTERM')
  }
  for (let i = 0; i < 100 && child.exitCode === null && child.signalCode === null; i++)
    await pause(100)
  if (child.exitCode === null && child.signalCode === null) {
    child.kill('SIGKILL')
    throw new Error('Owned session API did not stop gracefully.')
  }
}

export default async function setup() {
  await ensurePortFree()
  if ((await docker('info', '--format', '{{.OSType}}')) !== 'linux')
    throw new Error('Linux Docker is required for isolated session tests.')
  const uuid = randomUUID().replaceAll('-', '')
  const name = `finsight-pw-session-${uuid}`
  const dbName = `finsight_test_pw_${uuid}`
  const cleanupPath = path.join(root, 'test-results/auth-cleanup.json')
  await mkdir(path.dirname(cleanupPath), { recursive: true })
  await writeFile(cleanupPath, JSON.stringify({ name, apiStopped: false, containerRemoved: false }))
  let created = false
  let child: ChildProcess | undefined
  const cleanup = async () => {
    let stopped = false
    let removed = !created
    try {
      await stopChild(child)
      stopped = true
    } finally {
      if (created) {
        await docker('stop', '--time', '5', name)
        for (let i = 0; i < 50; i++) {
          const remaining = await docker(
            'container',
            'ls',
            '--all',
            '--filter',
            `name=^/${name}$`,
            '--format',
            '{{.ID}}',
          )
          if (!remaining) {
            removed = true
            break
          }
          await pause(100)
        }
        await writeFile(
          cleanupPath,
          JSON.stringify({ name, apiStopped: stopped, containerRemoved: removed }),
        )
      }
    }
    if (!removed) throw new Error('Owned Playwright PostgreSQL container cleanup failed.')
  }
  try {
    await docker(
      'run',
      '--rm',
      '--detach',
      '--name',
      name,
      '--publish',
      '127.0.0.1::5432',
      '--env',
      `POSTGRES_DB=${dbName}`,
      '--env',
      'POSTGRES_USER=finsight_pw',
      '--env',
      'POSTGRES_PASSWORD=synthetic-pw-session-only',
      image,
    )
    created = true
    const port = Number((await docker('port', name, '5432/tcp')).split(':').at(-1))
    if (!Number.isInteger(port) || port === 5432 || port === 5433)
      throw new Error('Invalid isolated PostgreSQL port.')
    let ready = false
    for (let i = 0; i < 100; i++) {
      try {
        await docker(
          'exec',
          name,
          'pg_isready',
          '-h',
          '127.0.0.1',
          '-U',
          'finsight_pw',
          '-d',
          dbName,
        )
        ready = true
        break
      } catch {
        await pause(300)
      }
    }
    if (!ready) throw new Error('Isolated PostgreSQL readiness timeout.')
    const environment = Object.fromEntries(
      Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith('FINSIGHT_')),
    )
    const python = path.join(
      root,
      'backend/.venv',
      process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
    )
    child = spawn(python, [path.join(root, 'tests/support/session-api.py'), root], {
      cwd: root,
      windowsHide: true,
      stdio: 'ignore',
      env: {
        ...environment,
        SESSION_TEST_DB_NAME: dbName,
        SESSION_TEST_DB_PORT: String(port),
        SESSION_TEST_DB_PASSWORD: 'synthetic-pw-session-only',
        SESSION_TEST_JWT_KEY: randomBytes(32).toString('hex'),
        SESSION_TEST_CSRF_KEY: randomBytes(32).toString('hex'),
      },
    })
    let launchError = false
    child.once('error', () => {
      launchError = true
    })
    ready = false
    for (let i = 0; i < 150; i++) {
      if (launchError || child.exitCode !== null)
        throw new Error('Isolated session API exited before readiness.')
      try {
        const response = await fetch('http://127.0.0.1:8002/health/ready', {
          signal: AbortSignal.timeout(1000),
        })
        if (response.ok && response.headers.get('x-finsight-test-run') === uuid) {
          ready = true
          break
        }
      } catch {
        /* own API still starting */
      }
      await pause(300)
    }
    if (!ready) throw new Error('Isolated session API readiness timeout.')
    for (const user of ['alice', 'bob']) {
      const response = await fetch('http://127.0.0.1:8002/api/v1/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: user,
          email: `${user}@example.com`,
          password: 'synthetic session password',
        }),
      })
      if (response.status !== 200) throw new Error('Synthetic identity setup failed.')
    }
    return cleanup
  } catch (error) {
    await cleanup()
    // Suppress command arguments and child environment from reporter output.
    // eslint-disable-next-line preserve-caught-error -- credential-bearing command errors must not reach reports
    throw new Error(
      error instanceof Error && !('cmd' in error)
        ? error.message
        : 'Isolated session test setup failed.',
    )
  }
}
