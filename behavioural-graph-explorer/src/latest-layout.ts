import type { VisibleGraph } from './graph'
import type { LayoutEngine, LayoutResult } from './dagre-layout'

export type ApplyLatestLayout = (graph: VisibleGraph) => Promise<void>

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
