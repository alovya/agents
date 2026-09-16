import { describe, expect, it } from 'vitest'
import type { GraphDocument } from '../graph/graph'
import { SAMPLE_GRAPH_DOCUMENT } from '../graph/sample-graph'
import {
  createInitialGraphView,
  fetchGraphFileSource,
} from './load-requested-graph'

describe('createInitialGraphView', () => {
  it('starts from the sample document when no inline source was requested', () => {
    const initialGraphView = createInitialGraphView(null)

    expect(initialGraphView.activeGraph.document).toBe(SAMPLE_GRAPH_DOCUMENT)
    expect(initialGraphView.graphJsonSource).toBe(
      JSON.stringify(SAMPLE_GRAPH_DOCUMENT, null, 2),
    )
    expect(initialGraphView.importError).toBeNull()
  })

  it('activates a valid inline document and keeps its source verbatim', () => {
    const initialGraphView = createInitialGraphView(validInlineGraphSource)

    expect(initialGraphView.activeGraph.document).toEqual(validInlineDocument)
    expect(initialGraphView.graphJsonSource).toBe(validInlineGraphSource)
    expect(initialGraphView.importError).toBeNull()
  })

  it('keeps the sample document and reports the validation error for an invalid inline source', () => {
    const invalidInlineGraphSource = '{"rootId":"root"}'
    const initialGraphView = createInitialGraphView(invalidInlineGraphSource)

    expect(initialGraphView.activeGraph.document).toBe(SAMPLE_GRAPH_DOCUMENT)
    expect(initialGraphView.graphJsonSource).toBe(invalidInlineGraphSource)
    expect(initialGraphView.importError).toBe(
      'Invalid graph document: nodes is required',
    )
  })
})

describe('fetchGraphFileSource', () => {
  it('returns the served graph JSON', async () => {
    const originalFetch = globalThis.fetch
    const fetch_mock = async () => ({
      ok: true,
      status: 200,
      text: async () => validInlineGraphSource,
    })
    globalThis.fetch = fetch_mock as unknown as typeof globalThis.fetch

    try {
      await expect(fetchGraphFileSource('/__bgexp/graph.json')).resolves.toBe(
        validInlineGraphSource,
      )
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  it('reports the status when the graph file cannot be served', async () => {
    const originalFetch = globalThis.fetch
    const fetch_mock = async () => ({
      ok: false,
      status: 404,
      text: async () => '',
    })
    globalThis.fetch = fetch_mock as unknown as typeof globalThis.fetch

    try {
      await expect(
        fetchGraphFileSource('/__bgexp/graph.json'),
      ).rejects.toThrow('Could not load graph JSON file (404).')
    } finally {
      globalThis.fetch = originalFetch
    }
  })
})

const validInlineDocument: GraphDocument = {
  rootId: 'root',
  nodes: [
    { id: 'root', label: 'Root', kind: 'composite', parentId: null },
    { id: 'left', label: 'Left', kind: 'leaf', parentId: 'root' },
    { id: 'right', label: 'Right', kind: 'leaf', parentId: 'root' },
  ],
  edges: [],
}
const validInlineGraphSource = `${JSON.stringify(validInlineDocument)}\n`
