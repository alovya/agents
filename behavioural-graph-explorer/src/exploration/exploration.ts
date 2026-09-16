import type { GraphDocument, VisibleGraph } from '../graph/graph'

export type ExplorationState = {
  currentScopeId: string
  scopePath: readonly string[]
  expandedNodeIds: ReadonlySet<string>
  selectedNodeId: string | null
  selectedEdgeId: string | null
  projectionRevision: number
}

export function createInitialExplorationState(
  document: GraphDocument,
): ExplorationState {
  return {
    currentScopeId: document.rootId,
    scopePath: [document.rootId],
    expandedNodeIds: new Set(),
    selectedNodeId: null,
    selectedEdgeId: null,
    projectionRevision: 0,
  }
}

export function selectNode(
  state: ExplorationState,
  graph: VisibleGraph,
  nodeId: string,
): ExplorationState {
  if (!graph.nodes.some((node) => node.id === nodeId)) {
    return state
  }

  return {
    ...state,
    selectedNodeId: nodeId,
    selectedEdgeId: null,
  }
}

export function selectEdge(
  state: ExplorationState,
  graph: VisibleGraph,
  edgeId: string,
): ExplorationState {
  if (!graph.edges.some((edge) => edge.id === edgeId)) {
    return state
  }

  if (state.selectedEdgeId === edgeId) {
    return {
      ...state,
      selectedNodeId: null,
      selectedEdgeId: null,
    }
  }

  return {
    ...state,
    selectedNodeId: null,
    selectedEdgeId: edgeId,
  }
}

export function clearSelection(state: ExplorationState): ExplorationState {
  if (state.selectedNodeId === null && state.selectedEdgeId === null) {
    return state
  }

  return {
    ...state,
    selectedNodeId: null,
    selectedEdgeId: null,
  }
}

export function clickIntoComposite(
  document: GraphDocument,
  graph: VisibleGraph,
  state: ExplorationState,
  nodeId: string,
): ExplorationState {
  if (!isVisibleComposite(document, graph, nodeId)) {
    return state
  }

  return acceptScopeChange(state, nodeId, [...state.scopePath, nodeId])
}

export function returnToEnclosingScope(
  state: ExplorationState,
): ExplorationState {
  if (state.scopePath.length <= 1) {
    return state
  }

  const scopePath = state.scopePath.slice(0, -1)
  const currentScopeId = scopePath[scopePath.length - 1]

  return acceptScopeChange(state, currentScopeId, scopePath)
}

export function expandComposite(
  document: GraphDocument,
  graph: VisibleGraph,
  state: ExplorationState,
  nodeId: string,
): ExplorationState {
  if (!isVisibleComposite(document, graph, nodeId)) {
    return state
  }

  const expandedNodeIds = new Set(state.expandedNodeIds)
  expandedNodeIds.add(nodeId)

  return acceptExpansionChange(state, expandedNodeIds)
}

export function expandVisibleComposites(
  graph: VisibleGraph,
  state: ExplorationState,
): ExplorationState {
  const visibleCompositeIds = graph.nodes
    .filter((node) => node.kind === 'composite')
    .map((node) => node.id)

  return addExpansionIds(state, visibleCompositeIds)
}

export function expandAllComposites(
  document: GraphDocument,
  state: ExplorationState,
): ExplorationState {
  const nodesById = new Map(document.nodes.map((node) => [node.id, node]))
  const compositeDescendantIds = document.nodes
    .filter(
      (node) =>
        node.kind === 'composite' &&
        node.id !== state.currentScopeId &&
        isDescendantOfScope(node.id, state.currentScopeId, nodesById),
    )
    .map((node) => node.id)

  return addExpansionIds(state, compositeDescendantIds)
}

function isVisibleComposite(
  document: GraphDocument,
  graph: VisibleGraph,
  nodeId: string,
): boolean {
  const visibleNode = graph.nodes.find((node) => node.id === nodeId)
  const documentNode = document.nodes.find((node) => node.id === nodeId)

  return (
    visibleNode?.kind === 'composite' && documentNode?.kind === 'composite'
  )
}

function acceptScopeChange(
  state: ExplorationState,
  currentScopeId: string,
  scopePath: readonly string[],
): ExplorationState {
  return {
    ...state,
    currentScopeId,
    scopePath,
    selectedNodeId: null,
    selectedEdgeId: null,
    projectionRevision: state.projectionRevision + 1,
  }
}

function addExpansionIds(
  state: ExplorationState,
  candidateIds: readonly string[],
): ExplorationState {
  const expandedNodeIds = new Set(state.expandedNodeIds)

  for (const candidateId of candidateIds) {
    expandedNodeIds.add(candidateId)
  }

  if (expandedNodeIds.size === state.expandedNodeIds.size) {
    return state
  }

  return acceptExpansionChange(state, expandedNodeIds)
}

function acceptExpansionChange(
  state: ExplorationState,
  expandedNodeIds: ReadonlySet<string>,
): ExplorationState {
  return {
    ...state,
    expandedNodeIds,
    selectedNodeId: null,
    selectedEdgeId: null,
    projectionRevision: state.projectionRevision + 1,
  }
}

function isDescendantOfScope(
  nodeId: string,
  scopeId: string,
  nodesById: ReadonlyMap<string, GraphDocument['nodes'][number]>,
): boolean {
  let parentId = nodesById.get(nodeId)?.parentId ?? null

  while (parentId !== null) {
    if (parentId === scopeId) {
      return true
    }

    parentId = nodesById.get(parentId)?.parentId ?? null
  }

  return false
}
