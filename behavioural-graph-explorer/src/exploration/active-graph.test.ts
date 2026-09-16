import { describe, expect, it } from 'vitest'
import {
  activateGraphDocument,
  applyExplorationTransition,
  type ActiveGraph,
  undoLastViewChange,
} from './active-graph'
import { projectVisibleGraph, type GraphDocument } from '../graph/graph'
import { clickIntoComposite, expandComposite, selectNode } from './exploration'
import {
  SAMPLE_GRAPH_DOCUMENT,
  SAMPLE_NODE_IDS,
} from '../graph/sample-graph'

function project(activeGraph: ActiveGraph) {
  return projectVisibleGraph(
    activeGraph.document,
    activeGraph.exploration.currentScopeId,
    activeGraph.exploration.expandedNodeIds,
  )
}

function nodeIds(activeGraph: ActiveGraph) {
  return project(activeGraph).nodes.map((node) => node.id)
}

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

describe('undoLastViewChange', () => {
  it('restores enclosing scope nodes and edges after a scope change', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const enteredExploration = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialGraph),
      initialGraph.exploration,
      SAMPLE_NODE_IDS.preparation,
    )
    const enteredGraph = applyExplorationTransition(
      initialGraph,
      enteredExploration,
    )
    const undoneGraph = undoLastViewChange(enteredGraph)

    expect(undoneGraph.exploration.currentScopeId).toBe(SAMPLE_NODE_IDS.root)
    expect(undoneGraph.exploration.scopePath).toEqual([SAMPLE_NODE_IDS.root])
    expect(nodeIds(undoneGraph)).toEqual(nodeIds(initialGraph))
    expect(project(undoneGraph).edges).toEqual(project(initialGraph).edges)
    expect(undoneGraph.exploration.projectionRevision).toBe(2)
  })

  it('does not leak expansion from one scope into its sibling', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const preparationExpandedExploration = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialGraph),
      initialGraph.exploration,
      SAMPLE_NODE_IDS.preparation,
    )
    const preparationExpandedGraph = applyExplorationTransition(
      initialGraph,
      preparationExpandedExploration,
    )
    const fullyExpandedExploration = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(preparationExpandedGraph),
      preparationExpandedGraph.exploration,
      SAMPLE_NODE_IDS.preparationChecks,
    )
    const fullyExpandedGraph = applyExplorationTransition(
      preparationExpandedGraph,
      fullyExpandedExploration,
    )
    const executionExploration = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(fullyExpandedGraph),
      fullyExpandedGraph.exploration,
      SAMPLE_NODE_IDS.execution,
    )
    const executionGraph = applyExplorationTransition(
      fullyExpandedGraph,
      executionExploration,
    )

    expect(executionGraph.exploration.expandedNodeIds).toEqual(
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.preparationChecks,
      ]),
    )
    expect(nodeIds(executionGraph)).toEqual([
      SAMPLE_NODE_IDS.runTask,
      SAMPLE_NODE_IDS.recordResult,
    ])
    expect(undoLastViewChange(executionGraph).exploration.currentScopeId).toBe(
      SAMPLE_NODE_IDS.root,
    )
  })

  it('retains expansion IDs after undoing a scope change', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const preparationExpandedExploration = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialGraph),
      initialGraph.exploration,
      SAMPLE_NODE_IDS.preparation,
    )
    const preparationExpandedGraph = applyExplorationTransition(
      initialGraph,
      preparationExpandedExploration,
    )
    const fullyExpandedExploration = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(preparationExpandedGraph),
      preparationExpandedGraph.exploration,
      SAMPLE_NODE_IDS.preparationChecks,
    )
    const fullyExpandedGraph = applyExplorationTransition(
      preparationExpandedGraph,
      fullyExpandedExploration,
    )
    const executionExploration = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(fullyExpandedGraph),
      fullyExpandedGraph.exploration,
      SAMPLE_NODE_IDS.execution,
    )
    const executionGraph = applyExplorationTransition(
      fullyExpandedGraph,
      executionExploration,
    )
    const undoneGraph = undoLastViewChange(executionGraph)

    expect(undoneGraph.exploration.currentScopeId).toBe(SAMPLE_NODE_IDS.root)
    expect(undoneGraph.exploration.scopePath).toEqual([SAMPLE_NODE_IDS.root])
    expect(undoneGraph.exploration.expandedNodeIds).toEqual(
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.preparationChecks,
      ]),
    )
    expect(nodeIds(undoneGraph)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(undoneGraph).edges).toEqual([
      {
        id: 'execution->prepare-input',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['run-to-prepare'],
      },
      {
        id: 'execution->report',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.report,
        underlyingEdgeIds: ['record-to-report'],
      },
      {
        id: 'normalise-input->execution',
        source: SAMPLE_NODE_IDS.normaliseInput,
        target: SAMPLE_NODE_IDS.execution,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'prepare-input->validate-input',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.validateInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
      {
        id: 'validate-input->normalise-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.normaliseInput,
        underlyingEdgeIds: ['validate-to-normalise'],
      },
    ])
  })

  it('restores a directly visible nested scope to the enclosing root view', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const rootExpandedExploration = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialGraph),
      initialGraph.exploration,
      SAMPLE_NODE_IDS.preparation,
    )
    const rootExpandedGraph = applyExplorationTransition(
      initialGraph,
      rootExpandedExploration,
    )
    const nestedExploration = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(rootExpandedGraph),
      rootExpandedGraph.exploration,
      SAMPLE_NODE_IDS.preparationChecks,
    )
    const nestedGraph = applyExplorationTransition(
      rootExpandedGraph,
      nestedExploration,
    )

    expect(nestedGraph.exploration.scopePath).toEqual([
      SAMPLE_NODE_IDS.root,
      SAMPLE_NODE_IDS.preparationChecks,
    ])
    expect(nestedGraph.exploration.currentScopeId).toBe(
      SAMPLE_NODE_IDS.preparationChecks,
    )

    const undoneGraph = undoLastViewChange(nestedGraph)

    expect(undoneGraph.exploration.scopePath).toEqual([SAMPLE_NODE_IDS.root])
    expect(undoneGraph.exploration.currentScopeId).toBe(SAMPLE_NODE_IDS.root)
    expect(nodeIds(undoneGraph)).toEqual(nodeIds(rootExpandedGraph))
    expect(project(undoneGraph).edges).toEqual(project(rootExpandedGraph).edges)
  })
})
