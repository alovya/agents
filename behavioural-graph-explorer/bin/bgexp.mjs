#!/usr/bin/env node

import { readFile } from 'node:fs/promises'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const packageRootPath = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const viteEntryPath = resolve(packageRootPath, 'node_modules/vite/bin/vite.js')
const commandArguments = process.argv.slice(2)
const graphPathArgument = commandArguments[0]?.startsWith('-')
  ? undefined
  : commandArguments.shift()
const graphFilePath = graphPathArgument === undefined
  ? undefined
  : resolve(process.cwd(), graphPathArgument)

if (graphFilePath !== undefined) {
  await readFile(graphFilePath, 'utf8')
}

const graphUrlPath = graphFilePath === undefined
  ? undefined
  : '/?graphFile=/__bgexp/graph.json'
const viteArguments = [
  viteEntryPath,
  '--host',
  '127.0.0.1',
  '--open',
  ...(graphUrlPath === undefined ? [] : [graphUrlPath]),
  ...commandArguments,
]
const viteProcess = spawn(process.execPath, viteArguments, {
  cwd: packageRootPath,
  env: {
    ...process.env,
    BGEXP_GRAPH_FILE_PATH: graphFilePath ?? '',
  },
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
