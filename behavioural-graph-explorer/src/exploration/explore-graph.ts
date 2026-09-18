import type { GraphDocument, VisibleGraph } from '../graph/graph-document'

export type ExplorationState = {
  currentScopeId: string
  scopePath: readonly string[]
  expandedNodeIds: ReadonlySet<string>
  boldedEdgeIds: ReadonlySet<string>
  selectedNodeIds: ReadonlySet<string>
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
    boldedEdgeIds: new Set(),
    selectedNodeIds: new Set(),
    selectedEdgeId: null,
    projectionRevision: 0,
  }
}

export function findConnectedEdgeIds(
  graph: VisibleGraph,
  nodeId: string,
): readonly string[] {
  return graph.edges
    .filter((edge) => edge.source === nodeId || edge.target === nodeId)
    .map((edge) => edge.id)
}

export function selectNode(
  state: ExplorationState,
  graph: VisibleGraph,
  nodeId: string,
): ExplorationState {
  if (!graph.nodes.some((node) => node.id === nodeId)) {
    return state
  }

  const selectedNodeIds = new Set(state.selectedNodeIds)

  if (selectedNodeIds.has(nodeId)) {
    selectedNodeIds.delete(nodeId)
  } else {
    selectedNodeIds.add(nodeId)
  }

  const boldedEdgeIds = new Set<string>()

  for (const selectedNodeId of selectedNodeIds) {
    for (const edgeId of findConnectedEdgeIds(graph, selectedNodeId)) {
      boldedEdgeIds.add(edgeId)
    }
  }

  return {
    ...state,
    boldedEdgeIds,
    selectedNodeIds,
    selectedEdgeId: null,
  }
}

export function canCollapseOneLevel(
  document: GraphDocument,
  graph: VisibleGraph,
  state: ExplorationState,
  nodeId: string,
): boolean {
  const node = graph.nodes.find((candidate) => candidate.id === nodeId)
  const parent = node?.parentId === null || node?.parentId === undefined
    ? undefined
    : document.nodes.find((candidate) => candidate.id === node.parentId)

  return (
    parent?.kind === 'composite' &&
    parent.id !== state.currentScopeId &&
    state.expandedNodeIds.has(parent.id)
  )
}

export function collapseOneLevel(
  document: GraphDocument,
  graph: VisibleGraph,
  state: ExplorationState,
  nodeId: string,
): ExplorationState {
  if (!canCollapseOneLevel(document, graph, state, nodeId)) {
    return state
  }

  const node = graph.nodes.find((candidate) => candidate.id === nodeId)
  const parentId = node?.parentId

  if (parentId === null || parentId === undefined) {
    return state
  }

  const expandedNodeIds = new Set(state.expandedNodeIds)
  expandedNodeIds.delete(parentId)

  return acceptExpansionChange(state, expandedNodeIds)
}

export function selectEdge(
  state: ExplorationState,
  graph: VisibleGraph,
  edgeId: string,
): ExplorationState {
  if (!graph.edges.some((edge) => edge.id === edgeId)) {
    return state
  }

  const boldedEdgeIds = new Set(state.boldedEdgeIds)

  if (boldedEdgeIds.has(edgeId)) {
    boldedEdgeIds.delete(edgeId)
  } else {
    boldedEdgeIds.add(edgeId)
  }

  if (state.selectedEdgeId === edgeId) {
    return {
      ...state,
      boldedEdgeIds,
      selectedNodeIds: new Set(),
      selectedEdgeId: null,
    }
  }

  return {
    ...state,
    boldedEdgeIds,
    selectedNodeIds: new Set(),
    selectedEdgeId: edgeId,
  }
}

export function clearSelectedArrows(
  state: ExplorationState,
  graph: VisibleGraph,
): ExplorationState {
  const visibleEdgeIds = new Set(graph.edges.map((edge) => edge.id))
  const boldedEdgeIds = new Set(
    [...state.boldedEdgeIds].filter((edgeId) => !visibleEdgeIds.has(edgeId)),
  )

  if (boldedEdgeIds.size === state.boldedEdgeIds.size) {
    return state
  }

  return {
    ...state,
    boldedEdgeIds,
  }
}

export function clearSelectedNodes(state: ExplorationState): ExplorationState {
  if (state.selectedNodeIds.size === 0) {
    return state
  }

  return {
    ...state,
    selectedNodeIds: new Set(),
  }
}

export function clearSelection(state: ExplorationState): ExplorationState {
  if (state.selectedNodeIds.size === 0 && state.selectedEdgeId === null) {
    return state
  }

  return {
    ...state,
    selectedNodeIds: new Set(),
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

export function collapseOneVisibleLevel(
  document: GraphDocument,
  state: ExplorationState,
): ExplorationState {
  const expandedNodeIds = new Set(state.expandedNodeIds)

  for (const node of document.nodes) {
    if (
      node.kind === 'composite' &&
      node.parentId === state.currentScopeId
    ) {
      expandedNodeIds.delete(node.id)
    }
  }

  if (expandedNodeIds.size === state.expandedNodeIds.size) {
    return state
  }

  return acceptExpansionChange(state, expandedNodeIds)
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

export function collapseAllComposites(
  document: GraphDocument,
  state: ExplorationState,
): ExplorationState {
  const nodesById = new Map(document.nodes.map((node) => [node.id, node]))
  const expandedNodeIds = new Set(state.expandedNodeIds)

  for (const node of document.nodes) {
    if (
      node.kind === 'composite' &&
      node.id !== state.currentScopeId &&
      isDescendantOfScope(node.id, state.currentScopeId, nodesById)
    ) {
      expandedNodeIds.delete(node.id)
    }
  }

  if (expandedNodeIds.size === state.expandedNodeIds.size) {
    return state
  }

  return acceptExpansionChange(state, expandedNodeIds)
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
    boldedEdgeIds: new Set(),
    selectedNodeIds: new Set(),
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
    boldedEdgeIds: new Set(),
    selectedNodeIds: new Set(),
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
