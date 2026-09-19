import type { GraphDocument, VisibleGraph } from '../graph/graph-document'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import {
  createInitialExplorationState,
  findConnectedEdgeIds,
  type ExplorationState,
} from './explore-graph'

export type ViewSnapshot = {
  currentScopeId: string
  scopePath: readonly string[]
  expandedNodeIds: ReadonlySet<string>
  boldedEdgeIds: ReadonlySet<string>
  selectedNodeIds: ReadonlySet<string>
  selectionColourByNodeId: ReadonlyMap<string, number>
  nextSelectionColourId: number
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

export function replaceGraphDocument(
  activeGraph: ActiveGraph,
  document: GraphDocument,
): ActiveGraph {
  const scopePath = restoreScopePath(
    activeGraph.exploration.scopePath,
    document,
  )
  const currentScopeId = scopePath[scopePath.length - 1]
  const nodeIds = new Set(document.nodes.map((node) => node.id))
  const compositeNodeIds = new Set(
    document.nodes
      .filter((node) => node.kind === 'composite')
      .map((node) => node.id),
  )
  const expandedNodeIds = new Set(
    [...activeGraph.exploration.expandedNodeIds].filter((nodeId) =>
      compositeNodeIds.has(nodeId),
    ),
  )
  const visibleGraph = projectVisibleGraph(
    document,
    currentScopeId,
    expandedNodeIds,
  )
  const visibleNodeIds = new Set(visibleGraph.nodes.map((node) => node.id))
  const visibleEdgeIds = new Set(visibleGraph.edges.map((edge) => edge.id))

  return {
    document,
    exploration: {
      currentScopeId,
      scopePath,
      expandedNodeIds,
      boldedEdgeIds: new Set(
        [...activeGraph.exploration.boldedEdgeIds].filter((edgeId) =>
          visibleEdgeIds.has(edgeId),
        ),
      ),
      selectedNodeIds: new Set(
        [...activeGraph.exploration.selectedNodeIds].filter((nodeId) =>
          visibleNodeIds.has(nodeId),
        ),
      ),
      selectionColourByNodeId: new Map(
        [...activeGraph.exploration.selectionColourByNodeId].filter(
          ([nodeId]) => nodeIds.has(nodeId),
        ),
      ),
      nextSelectionColourId: activeGraph.exploration.nextSelectionColourId,
      selectedEdgeId:
        activeGraph.exploration.selectedEdgeId !== null &&
        visibleEdgeIds.has(activeGraph.exploration.selectedEdgeId)
          ? activeGraph.exploration.selectedEdgeId
          : null,
      projectionRevision: activeGraph.exploration.projectionRevision + 1,
    },
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

function restoreScopePath(
  previousScopePath: readonly string[],
  document: GraphDocument,
): readonly string[] {
  const nodesById = new Map(document.nodes.map((node) => [node.id, node]))
  const scopePath = [document.rootId]

  for (const nodeId of previousScopePath.slice(1)) {
    const node = nodesById.get(nodeId)
    const parentId = scopePath[scopePath.length - 1]

    if (node?.kind !== 'composite' || node.parentId !== parentId) {
      break
    }

    scopePath.push(nodeId)
  }

  return scopePath
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
  const previousVisibleNodeIds = new Set(
    previousVisibleGraph.nodes.map((node) => node.id),
  )
  const visibleNodeIds = new Set(visibleGraph.nodes.map((node) => node.id))
  const visibleEdgeIds = new Set(visibleGraph.edges.map((edge) => edge.id))
  const selectedNodeIds = new Set<string>()
  const newlySelectedNodeIds = new Set<string>()
  const expandedSelectedNodeIds = new Set<string>()

  for (const selectedNodeId of previousExploration.selectedNodeIds) {
    if (visibleNodeIds.has(selectedNodeId)) {
      selectedNodeIds.add(selectedNodeId)
      continue
    }

    if (nextExploration.expandedNodeIds.has(selectedNodeId)) {
      expandedSelectedNodeIds.add(selectedNodeId)

      for (const node of document.nodes) {
        if (node.parentId === selectedNodeId && visibleNodeIds.has(node.id)) {
          selectedNodeIds.add(node.id)
          newlySelectedNodeIds.add(node.id)
        }
      }

      continue
    }

    const parentId = document.nodes.find(
      (node) => node.id === selectedNodeId,
    )?.parentId

    if (
      parentId !== null &&
      parentId !== undefined &&
      !previousVisibleNodeIds.has(parentId) &&
      visibleNodeIds.has(parentId)
    ) {
      selectedNodeIds.add(parentId)
      newlySelectedNodeIds.add(parentId)
    }
  }

  const hiddenSelectedNodeIds = new Set(
    [...previousExploration.selectedNodeIds].filter(
      (nodeId) =>
        !visibleNodeIds.has(nodeId) &&
        !expandedSelectedNodeIds.has(nodeId),
    ),
  )
  const selectedEdgeId =
    previousExploration.selectedEdgeId !== null &&
    visibleEdgeIds.has(previousExploration.selectedEdgeId)
      ? previousExploration.selectedEdgeId
      : null
  const selectionColourByNodeId = new Map(
    nextExploration.selectionColourByNodeId,
  )
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

  const boldedEdgeIds = new Set(
    preserveBoldedEdges(
      previousVisibleGraph,
      previousExploration.boldedEdgeIds,
      nextEdgesByUnderlyingId,
      hiddenSelectedNodeIds,
    ),
  )

  for (const newlySelectedNodeId of newlySelectedNodeIds) {
    for (const edgeId of findConnectedEdgeIds(
      visibleGraph,
      newlySelectedNodeId,
    )) {
      boldedEdgeIds.add(edgeId)
    }
  }

  return {
    ...nextExploration,
    boldedEdgeIds,
    selectedNodeIds,
    selectionColourByNodeId,
    nextSelectionColourId: nextExploration.nextSelectionColourId,
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
    selectionColourByNodeId: new Map(exploration.selectionColourByNodeId),
    nextSelectionColourId: exploration.nextSelectionColourId,
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
    selectionColourByNodeId: new Map(view.selectionColourByNodeId),
    nextSelectionColourId: view.nextSelectionColourId,
    selectedEdgeId: view.selectedEdgeId,
    projectionRevision: exploration.projectionRevision + 1,
  }
}
