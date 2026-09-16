import type { GraphDocument } from './graph'
import {
  createInitialExplorationState,
  type ExplorationState,
} from './exploration'

export type ViewSnapshot = {
  currentScopeId: string
  scopePath: readonly string[]
  expandedNodeIds: ReadonlySet<string>
}

export type ActiveGraph = {
  document: GraphDocument
  exploration: ExplorationState
  viewHistory: readonly ViewSnapshot[]
}

export function activateGraphDocument(document: GraphDocument): ActiveGraph {
  return {
    document,
    exploration: createInitialExplorationState(document),
    viewHistory: [],
  }
}

export function applyExplorationTransition(
  activeGraph: ActiveGraph,
  nextExploration: ExplorationState,
): ActiveGraph {
  if (nextExploration === activeGraph.exploration) {
    return activeGraph
  }

  const changedProjection =
    nextExploration.projectionRevision !==
    activeGraph.exploration.projectionRevision

  return {
    ...activeGraph,
    exploration: nextExploration,
    viewHistory: changedProjection
      ? [...activeGraph.viewHistory, captureView(activeGraph.exploration)]
      : activeGraph.viewHistory,
  }
}

export function undoLastViewChange(activeGraph: ActiveGraph): ActiveGraph {
  const previousView = activeGraph.viewHistory.at(-1)

  if (!previousView) {
    return activeGraph
  }

  return {
    ...activeGraph,
    exploration: restoreView(activeGraph.exploration, previousView),
    viewHistory: activeGraph.viewHistory.slice(0, -1),
  }
}

function captureView(exploration: ExplorationState): ViewSnapshot {
  return {
    currentScopeId: exploration.currentScopeId,
    scopePath: [...exploration.scopePath],
    expandedNodeIds: new Set(exploration.expandedNodeIds),
  }
}

function restoreView(
  exploration: ExplorationState,
  view: ViewSnapshot,
): ExplorationState {
  return {
    currentScopeId: view.currentScopeId,
    scopePath: [...view.scopePath],
    expandedNodeIds: new Set(view.expandedNodeIds),
    selectedNodeId: null,
    selectedEdgeId: null,
    projectionRevision: exploration.projectionRevision + 1,
  }
}
