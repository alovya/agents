import type { VisibleGraph } from '../graph/graph'
import type { LayoutEngine, LayoutResult } from '../layout/dagre-layout'

export type ApplyLatestLayout = (graph: VisibleGraph) => Promise<void>

export type LaidOutGraph = {
  graph: VisibleGraph
  layout: LayoutResult
}

export function canRenderLayoutForGraph(
  laidOutGraph: LaidOutGraph | null,
  visibleGraph: VisibleGraph,
): laidOutGraph is LaidOutGraph {
  return laidOutGraph?.graph === visibleGraph
}

export function createLatestLayoutRunner(
  layoutEngine: LayoutEngine,
  applyLayout: (graph: VisibleGraph, layout: LayoutResult) => void,
): ApplyLatestLayout {
  let latestRequestToken = 0

  return async (graph) => {
    const requestToken = ++latestRequestToken
    const layout = await layoutEngine.layout(graph)

    if (requestToken === latestRequestToken) {
      applyLayout(graph, layout)
    }
  }
}
