import type { GraphDocument, VisibleGraph } from './graph'

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
