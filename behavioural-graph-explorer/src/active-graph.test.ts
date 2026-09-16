import { describe, expect, it } from 'vitest'
import { activateGraphDocument } from './active-graph'
import type { GraphDocument } from './graph'

describe('activateGraphDocument', () => {
  it('starts a different document at its root with empty exploration state', () => {
    const document: GraphDocument = {
      rootId: 'imported-root',
      nodes: [
        {
          id: 'imported-root',
          label: 'Imported graph',
          kind: 'composite',
          parentId: null,
        },
        {
          id: 'first',
          label: 'First',
          kind: 'leaf',
          parentId: 'imported-root',
        },
        {
          id: 'second',
          label: 'Second',
          kind: 'leaf',
          parentId: 'imported-root',
        },
      ],
      edges: [],
    }

    const activeGraph = activateGraphDocument(document)

    expect(activeGraph.document).toBe(document)
    expect(activeGraph.exploration).toEqual({
      currentScopeId: 'imported-root',
      scopePath: ['imported-root'],
      expandedNodeIds: new Set(),
      selectedNodeId: null,
      selectedEdgeId: null,
      projectionRevision: 0,
    })
  })
})
