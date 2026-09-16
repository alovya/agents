import { describe, expect, it } from 'vitest'
import type { VisibleGraph } from './graph'
import type { LayoutEngine, LayoutResult } from './dagre-layout'
import { createLatestLayoutRunner } from './latest-layout'

const graphA: VisibleGraph = {
  nodes: [
    { id: 'A', label: 'A', kind: 'leaf', parentId: 'root' },
  ],
  edges: [],
}
const graphB: VisibleGraph = {
  nodes: [
    { id: 'B', label: 'B', kind: 'leaf', parentId: 'root' },
  ],
  edges: [],
}
const layoutA: LayoutResult = { nodePositions: { A: { x: 1, y: 2 } } }
const layoutB: LayoutResult = { nodePositions: { B: { x: 3, y: 4 } } }

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
}

function defer<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })

  return { promise, resolve }
}

describe('createLatestLayoutRunner', () => {
  it('applies only the latest result when layout requests finish out of order', async () => {
    const deferredA = defer<LayoutResult>()
    const deferredB = defer<LayoutResult>()
    const layoutEngine: LayoutEngine = {
      layout: (graph) => (graph === graphA ? deferredA.promise : deferredB.promise),
    }
    const applied: Array<{ graph: VisibleGraph; layout: LayoutResult }> = []
    const runLatestLayout = createLatestLayoutRunner(
      layoutEngine,
      (graph, layout) => applied.push({ graph, layout }),
    )

    const requestA = runLatestLayout(graphA)
    const requestB = runLatestLayout(graphB)
    deferredB.resolve(layoutB)
    await requestB
    deferredA.resolve(layoutA)
    await requestA

    expect(applied).toEqual([{ graph: graphB, layout: layoutB }])
  })

  it('applies each sequential latest request', async () => {
    const layoutEngine: LayoutEngine = {
      layout: async (graph) => (graph === graphA ? layoutA : layoutB),
    }
    const applied: Array<{ graph: VisibleGraph; layout: LayoutResult }> = []
    const runLatestLayout = createLatestLayoutRunner(
      layoutEngine,
      (graph, layout) => applied.push({ graph, layout }),
    )

    await runLatestLayout(graphA)
    await runLatestLayout(graphB)

    expect(applied).toEqual([
      { graph: graphA, layout: layoutA },
      { graph: graphB, layout: layoutB },
    ])
  })
})
