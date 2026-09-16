import type {
  ExpansionState,
  GraphDocument,
  GraphNode,
  VisibleGraph,
} from './graph-document'

export function projectVisibleGraph(
  document: GraphDocument,
  currentScopeId: string,
  expandedNodeIds: ExpansionState,
): VisibleGraph {
  const nodesById = indexNodes(document.nodes)
  const currentScope = nodesById.get(currentScopeId)

  if (!currentScope) {
    throw new Error(`Unknown scope ID: ${currentScopeId}`)
  }

  if (currentScope.kind !== 'composite') {
    throw new Error(`Scope ID is not composite: ${currentScopeId}`)
  }

  const childrenByParentId = groupNodesByParent(document.nodes)
  const visibleNodes: GraphNode[] = []
  const visibleNodeIds = new Set<string>()

  addVisibleChildren(
    currentScopeId,
    childrenByParentId,
    expandedNodeIds,
    visibleNodes,
    visibleNodeIds,
  )

  const summaries = new Map<string, MutableVisibleGraphEdge>()

  for (const canonicalEdge of document.edges) {
    const source = findVisibleRepresentative(
      canonicalEdge.from,
      currentScopeId,
      nodesById,
      visibleNodeIds,
    )
    const target = findVisibleRepresentative(
      canonicalEdge.to,
      currentScopeId,
      nodesById,
      visibleNodeIds,
    )

    if (!source || !target || source === target) {
      continue
    }

    const summaryId = `${source}->${target}`
    const summary = summaries.get(summaryId)

    if (summary) {
      summary.underlyingEdgeIds.push(canonicalEdge.id)
    } else {
      summaries.set(summaryId, {
        id: summaryId,
        source,
        target,
        underlyingEdgeIds: [canonicalEdge.id],
      })
    }
  }

  const edges = [...summaries.values()]
    .sort(compareVisibleEdges)
    .map((summary) => ({
      ...summary,
      underlyingEdgeIds: [...summary.underlyingEdgeIds].sort(compareStrings),
    }))

  return { nodes: visibleNodes, edges }
}

type MutableVisibleGraphEdge = {
  id: string
  source: string
  target: string
  underlyingEdgeIds: string[]
}

function indexNodes(nodes: readonly GraphNode[]): Map<string, GraphNode> {
  return new Map(nodes.map((node) => [node.id, node]))
}

function groupNodesByParent(
  nodes: readonly GraphNode[],
): Map<string | null, GraphNode[]> {
  const childrenByParentId = new Map<string | null, GraphNode[]>()

  for (const node of nodes) {
    const siblings = childrenByParentId.get(node.parentId)

    if (siblings) {
      siblings.push(node)
    } else {
      childrenByParentId.set(node.parentId, [node])
    }
  }

  return childrenByParentId
}

function addVisibleChildren(
  parentId: string,
  childrenByParentId: Map<string | null, GraphNode[]>,
  expandedNodeIds: ExpansionState,
  visibleNodes: GraphNode[],
  visibleNodeIds: Set<string>,
): void {
  for (const child of childrenByParentId.get(parentId) ?? []) {
    if (child.kind === 'composite' && expandedNodeIds.has(child.id)) {
      addVisibleChildren(
        child.id,
        childrenByParentId,
        expandedNodeIds,
        visibleNodes,
        visibleNodeIds,
      )
    } else {
      visibleNodes.push(child)
      visibleNodeIds.add(child.id)
    }
  }
}

function findVisibleRepresentative(
  endpointId: string,
  currentScopeId: string,
  nodesById: Map<string, GraphNode>,
  visibleNodeIds: ReadonlySet<string>,
): string | undefined {
  let candidate = nodesById.get(endpointId)

  while (candidate && candidate.id !== currentScopeId) {
    if (visibleNodeIds.has(candidate.id)) {
      return candidate.id
    }

    candidate =
      candidate.parentId === null
        ? undefined
        : nodesById.get(candidate.parentId)
  }

  return undefined
}

function compareVisibleEdges(
  left: MutableVisibleGraphEdge,
  right: MutableVisibleGraphEdge,
): number {
  return (
    compareStrings(left.source, right.source) ||
    compareStrings(left.target, right.target)
  )
}

function compareStrings(left: string, right: string): number {
  if (left < right) {
    return -1
  }

  if (left > right) {
    return 1
  }

  return 0
}
