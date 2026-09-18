import type { GraphDocument, VisibleGraph } from '../graph/graph-document'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import {
  createInitialExplorationState,
  type ExplorationState,
} from './explore-graph'

export type ViewSnapshot = {
  currentScopeId: string
  scopePath: readonly string[]
  expandedNodeIds: ReadonlySet<string>
  boldedEdgeIds: ReadonlySet<string>
  selectedNodeIds: ReadonlySet<string>
  selectedEdgeId: string | null
}

export type ActiveGraph = {
  document: GraphDocument
  exploration: ExplorationState
  viewHistory: readonly ViewSnapshot[]
  redoHistory: readonly ViewSnapshot[]
}

export function activateGraphDocument(document: GraphDocument): ActiveGraph {
  return {
    document,
    exploration: createInitialExplorationState(document),
    viewHistory: [],
    redoHistory: [],
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
  const exploration = changedProjection
    ? preserveVisibleSelection(
        activeGraph.document,
        activeGraph.exploration,
        nextExploration,
      )
    : nextExploration

  return {
    ...activeGraph,
    exploration,
    viewHistory: changedProjection
      ? [...activeGraph.viewHistory, captureView(activeGraph.exploration)]
      : activeGraph.viewHistory,
    redoHistory: changedProjection ? [] : activeGraph.redoHistory,
  }
}

export function undoLastViewChange(activeGraph: ActiveGraph): ActiveGraph {
  const previousView = activeGraph.viewHistory.at(-1)

  if (!previousView) {
    return activeGraph
  }

  const restoredExploration = restoreView(
    activeGraph.exploration,
    previousView,
  )

  return {
    ...activeGraph,
    exploration: restoredExploration,
    viewHistory: activeGraph.viewHistory.slice(0, -1),
    redoHistory: [
      ...activeGraph.redoHistory,
      captureView(activeGraph.exploration),
    ],
  }
}

export function redoLastViewChange(activeGraph: ActiveGraph): ActiveGraph {
  const nextView = activeGraph.redoHistory.at(-1)

  if (!nextView) {
    return activeGraph
  }

  const restoredExploration = restoreView(
    activeGraph.exploration,
    nextView,
  )

  return {
    ...activeGraph,
    exploration: restoredExploration,
    viewHistory: [
      ...activeGraph.viewHistory,
      captureView(activeGraph.exploration),
    ],
    redoHistory: activeGraph.redoHistory.slice(0, -1),
  }
}

function preserveVisibleSelection(
  document: GraphDocument,
  previousExploration: ExplorationState,
  nextExploration: ExplorationState,
): ExplorationState {
  const previousVisibleGraph = projectVisibleGraph(
    document,
    previousExploration.currentScopeId,
    previousExploration.expandedNodeIds,
  )
  const visibleGraph = projectVisibleGraph(
    document,
    nextExploration.currentScopeId,
    nextExploration.expandedNodeIds,
  )
  const visibleNodeIds = new Set(visibleGraph.nodes.map((node) => node.id))
  const visibleEdgeIds = new Set(visibleGraph.edges.map((edge) => edge.id))
  const selectedNodeIds = new Set(
    [...previousExploration.selectedNodeIds].filter((nodeId) =>
      visibleNodeIds.has(nodeId),
    ),
  )
  const hiddenSelectedNodeIds = new Set(
    [...previousExploration.selectedNodeIds].filter(
      (nodeId) => !visibleNodeIds.has(nodeId),
    ),
  )
  const selectedEdgeId =
    previousExploration.selectedEdgeId !== null &&
    visibleEdgeIds.has(previousExploration.selectedEdgeId)
      ? previousExploration.selectedEdgeId
      : null
  const nextEdgesByUnderlyingId = new Map<string, Set<string>>()

  for (const edge of visibleGraph.edges) {
    for (const underlyingEdgeId of edge.underlyingEdgeIds) {
      const nextEdgeIds = nextEdgesByUnderlyingId.get(underlyingEdgeId)

      if (nextEdgeIds) {
        nextEdgeIds.add(edge.id)
      } else {
        nextEdgesByUnderlyingId.set(
          underlyingEdgeId,
          new Set([edge.id]),
        )
      }
    }
  }

  const boldedEdgeIds = preserveBoldedEdges(
    previousVisibleGraph,
    previousExploration.boldedEdgeIds,
    nextEdgesByUnderlyingId,
    hiddenSelectedNodeIds,
  )

  return {
    ...nextExploration,
    boldedEdgeIds,
    selectedNodeIds,
    selectedEdgeId,
  }
}

function preserveBoldedEdges(
  previousVisibleGraph: VisibleGraph,
  previousBoldedEdgeIds: ReadonlySet<string>,
  nextEdgesByUnderlyingId: ReadonlyMap<string, ReadonlySet<string>>,
  hiddenSelectedNodeIds: ReadonlySet<string>,
): ReadonlySet<string> {
  const boldedEdgeIds = new Set<string>()

  for (const edge of previousVisibleGraph.edges) {
    if (
      !previousBoldedEdgeIds.has(edge.id) ||
      hiddenSelectedNodeIds.has(edge.source) ||
      hiddenSelectedNodeIds.has(edge.target)
    ) {
      continue
    }

    for (const underlyingEdgeId of edge.underlyingEdgeIds) {
      for (const nextEdgeId of nextEdgesByUnderlyingId.get(
        underlyingEdgeId,
      ) ?? []) {
        boldedEdgeIds.add(nextEdgeId)
      }
    }
  }

  return boldedEdgeIds
}

function captureView(exploration: ExplorationState): ViewSnapshot {
  return {
    currentScopeId: exploration.currentScopeId,
    scopePath: [...exploration.scopePath],
    expandedNodeIds: new Set(exploration.expandedNodeIds),
    boldedEdgeIds: new Set(exploration.boldedEdgeIds),
    selectedNodeIds: new Set(exploration.selectedNodeIds),
    selectedEdgeId: exploration.selectedEdgeId,
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
    boldedEdgeIds: new Set(view.boldedEdgeIds),
    selectedNodeIds: new Set(view.selectedNodeIds),
    selectedEdgeId: view.selectedEdgeId,
    projectionRevision: exploration.projectionRevision + 1,
  }
}
