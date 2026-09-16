import { MarkerType } from '@xyflow/react'
import type { Edge, Node } from '@xyflow/react'
import type { GraphNode, NodeKind, VisibleGraph } from './graph'
import type { LayoutResult } from './dagre-layout'

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

  const edges = graph.edges.map((graphEdge) => ({
    id: graphEdge.id,
    source: graphEdge.source,
    target: graphEdge.target,
    markerEnd: { type: MarkerType.ArrowClosed },
  }))

  return { nodes, edges }
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
