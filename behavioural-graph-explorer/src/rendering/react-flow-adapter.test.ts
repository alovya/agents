import { describe, expect, it, vi } from 'vitest'
import { MarkerType } from '@xyflow/react'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import type { VisibleGraph } from '../graph/graph-document'
import {
  convertToReactFlow,
  GRAPH_ARROWHEAD_SIZE,
  GRAPH_EDGE_COLOUR,
} from './react-flow-adapter'
import type { LayoutResult } from '../layout/dagre-layout'
import { SAMPLE_GRAPH_DOCUMENT, SAMPLE_NODE_IDS } from '../graph/sample-graph'

function layoutFor(graph: ReturnType<typeof projectVisibleGraph>): LayoutResult {
  return {
    nodePositions: Object.fromEntries(
      graph.nodes.map((node, index) => [node.id, { x: index * 260, y: 40 }]),
    ),
    edgeRoutes: Object.fromEntries(
      graph.edges.map((edge) => [
        edge.id,
        [
          { x: 0, y: 88 },
          { x: 100, y: 88 },
        ],
      ]),
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
      kind: 'composite',
      canClickInto: true,
      canExpand: true,
    })
    composite.data.onClickInto?.()
    composite.data.onExpand?.()
    expect(onClickInto).toHaveBeenCalledWith(SAMPLE_NODE_IDS.preparation)
    expect(onExpand).toHaveBeenCalledWith(SAMPLE_NODE_IDS.preparation)

    expect(leaf.data).toMatchObject({
      kind: 'leaf',
      canClickInto: false,
      canExpand: false,
    })
    expect(leaf.data).not.toHaveProperty('onClickInto')
    expect(leaf.data).not.toHaveProperty('onExpand')
  })

  it('uses Dagre routes for directed edges', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )
    const flowGraph = convertToReactFlow(graph, layoutFor(graph), {})

    expect(flowGraph.edges.map((edge) => edge.type)).toEqual([
      'dagre',
      'dagre',
      'dagre',
    ])
    expect(flowGraph.edges.map((edge) => edge.sourceHandle)).toEqual([
      'source-bottom',
      'source-right',
      'source-top',
    ])
    expect(flowGraph.edges.map((edge) => edge.targetHandle)).toEqual([
      'target-bottom',
      'target-left',
      'target-top',
    ])
    expect(flowGraph.edges.map((edge) => edge.style)).toEqual([
      { stroke: GRAPH_EDGE_COLOUR },
      { stroke: GRAPH_EDGE_COLOUR },
      { stroke: GRAPH_EDGE_COLOUR },
    ])
    expect(flowGraph.edges.map((edge) => edge.markerEnd)).toEqual([
      {
        type: MarkerType.ArrowClosed,
        color: GRAPH_EDGE_COLOUR,
        width: GRAPH_ARROWHEAD_SIZE,
        height: GRAPH_ARROWHEAD_SIZE,
        markerUnits: 'userSpaceOnUse',
      },
      {
        type: MarkerType.ArrowClosed,
        color: GRAPH_EDGE_COLOUR,
        width: GRAPH_ARROWHEAD_SIZE,
        height: GRAPH_ARROWHEAD_SIZE,
        markerUnits: 'userSpaceOnUse',
      },
      {
        type: MarkerType.ArrowClosed,
        color: GRAPH_EDGE_COLOUR,
        width: GRAPH_ARROWHEAD_SIZE,
        height: GRAPH_ARROWHEAD_SIZE,
        markerUnits: 'userSpaceOnUse',
      },
    ])
  })

  it('chooses top and bottom handles for vertical edges', () => {
    const graph: VisibleGraph = {
      nodes: [
        {
          id: 'source',
          label: 'Source',
          kind: 'leaf',
          parentId: null,
        },
        {
          id: 'target',
          label: 'Target',
          kind: 'leaf',
          parentId: null,
        },
      ],
      edges: [
        {
          id: 'source->target',
          source: 'source',
          target: 'target',
          underlyingEdgeIds: ['source-to-target'],
        },
      ],
    }
    const flowGraph = convertToReactFlow(
      graph,
      {
        nodePositions: {
          source: { x: 0, y: 200 },
          target: { x: 0, y: 0 },
        },
        edgeRoutes: {
          'source->target': [
            { x: 110, y: 200 },
            { x: 110, y: 0 },
          ],
        },
      },
      {},
    )

    expect(flowGraph.edges[0]).toMatchObject({
      sourceHandle: 'source-top',
      targetHandle: 'target-bottom',
      style: { stroke: GRAPH_EDGE_COLOUR },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: GRAPH_EDGE_COLOUR,
        width: GRAPH_ARROWHEAD_SIZE,
        height: GRAPH_ARROWHEAD_SIZE,
        markerUnits: 'userSpaceOnUse',
      },
    })
  })

  it('fails clearly when a visible node has no layout position', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_GRAPH_DOCUMENT.rootId,
      new Set(),
    )

    expect(() =>
      convertToReactFlow(
        graph,
        { nodePositions: {}, edgeRoutes: {} },
        {},
      ),
    ).toThrow(`Missing layout position for visible node: ${SAMPLE_NODE_IDS.preparation}`)
  })
})
