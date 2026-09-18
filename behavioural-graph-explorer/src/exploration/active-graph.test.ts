import { describe, expect, it } from 'vitest'
import {
  activateGraphDocument,
  applyExplorationTransition,
  redoLastViewChange,
  type ActiveGraph,
  undoLastViewChange,
} from './active-graph'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import type { GraphDocument } from '../graph/graph-document'
import {
  clickIntoComposite,
  expandComposite,
  selectEdge,
  selectNode,
} from './explore-graph'
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
      boldedEdgeIds: new Set(),
      selectedNodeIds: new Set(),
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(activeGraph.viewHistory).toEqual([])
    expect(activeGraph.redoHistory).toEqual([])
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
    expect(undoneGraph.exploration.selectedNodeIds).toEqual(new Set())
    expect(undoneGraph.exploration.selectedEdgeId).toBeNull()
    expect(undoneGraph.exploration.projectionRevision).toBe(2)
    expect(undoneGraph.viewHistory).toEqual([])
    expect(undoneGraph.redoHistory).toHaveLength(1)
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

describe('redoLastViewChange', () => {
  it('restores the view that was undone', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const expandedGraph = applyExplorationTransition(
      initialGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(initialGraph),
        initialGraph.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )
    const undoneGraph = undoLastViewChange(expandedGraph)
    const redoneGraph = redoLastViewChange(undoneGraph)

    expect(nodeIds(redoneGraph)).toEqual(nodeIds(expandedGraph))
    expect(redoneGraph.exploration.expandedNodeIds).toEqual(
      expandedGraph.exploration.expandedNodeIds,
    )
    expect(redoneGraph.viewHistory).toHaveLength(1)
    expect(redoneGraph.redoHistory).toEqual([])
    expect(redoLastViewChange(redoneGraph)).toBe(redoneGraph)
  })

  it('clears redo history when a new view change is made', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const expandedPreparation = applyExplorationTransition(
      initialGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(initialGraph),
        initialGraph.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )
    const undoneGraph = undoLastViewChange(expandedPreparation)
    const expandedExecution = applyExplorationTransition(
      undoneGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(undoneGraph),
        undoneGraph.exploration,
        SAMPLE_NODE_IDS.execution,
      ),
    )

    expect(expandedExecution.redoHistory).toEqual([])
    expect(redoLastViewChange(expandedExecution)).toBe(expandedExecution)
  })
})

describe('selection during view changes', () => {
  it('keeps a selected node that remains visible', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const selectedGraph = applyExplorationTransition(
      initialGraph,
      selectNode(
        initialGraph.exploration,
        project(initialGraph),
        SAMPLE_NODE_IDS.report,
      ),
    )
    const expandedGraph = applyExplorationTransition(
      selectedGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(selectedGraph),
        selectedGraph.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )

    expect(expandedGraph.exploration.selectedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.report]),
    )
    expect(expandedGraph.exploration.boldedEdgeIds).toEqual(
      new Set(['execution->report']),
    )
  })

  it('keeps visible selected nodes and removes hidden selected nodes', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const preparationSelectedGraph = applyExplorationTransition(
      initialGraph,
      selectNode(
        initialGraph.exploration,
        project(initialGraph),
        SAMPLE_NODE_IDS.preparation,
      ),
    )
    const multipleNodesSelected = applyExplorationTransition(
      preparationSelectedGraph,
      selectNode(
        preparationSelectedGraph.exploration,
        project(preparationSelectedGraph),
        SAMPLE_NODE_IDS.report,
      ),
    )
    const expandedGraph = applyExplorationTransition(
      multipleNodesSelected,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(multipleNodesSelected),
        multipleNodesSelected.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )

    expect(expandedGraph.exploration.selectedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.report]),
    )
    expect(expandedGraph.exploration.boldedEdgeIds).toEqual(
      new Set(['execution->report']),
    )
  })

  it('clears a selected node that the view change hides', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const selectedGraph = applyExplorationTransition(
      initialGraph,
      selectNode(
        initialGraph.exploration,
        project(initialGraph),
        SAMPLE_NODE_IDS.preparation,
      ),
    )
    const expandedGraph = applyExplorationTransition(
      selectedGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(selectedGraph),
        selectedGraph.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )

    expect(expandedGraph.exploration.selectedNodeIds).toEqual(new Set())
    expect(expandedGraph.exploration.boldedEdgeIds).toEqual(new Set())
  })

  it('keeps a selected edge that remains visible', () => {
    const initialGraph = activateGraphDocument(SAMPLE_GRAPH_DOCUMENT)
    const stableEdgeId = project(initialGraph).edges.find(
      (edge) =>
        edge.source === SAMPLE_NODE_IDS.execution &&
        edge.target === SAMPLE_NODE_IDS.report,
    )?.id

    if (!stableEdgeId) {
      throw new Error('Expected a stable sample edge')
    }

    const selectedGraph = applyExplorationTransition(
      initialGraph,
      selectEdge(
        initialGraph.exploration,
        project(initialGraph),
        stableEdgeId,
      ),
    )
    const expandedGraph = applyExplorationTransition(
      selectedGraph,
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        project(selectedGraph),
        selectedGraph.exploration,
        SAMPLE_NODE_IDS.preparation,
      ),
    )

    expect(expandedGraph.exploration.selectedEdgeId).toBe(stableEdgeId)
    expect(expandedGraph.exploration.boldedEdgeIds).toEqual(
      new Set([stableEdgeId]),
    )
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
