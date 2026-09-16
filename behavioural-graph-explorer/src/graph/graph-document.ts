export type NodeKind = 'leaf' | 'composite'
export type GraphMetadata = Readonly<Record<string, unknown>>

export type GraphNode = {
  id: string
  label: string
  kind: NodeKind
  parentId: string | null
  metadata?: GraphMetadata
}

export type GraphEdge = {
  id: string
  from: string
  to: string
  label?: string
}

export type GraphDocument = {
  rootId: string
  nodes: readonly GraphNode[]
  edges: readonly GraphEdge[]
}

export type VisibleGraphEdge = {
  id: string
  source: string
  target: string
  underlyingEdgeIds: readonly string[]
}

export type VisibleGraph = {
  nodes: readonly GraphNode[]
  edges: readonly VisibleGraphEdge[]
}

export type ExpansionState = ReadonlySet<string>
