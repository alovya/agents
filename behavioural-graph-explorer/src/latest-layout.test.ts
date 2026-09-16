import { describe, expect, it } from 'vitest'
import { projectVisibleGraph, type GraphDocument, type VisibleGraph } from './graph'
import { createInitialExplorationState } from './exploration'
import type { LayoutEngine, LayoutResult } from './dagre-layout'
import {
  canRenderLayoutForGraph,
  createLatestLayoutRunner,
} from './latest-layout'

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
const layoutA: LayoutResult = {
  nodePositions: { A: { x: 1, y: 2 } },
  edgeRoutes: {},
}
const layoutB: LayoutResult = {
  nodePositions: { B: { x: 3, y: 4 } },
  edgeRoutes: {},
}

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

  it('keeps an old layout inapplicable when a new document has the same root and exploration values', async () => {
    const oldDocument: GraphDocument = {
      rootId: 'root',
      nodes: [
        { id: 'root', label: 'Old root', kind: 'composite', parentId: null },
        { id: 'left', label: 'Old left', kind: 'leaf', parentId: 'root' },
        { id: 'right', label: 'Right', kind: 'leaf', parentId: 'root' },
      ],
      edges: [],
    }
    const newDocument: GraphDocument = {
      ...oldDocument,
      nodes: [
        { id: 'root', label: 'New root', kind: 'composite', parentId: null },
        { id: 'left', label: 'New left', kind: 'leaf', parentId: 'root' },
        { id: 'right', label: 'Right', kind: 'leaf', parentId: 'root' },
      ],
    }
    const oldState = createInitialExplorationState(oldDocument)
    const newState = createInitialExplorationState(newDocument)
    const oldVisibleGraph = projectVisibleGraph(
      oldDocument,
      oldState.currentScopeId,
      oldState.expandedNodeIds,
    )
    const newVisibleGraph = projectVisibleGraph(
      newDocument,
      newState.currentScopeId,
      newState.expandedNodeIds,
    )
    const deferredOld = defer<LayoutResult>()
    const deferredNew = defer<LayoutResult>()
    const oldLayout: LayoutResult = {
      nodePositions: { left: { x: 1, y: 2 }, right: { x: 3, y: 4 } },
      edgeRoutes: {},
    }
    const newLayout: LayoutResult = {
      nodePositions: { left: { x: 5, y: 6 }, right: { x: 7, y: 8 } },
      edgeRoutes: {},
    }
    const layoutEngine: LayoutEngine = {
      layout: (graph) =>
        graph === oldVisibleGraph ? deferredOld.promise : deferredNew.promise,
    }
    const applicableLayouts: Array<{
      graph: VisibleGraph
      layout: LayoutResult
    }> = []
    let currentVisibleGraph = oldVisibleGraph
    const runLatestLayout = createLatestLayoutRunner(
      layoutEngine,
      (graph, layout) => {
        const laidOutGraph = { graph, layout }

        if (canRenderLayoutForGraph(laidOutGraph, currentVisibleGraph)) {
          applicableLayouts.push(laidOutGraph)
        }
      },
    )

    const oldRequest = runLatestLayout(oldVisibleGraph)
    currentVisibleGraph = newVisibleGraph
    const newRequest = runLatestLayout(newVisibleGraph)
    deferredNew.resolve(newLayout)
    await newRequest
    deferredOld.resolve(oldLayout)
    await oldRequest

    expect(oldState).toEqual(newState)
    expect(oldVisibleGraph.nodes.map((node) => node.id)).toEqual(
      newVisibleGraph.nodes.map((node) => node.id),
    )
    expect(oldVisibleGraph).not.toBe(newVisibleGraph)
    expect(
      canRenderLayoutForGraph(
        { graph: oldVisibleGraph, layout: oldLayout },
        newVisibleGraph,
      ),
    ).toBe(false)
    expect(applicableLayouts).toEqual([
      { graph: newVisibleGraph, layout: newLayout },
    ])
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
