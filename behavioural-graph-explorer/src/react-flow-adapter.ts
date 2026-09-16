import { MarkerType } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'
import type { GraphNode, NodeKind, VisibleGraph } from './graph'
import type { LayoutResult } from './dagre-layout'

export const GRAPH_ARROWHEAD_SIZE = 37.5

export const EDGE_DIRECTION_COLOURS = {
  top: '#CC79A7',
  right: '#0072B2',
  bottom: '#009E73',
  left: '#D55E00',
} as const

export type GraphFlowNodeData = {
  graphNodeId: string
  label: string
  kind: NodeKind
  canClickInto: boolean
  canExpand: boolean
  onClickInto?: () => void
  onExpand?: () => void
}

export type GraphNodeActions = {
  onClickInto?: (nodeId: string) => void
  onExpand?: (nodeId: string) => void
}

export function convertToReactFlow(
  graph: VisibleGraph,
  layout: LayoutResult,
  actions: GraphNodeActions,
): { nodes: Node<GraphFlowNodeData>[]; edges: Edge[] } {
  const nodes = graph.nodes.map((graphNode) => {
    const position = layout.nodePositions[graphNode.id]

    if (position === undefined) {
      throw new Error(
        `Missing layout position for visible node: ${graphNode.id}`,
      )
    }

    return {
      id: graphNode.id,
      type: 'graph',
      position: { x: position.x, y: position.y },
      data: createNodeData(graphNode, actions),
    }
  })

  const edges = graph.edges.map((graphEdge) => {
    const sourcePosition = layout.nodePositions[graphEdge.source]
    const targetPosition = layout.nodePositions[graphEdge.target]
    const sourceSide = chooseSourceSide(sourcePosition, targetPosition)
    const reverseEdge = graph.edges.find(
      (candidate) =>
        candidate.id !== graphEdge.id &&
        candidate.source === graphEdge.target &&
        candidate.target === graphEdge.source,
    )
    const handles = chooseEdgeHandles(graphEdge, reverseEdge, sourceSide)
    const colour = EDGE_DIRECTION_COLOURS[sourceSide]

    return {
      id: graphEdge.id,
      source: graphEdge.source,
      target: graphEdge.target,
      type: 'smoothstep' as const,
      sourceHandle: handles.sourceHandle,
      targetHandle: handles.targetHandle,
      style: { stroke: colour },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: colour,
        width: GRAPH_ARROWHEAD_SIZE,
        height: GRAPH_ARROWHEAD_SIZE,
        markerUnits: 'userSpaceOnUse',
      },
    }
  })

  return { nodes, edges }
}

type HandleSide = 'top' | 'right' | 'bottom' | 'left'

function chooseSourceSide(
  sourcePosition: { x: number; y: number } | undefined,
  targetPosition: { x: number; y: number } | undefined,
): HandleSide {
  if (!sourcePosition || !targetPosition) {
    throw new Error('Cannot choose edge direction without positions for both endpoints')
  }

  const deltaX = targetPosition.x - sourcePosition.x
  const deltaY = targetPosition.y - sourcePosition.y

  return Math.abs(deltaX) >= Math.abs(deltaY)
    ? deltaX >= 0
      ? 'right'
      : 'left'
    : deltaY >= 0
      ? 'bottom'
      : 'top'
}

function chooseEdgeHandles(
  graphEdge: VisibleGraph['edges'][number],
  reverseEdge: VisibleGraph['edges'][number] | undefined,
  sourceSide: HandleSide,
): { sourceHandle: string; targetHandle: string } {
  if (reverseEdge) {
    const isFirstParallelEdge = graphEdge.id < reverseEdge.id
    const laneSide = chooseParallelLaneSide(sourceSide, isFirstParallelEdge)

    return {
      sourceHandle: `source-${laneSide}`,
      targetHandle: `target-${laneSide}`,
    }
  }

  const targetSide = oppositeHandleSide(sourceSide)

  return {
    sourceHandle: `source-${sourceSide}`,
    targetHandle: `target-${targetSide}`,
  }
}

function chooseParallelLaneSide(
  primarySide: HandleSide,
  isFirstParallelEdge: boolean,
): HandleSide {
  const isHorizontal = primarySide === 'left' || primarySide === 'right'

  if (isHorizontal) {
    return isFirstParallelEdge ? 'bottom' : 'top'
  }

  return isFirstParallelEdge ? 'right' : 'left'
}

function oppositeHandleSide(side: HandleSide): HandleSide {
  if (side === 'top') return 'bottom'
  if (side === 'right') return 'left'
  if (side === 'bottom') return 'top'
  return 'right'
}

function createNodeData(
  graphNode: GraphNode,
  actions: GraphNodeActions,
): GraphFlowNodeData {
  const data: GraphFlowNodeData = {
    graphNodeId: graphNode.id,
    label: graphNode.label,
    kind: graphNode.kind,
    canClickInto: graphNode.kind === 'composite',
    canExpand: graphNode.kind === 'composite',
  }

  if (graphNode.kind === 'composite') {
    const onClickInto = actions.onClickInto
    const onExpand = actions.onExpand

    if (onClickInto) {
      data.onClickInto = () => onClickInto(graphNode.id)
    }

    if (onExpand) {
      data.onExpand = () => onExpand(graphNode.id)
    }
  }

  return data
}
