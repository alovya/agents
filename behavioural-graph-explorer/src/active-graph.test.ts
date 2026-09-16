import { describe, expect, it } from 'vitest'
import {
  activateGraphDocument,
  applyExplorationTransition,
  undoLastViewChange,
} from './active-graph'
import { projectVisibleGraph, type GraphDocument } from './graph'
import { expandComposite, selectNode } from './exploration'

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
    expect(activeGraph.viewHistory).toEqual([])
  })

  it('undoes projection-changing view transitions without recording selection', () => {
    const document: GraphDocument = {
      rootId: 'root',
      nodes: [
        {
          id: 'root',
          label: 'Root',
          kind: 'composite',
          parentId: null,
        },
        {
          id: 'scope',
          label: 'Scope',
          kind: 'composite',
          parentId: 'root',
        },
        {
          id: 'first',
          label: 'First',
          kind: 'leaf',
          parentId: 'scope',
        },
        {
          id: 'second',
          label: 'Second',
          kind: 'leaf',
          parentId: 'scope',
        },
      ],
      edges: [],
    }
    const activeGraph = activateGraphDocument(document)
    const initialView = projectVisibleGraph(
      document,
      activeGraph.exploration.currentScopeId,
      activeGraph.exploration.expandedNodeIds,
    )
    const expandedExploration = expandComposite(
      document,
      initialView,
      activeGraph.exploration,
      'scope',
    )
    const expandedGraph = applyExplorationTransition(
      activeGraph,
      expandedExploration,
    )

    expect(expandedGraph.viewHistory).toHaveLength(1)
    expect(
      applyExplorationTransition(
        expandedGraph,
        selectNode(
          expandedGraph.exploration,
          projectVisibleGraph(
            document,
            expandedGraph.exploration.currentScopeId,
            expandedGraph.exploration.expandedNodeIds,
          ),
          'first',
        ),
      ).viewHistory,
    ).toHaveLength(1)

    const undoneGraph = undoLastViewChange(expandedGraph)

    expect(undoneGraph.exploration.currentScopeId).toBe('root')
    expect(undoneGraph.exploration.scopePath).toEqual(['root'])
    expect(undoneGraph.exploration.expandedNodeIds).toEqual(new Set())
    expect(undoneGraph.exploration.selectedNodeId).toBeNull()
    expect(undoneGraph.exploration.selectedEdgeId).toBeNull()
    expect(undoneGraph.exploration.projectionRevision).toBe(2)
    expect(undoneGraph.viewHistory).toEqual([])
    expect(
      projectVisibleGraph(
        document,
        undoneGraph.exploration.currentScopeId,
        undoneGraph.exploration.expandedNodeIds,
      ).nodes.map((node) => node.id),
    ).toEqual(['scope'])
    expect(undoLastViewChange(undoneGraph)).toBe(undoneGraph)
  })
})
