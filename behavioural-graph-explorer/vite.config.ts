import { readFile } from 'node:fs/promises'
import react from '@vitejs/plugin-react'
import type { Plugin } from 'vite'
import { defineConfig } from 'vite'

const graphRoutePath = '/__bgexp/graph.json'

function serveGraphFile(): Plugin {
  return {
    name: 'serve-bgexp-graph-file',
    configureServer(server) {
      server.middlewares.use(graphRoutePath, async (_request, response, next) => {
        const graphFilePath = process.env.BGEXP_GRAPH_FILE_PATH

        if (graphFilePath === undefined || graphFilePath === '') {
          next()
          return
        }

        try {
          const graphSource = await readFile(graphFilePath, 'utf8')
          response.statusCode = 200
          response.setHeader('Content-Type', 'application/json; charset=utf-8')
          response.end(graphSource)
        } catch (error) {
          next(error)
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [serveGraphFile(), react()],
})
