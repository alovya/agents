#!/usr/bin/env node

import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const packageRootPath = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const viteEntryPath = resolve(packageRootPath, 'node_modules/vite/bin/vite.js')
const viteArguments = [
  viteEntryPath,
  '--host',
  '127.0.0.1',
  '--open',
  ...process.argv.slice(2),
]
const viteProcess = spawn(process.execPath, viteArguments, {
  cwd: packageRootPath,
  stdio: 'inherit',
})

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => viteProcess.kill(signal))
}

viteProcess.on('exit', (code, signal) => {
  if (signal !== null) {
    process.kill(process.pid, signal)
    return
  }

  process.exit(code ?? 1)
})
