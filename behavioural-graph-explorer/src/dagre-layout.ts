import dagre from 'dagre'
import type { VisibleGraph } from './graph'

export const GRAPH_NODE_WIDTH = 220
export const GRAPH_NODE_HEIGHT = 96

export type NodePosition = { x: number; y: number }

export type LayoutResult = {
  nodePositions: Readonly<Record<string, NodePosition>>
}

export interface LayoutEngine {
  layout(graph: VisibleGraph): Promise<LayoutResult>
}

export class DagreLayoutEngine implements LayoutEngine {
  async layout(graph: VisibleGraph): Promise<LayoutResult> {
    const dagreGraph = new dagre.graphlib.Graph()
    dagreGraph.setGraph({ rankdir: 'LR' })
    dagreGraph.setDefaultEdgeLabel(() => ({}))

    for (const graphNode of graph.nodes) {
      dagreGraph.setNode(graphNode.id, {
        width: GRAPH_NODE_WIDTH,
        height: GRAPH_NODE_HEIGHT,
      })
    }

    for (const graphEdge of graph.edges) {
      dagreGraph.setEdge(graphEdge.source, graphEdge.target)
    }

    dagre.layout(dagreGraph)

    const nodePositions: Record<string, NodePosition> = {}

    for (const graphNode of graph.nodes) {
      const dagreNode = dagreGraph.node(graphNode.id)

      if (
        dagreNode === undefined ||
        !Number.isFinite(dagreNode.x) ||
        !Number.isFinite(dagreNode.y)
      ) {
        throw new Error(`Dagre did not produce a finite position for node: ${graphNode.id}`)
      }

      nodePositions[graphNode.id] = {
        x: dagreNode.x - GRAPH_NODE_WIDTH / 2,
        y: dagreNode.y - GRAPH_NODE_HEIGHT / 2,
      }
    }

    return { nodePositions }
  }
}
