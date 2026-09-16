import { describe, expect, it } from 'vitest'
import type { GraphDocument } from './graph-document'
import { projectVisibleGraph } from './project-visible-graph'

type ExpectedEdge = {
  id: string
  source: string
  target: string
  underlyingEdgeIds: string[]
}

const compactFixture: GraphDocument = {
  rootId: 'root',
  nodes: [
    { id: 'root', label: 'Root', kind: 'composite', parentId: null },
    { id: 'A', label: 'A', kind: 'composite', parentId: 'root' },
    { id: 'D', label: 'D', kind: 'leaf', parentId: 'A' },
    { id: 'E', label: 'E', kind: 'composite', parentId: 'A' },
    { id: 'H', label: 'H', kind: 'leaf', parentId: 'E' },
    { id: 'I', label: 'I', kind: 'leaf', parentId: 'E' },
    { id: 'B', label: 'B', kind: 'composite', parentId: 'root' },
    { id: 'F', label: 'F', kind: 'leaf', parentId: 'B' },
    { id: 'G', label: 'G', kind: 'leaf', parentId: 'B' },
    { id: 'C', label: 'C', kind: 'leaf', parentId: 'root' },
  ],
  edges: [
    { id: 'd-f', from: 'D', to: 'F' },
    { id: 'h-g', from: 'H', to: 'G' },
    { id: 'f-c', from: 'F', to: 'C' },
    { id: 'g-c', from: 'G', to: 'C' },
    { id: 'g-d', from: 'G', to: 'D' },
    { id: 'h-d', from: 'H', to: 'D' },
  ],
}

const expandedFixture = new Set(['A', 'E', 'B'])

function edge(
  id: string,
  source: string,
  target: string,
  underlyingEdgeIds: string[],
): ExpectedEdge {
  return { id, source, target, underlyingEdgeIds }
}

describe('projectVisibleGraph', () => {
  it('projects the collapsed root with opposite summary directions and a collapsed cycle', () => {
    const graph = projectVisibleGraph(compactFixture, 'root', new Set())

    expect(graph.nodes.map((node) => node.id)).toEqual(['A', 'B', 'C'])
    expect(graph.edges).toEqual([
      edge('A->B', 'A', 'B', ['d-f', 'h-g']),
      edge('B->A', 'B', 'A', ['g-d']),
      edge('B->C', 'B', 'C', ['f-c', 'g-c']),
    ])
  })

  it('omits cross-boundary edges inside a closed scope', () => {
    const graph = projectVisibleGraph(compactFixture, 'A', new Set())

    expect(graph.nodes.map((node) => node.id)).toEqual(['D', 'E'])
    expect(graph.edges).toEqual([edge('E->D', 'E', 'D', ['h-d'])])
  })

  it('expands a composite in place without opening newly revealed composites', () => {
    const graph = projectVisibleGraph(compactFixture, 'root', new Set(['A']))

    expect(graph.nodes.map((node) => node.id)).toEqual(['D', 'E', 'B', 'C'])
    expect(graph.edges).toEqual([
      edge('B->C', 'B', 'C', ['f-c', 'g-c']),
      edge('B->D', 'B', 'D', ['g-d']),
      edge('D->B', 'D', 'B', ['d-f']),
      edge('E->B', 'E', 'B', ['h-g']),
      edge('E->D', 'E', 'D', ['h-d']),
    ])
  })

  it('shows every canonical edge when all compact composites are expanded', () => {
    const graph = projectVisibleGraph(compactFixture, 'root', expandedFixture)

    expect(graph.nodes.map((node) => node.id)).toEqual([
      'D',
      'H',
      'I',
      'F',
      'G',
      'C',
    ])
    expect(graph.edges).toEqual([
      edge('D->F', 'D', 'F', ['d-f']),
      edge('F->C', 'F', 'C', ['f-c']),
      edge('G->C', 'G', 'C', ['g-c']),
      edge('G->D', 'G', 'D', ['g-d']),
      edge('H->D', 'H', 'D', ['h-d']),
      edge('H->G', 'H', 'G', ['h-g']),
    ])
  })

  it('does not mutate the canonical document', () => {
    const before = JSON.stringify(compactFixture)

    projectVisibleGraph(compactFixture, 'root', new Set(['A', 'E']))

    expect(JSON.stringify(compactFixture)).toBe(before)
  })

  it('fails clearly for an unknown scope', () => {
    expect(() => projectVisibleGraph(compactFixture, 'missing', new Set())).toThrow(
      'Unknown scope ID: missing',
    )
  })
})
