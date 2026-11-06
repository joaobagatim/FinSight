import { fileURLToPath, URL } from 'node:url'
import { mergeConfig } from 'vite'
import base from './vite.config.js'

// Never load the personal root .env. This config is used only by tools/demo.py.
export default mergeConfig(base, {
  envDir: fileURLToPath(new URL('../.demo', import.meta.url)),
  cacheDir: fileURLToPath(new URL('../.demo/vite-cache', import.meta.url)),
  server: { host: '127.0.0.2', port: 5180, strictPort: true },
})
