import { describe, expect, it, vi } from 'vitest'
import { MarkerType } from '@xyflow/react'
import { projectVisibleGraph } from './graph'
import { convertToReactFlow } from './react-flow-adapter'
import type { LayoutResult } from './dagre-layout'
import { SAMPLE_GRAPH_DOCUMENT, SAMPLE_NODE_IDS } from './sample-graph'

function layoutFor(graph: ReturnType<typeof projectVisibleGraph>): LayoutResult {
  return {
    nodePositions: Object.fromEntries(
      graph.nodes.map((node, index) => [node.id, { x: index * 260, y: 40 }]),
    ),
  }
}

describe('convertToReactFlow', () => {
  it('converts the collapsed sample projection to stable node and edge IDs', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )
    const flowGraph = convertToReactFlow(graph, layoutFor(graph), {})

    expect(flowGraph.nodes.map((node) => node.id)).toEqual([
      SAMPLE_NODE_IDS.preparation,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(flowGraph.edges.map((edge) => edge.id)).toEqual([
      'execution->preparation',
      'execution->report',
      'preparation->execution',
    ])
    expect(flowGraph.edges).toEqual([
      expect.objectContaining({
        id: 'execution->preparation',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.preparation,
      }),
      expect.objectContaining({
        id: 'execution->report',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.report,
      }),
      expect.objectContaining({
        id: 'preparation->execution',
        source: SAMPLE_NODE_IDS.preparation,
        target: SAMPLE_NODE_IDS.execution,
      }),
    ])
  })

  it('distinguishes composite and leaf affordances and binds composite callbacks', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )
    const onClickInto = vi.fn()
    const onExpand = vi.fn()
    const flowGraph = convertToReactFlow(graph, layoutFor(graph), {
      onClickInto,
      onExpand,
    })
    const composite = flowGraph.nodes.find(
      (node) => node.id === SAMPLE_NODE_IDS.preparation,
    )!
    const leaf = flowGraph.nodes.find(
      (node) => node.id === SAMPLE_NODE_IDS.report,
    )!

    expect(composite.data).toMatchObject({
      graphNodeId: SAMPLE_NODE_IDS.preparation,
      kind: 'composite',
      canClickInto: true,
      canExpand: true,
    })
    composite.data.onClickInto?.()
    composite.data.onExpand?.()
    expect(onClickInto).toHaveBeenCalledWith(SAMPLE_NODE_IDS.preparation)
    expect(onExpand).toHaveBeenCalledWith(SAMPLE_NODE_IDS.preparation)

    expect(leaf.data).toMatchObject({
      graphNodeId: SAMPLE_NODE_IDS.report,
      kind: 'leaf',
      canClickInto: false,
      canExpand: false,
    })
    expect(leaf.data).not.toHaveProperty('onClickInto')
    expect(leaf.data).not.toHaveProperty('onExpand')
  })

  it('adds directed arrowheads to every converted edge', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )
    const flowGraph = convertToReactFlow(graph, layoutFor(graph), {})

    expect(flowGraph.edges.map((edge) => edge.markerEnd)).toEqual([
      { type: MarkerType.ArrowClosed },
      { type: MarkerType.ArrowClosed },
      { type: MarkerType.ArrowClosed },
    ])
  })

  it('fails clearly when a visible node has no layout position', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )

    expect(() =>
      convertToReactFlow(graph, { nodePositions: {} }, {}),
    ).toThrow(`Missing layout position for visible node: ${SAMPLE_NODE_IDS.preparation}`)
  })
})
