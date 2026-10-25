import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
const python = path.join(
  root,
  'backend',
  '.venv',
  process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python',
)

if (!existsSync(python)) {
  console.error(
    'Create backend/.venv and install backend/requirements-dev.txt before running tests.',
  )
  process.exit(1)
}

// Isolate the child process from local application settings; never mutate the parent environment.
const environment = Object.fromEntries(
  Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith('FINSIGHT_')),
)
const code = `
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "backend"))
from app.core.config import Settings
from app.main import create_app
import uvicorn

settings = Settings(_env_file=None, environment="test")
uvicorn.run(create_app(settings), host="127.0.0.1", port=8001, log_level="warning")
`
const child = spawn(python, ['-c', code, root], {
  cwd: root,
  env: environment,
  stdio: 'inherit',
  windowsHide: true,
})

let stopping = false
for (const signal of ['SIGINT', 'SIGTERM'] as const) {
  process.on(signal, () => {
    if (!stopping) {
      stopping = true
      child.kill(signal)
    }
  })
}
child.once('error', () => {
  console.error('Unable to start the isolated test API. Check the backend virtual environment.')
  process.exitCode = 1
})
child.once('exit', (code) => {
  process.exitCode = code ?? (stopping ? 0 : 1)
})
