import { describe, expect, it } from 'vitest'
import { projectVisibleGraph } from './graph'
import { DagreLayoutEngine } from './dagre-layout'
import type { VisibleGraph } from './graph'
import { SAMPLE_GRAPH_DOCUMENT } from './sample-graph'

const initialGraph = projectVisibleGraph(
  SAMPLE_GRAPH_DOCUMENT,
  SAMPLE_GRAPH_DOCUMENT.rootId,
  new Set(),
)

describe('DagreLayoutEngine', () => {
  it('returns one finite top-left position per visible node', async () => {
    const layout = await new DagreLayoutEngine().layout(initialGraph)

    expect(Object.keys(layout.nodePositions)).toEqual(
      initialGraph.nodes.map((node) => node.id),
    )
    for (const node of initialGraph.nodes) {
      const position = layout.nodePositions[node.id]

      expect(position).toBeDefined()
      expect(Number.isFinite(position?.x)).toBe(true)
      expect(Number.isFinite(position?.y)).toBe(true)
    }
  })

  it('translates Dagre centre coordinates into top-left positions', async () => {
    const isolatedGraph: VisibleGraph = {
      nodes: [
        { id: 'isolated', label: 'Isolated', kind: 'leaf', parentId: 'root' },
      ],
      edges: [],
    }

    await expect(new DagreLayoutEngine().layout(isolatedGraph)).resolves.toEqual({
      nodePositions: { isolated: { x: 0, y: 0 } },
    })
  })

  it('produces deterministic coordinates for the same visible graph', async () => {
    const engine = new DagreLayoutEngine()

    await expect(engine.layout(initialGraph)).resolves.toEqual(
      await engine.layout(initialGraph),
    )
  })

  it('lays out a changed visible graph from its own node set', async () => {
    const changedGraph: VisibleGraph = {
      nodes: [initialGraph.nodes[2]],
      edges: [],
    }
    const layout = await new DagreLayoutEngine().layout(changedGraph)

    expect(Object.keys(layout.nodePositions)).toEqual([initialGraph.nodes[2].id])
    expect(layout.nodePositions[initialGraph.nodes[0].id]).toBeUndefined()
  })
})
