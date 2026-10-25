import js from '@eslint/js'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  {
    ignores: ['frontend/**', 'backend/**', '.cache/**', 'playwright-report/**', 'test-results/**'],
  },
  {
    files: ['eslint.config.js'],
    extends: [js.configs.recommended],
  },
  {
    files: ['playwright.config.ts', 'tests/**/*.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
  },
)
