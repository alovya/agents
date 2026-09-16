import dagre from 'dagre'
import type { VisibleGraph } from './graph'

export const GRAPH_NODE_WIDTH = 220
export const GRAPH_NODE_HEIGHT = 96

export type LayoutPoint = { x: number; y: number }
export type NodePosition = LayoutPoint

export type LayoutResult = {
  nodePositions: Readonly<Record<string, NodePosition>>
  edgeRoutes: Readonly<Record<string, ReadonlyArray<LayoutPoint>>>
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
    const edgeRoutes: Record<string, ReadonlyArray<LayoutPoint>> = {}

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

    for (const graphEdge of graph.edges) {
      const dagreEdge = dagreGraph.edge(graphEdge.source, graphEdge.target)

      if (dagreEdge === undefined || dagreEdge.points.length < 2) {
        throw new Error(`Dagre did not produce a route for edge: ${graphEdge.id}`)
      }

      edgeRoutes[graphEdge.id] = dagreEdge.points.map(({ x, y }) => ({ x, y }))
    }

    return { nodePositions, edgeRoutes }
  }
}
