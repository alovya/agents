import { describe, expect, it } from 'vitest'
import { projectVisibleGraph } from './graph'
import {
  clearSelection,
  clickIntoComposite,
  createInitialExplorationState,
  expandAllComposites,
  expandComposite,
  expandVisibleComposites,
  returnToEnclosingScope,
  selectEdge,
  selectNode,
} from './exploration'
import {
  SAMPLE_GRAPH_DOCUMENT,
  SAMPLE_NODE_IDS,
} from './sample-graph'

function project(
  state: ReturnType<typeof createInitialExplorationState>,
) {
  return projectVisibleGraph(
    SAMPLE_GRAPH_DOCUMENT,
    state.currentScopeId,
    state.expandedNodeIds,
  )
}

function nodeIds(state: ReturnType<typeof createInitialExplorationState>) {
  return project(state).nodes.map((node) => node.id)
}

describe('exploration state', () => {
  it('starts at the root with an empty projection state', () => {
    const state = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)

    expect(state).toEqual({
      currentScopeId: SAMPLE_NODE_IDS.root,
      scopePath: [SAMPLE_NODE_IDS.root],
      expandedNodeIds: new Set(),
      selectedNodeId: null,
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(nodeIds(state)).toEqual([
      SAMPLE_NODE_IDS.preparation,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(state).edges).toEqual([
      {
        id: 'execution->preparation',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.preparation,
        underlyingEdgeIds: ['run-to-prepare'],
      },
      {
        id: 'execution->report',
        source: SAMPLE_NODE_IDS.execution,
        target: SAMPLE_NODE_IDS.report,
        underlyingEdgeIds: ['record-to-report'],
      },
      {
        id: 'preparation->execution',
        source: SAMPLE_NODE_IDS.preparation,
        target: SAMPLE_NODE_IDS.execution,
        underlyingEdgeIds: ['prepare-to-run'],
      },
    ])
  })

  it('expands one visible composite and reveals only its immediate children', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const initialGraph = project(initialState)
    const expandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      initialGraph,
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )

    expect(expandedState.projectionRevision).toBe(1)
    expect(expandedState.expandedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.preparation]),
    )
    expect(nodeIds(expandedState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.preparationChecks,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(expandedState).edges).toEqual([
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
        id: 'preparation-checks->prepare-input',
        source: SAMPLE_NODE_IDS.preparationChecks,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
      {
        id: 'prepare-input->execution',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.execution,
        underlyingEdgeIds: ['prepare-to-run'],
      },
    ])
  })

  it('expands every visible composite for one level only', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const selectedState = selectNode(
      initialState,
      project(initialState),
      SAMPLE_NODE_IDS.preparation,
    )
    const expandedOnce = expandVisibleComposites(
      project(selectedState),
      selectedState,
    )

    expect(expandedOnce.expandedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.preparation, SAMPLE_NODE_IDS.execution]),
    )
    expect(expandedOnce.projectionRevision).toBe(1)
    expect(expandedOnce.selectedNodeId).toBeNull()
    expect(expandedOnce.selectedEdgeId).toBeNull()
    expect(nodeIds(expandedOnce)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.preparationChecks,
      SAMPLE_NODE_IDS.runTask,
      SAMPLE_NODE_IDS.recordResult,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(expandedOnce).edges).toEqual([
      {
        id: 'preparation-checks->prepare-input',
        source: SAMPLE_NODE_IDS.preparationChecks,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
      {
        id: 'prepare-input->run-task',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'record-result->report',
        source: SAMPLE_NODE_IDS.recordResult,
        target: SAMPLE_NODE_IDS.report,
        underlyingEdgeIds: ['record-to-report'],
      },
      {
        id: 'record-result->run-task',
        source: SAMPLE_NODE_IDS.recordResult,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['record-to-run'],
      },
      {
        id: 'run-task->prepare-input',
        source: SAMPLE_NODE_IDS.runTask,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['run-to-prepare'],
      },
      {
        id: 'run-task->record-result',
        source: SAMPLE_NODE_IDS.runTask,
        target: SAMPLE_NODE_IDS.recordResult,
        underlyingEdgeIds: ['run-to-record'],
      },
    ])

    const expandedTwice = expandVisibleComposites(
      project(expandedOnce),
      expandedOnce,
    )

    expect(expandedTwice.expandedNodeIds).toEqual(
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.execution,
        SAMPLE_NODE_IDS.preparationChecks,
      ]),
    )
    expect(expandedTwice.projectionRevision).toBe(2)
    expect(nodeIds(expandedTwice)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
      SAMPLE_NODE_IDS.runTask,
      SAMPLE_NODE_IDS.recordResult,
      SAMPLE_NODE_IDS.report,
    ])
  })

  it('expands every composite descendant from the root', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const expandedState = expandAllComposites(
      SAMPLE_GRAPH_DOCUMENT,
      initialState,
    )

    expect(expandedState.expandedNodeIds).toEqual(
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.preparationChecks,
        SAMPLE_NODE_IDS.execution,
      ]),
    )
    expect(expandedState.projectionRevision).toBe(1)
    expect(nodeIds(expandedState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
      SAMPLE_NODE_IDS.runTask,
      SAMPLE_NODE_IDS.recordResult,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(expandedState).edges).toEqual([
      {
        id: 'prepare-input->run-task',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'record-result->report',
        source: SAMPLE_NODE_IDS.recordResult,
        target: SAMPLE_NODE_IDS.report,
        underlyingEdgeIds: ['record-to-report'],
      },
      {
        id: 'record-result->run-task',
        source: SAMPLE_NODE_IDS.recordResult,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['record-to-run'],
      },
      {
        id: 'run-task->prepare-input',
        source: SAMPLE_NODE_IDS.runTask,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['run-to-prepare'],
      },
      {
        id: 'run-task->record-result',
        source: SAMPLE_NODE_IDS.runTask,
        target: SAMPLE_NODE_IDS.recordResult,
        underlyingEdgeIds: ['run-to-record'],
      },
      {
        id: 'validate-input->prepare-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])

    expect(project(expandedState).edges).toEqual(
      expect.arrayContaining([
        {
          id: 'run-task->record-result',
          source: SAMPLE_NODE_IDS.runTask,
          target: SAMPLE_NODE_IDS.recordResult,
          underlyingEdgeIds: ['run-to-record'],
        },
        {
          id: 'record-result->run-task',
          source: SAMPLE_NODE_IDS.recordResult,
          target: SAMPLE_NODE_IDS.runTask,
          underlyingEdgeIds: ['record-to-run'],
        },
      ]),
    )
  })

  it('expands only preparation descendants inside the preparation scope', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const preparationState = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialState),
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )
    const expandedState = expandAllComposites(
      SAMPLE_GRAPH_DOCUMENT,
      preparationState,
    )

    expect(expandedState.scopePath).toEqual([
      SAMPLE_NODE_IDS.root,
      SAMPLE_NODE_IDS.preparation,
    ])
    expect(expandedState.expandedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.preparationChecks]),
    )
    expect(nodeIds(expandedState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
    ])
    expect(project(expandedState).edges).toEqual([
      {
        id: 'validate-input->prepare-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])
    expect(expandedState.projectionRevision).toBe(2)
  })

  it('keeps bulk expansion no-ops identical and preserves their revision', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const fullyExpandedState = expandAllComposites(
      SAMPLE_GRAPH_DOCUMENT,
      initialState,
    )

    expect(
      expandVisibleComposites(project(fullyExpandedState), fullyExpandedState),
    ).toBe(fullyExpandedState)
    expect(expandAllComposites(SAMPLE_GRAPH_DOCUMENT, fullyExpandedState)).toBe(
      fullyExpandedState,
    )
    expect(fullyExpandedState.projectionRevision).toBe(1)
  })

  it('enters preparation, keeps its boundary closed, and returns to the exact root view', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const initialGraph = project(initialState)
    const enteredState = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      initialGraph,
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )

    expect(enteredState.scopePath).toEqual([
      SAMPLE_NODE_IDS.root,
      SAMPLE_NODE_IDS.preparation,
    ])
    expect(nodeIds(enteredState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.preparationChecks,
    ])
    expect(project(enteredState).edges).toEqual([
      {
        id: 'preparation-checks->prepare-input',
        source: SAMPLE_NODE_IDS.preparationChecks,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])

    const returnedState = returnToEnclosingScope(enteredState)

    expect(returnedState.currentScopeId).toBe(SAMPLE_NODE_IDS.root)
    expect(returnedState.scopePath).toEqual([SAMPLE_NODE_IDS.root])
    expect(nodeIds(returnedState)).toEqual(nodeIds(initialState))
    expect(project(returnedState).edges).toEqual(project(initialState).edges)
    expect(returnedState.projectionRevision).toBe(2)
  })

  it('does not leak preparation expansion into execution', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const enteredState = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialState),
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )
    const expandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(enteredState),
      enteredState,
      SAMPLE_NODE_IDS.preparationChecks,
    )

    expect(expandedState.expandedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.preparationChecks]),
    )
    expect(nodeIds(expandedState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
    ])
    expect(project(expandedState).edges).toEqual([
      {
        id: 'validate-input->prepare-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])

    const rootState = returnToEnclosingScope(expandedState)

    expect(nodeIds(rootState)).toEqual([
      SAMPLE_NODE_IDS.preparation,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(rootState.expandedNodeIds).toEqual(
      new Set([SAMPLE_NODE_IDS.preparationChecks]),
    )
  })

  it('can enter a directly visible nested composite and back out to root', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const expandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialState),
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )
    const nestedState = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(expandedState),
      expandedState,
      SAMPLE_NODE_IDS.preparationChecks,
    )

    expect(nestedState.scopePath).toEqual([
      SAMPLE_NODE_IDS.root,
      SAMPLE_NODE_IDS.preparationChecks,
    ])
    expect(nestedState.currentScopeId).toBe(
      SAMPLE_NODE_IDS.preparationChecks,
    )

    const rootState = returnToEnclosingScope(nestedState)

    expect(rootState.scopePath).toEqual([SAMPLE_NODE_IDS.root])
    expect(rootState.currentScopeId).toBe(SAMPLE_NODE_IDS.root)
    expect(nodeIds(rootState)).toEqual(nodeIds(expandedState))
    expect(project(rootState).edges).toEqual(project(expandedState).edges)
  })

  it('retains expansion IDs while navigating between scopes', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const rootExpandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialState),
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )
    const enteredState = clickIntoComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(rootExpandedState),
      rootExpandedState,
      SAMPLE_NODE_IDS.preparation,
    )
    const preparationExpandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(enteredState),
      enteredState,
      SAMPLE_NODE_IDS.preparationChecks,
    )
    const returnedState = returnToEnclosingScope(preparationExpandedState)

    expect(returnedState.expandedNodeIds).toEqual(
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.preparationChecks,
      ]),
    )
    expect(nodeIds(returnedState)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(project(returnedState).edges).toEqual([
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
        id: 'prepare-input->execution',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.execution,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'validate-input->prepare-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.preparationInput,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])
  })

  it('keeps node and edge selection mutually exclusive without changing the revision', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const graph = project(initialState)
    const nodeSelected = selectNode(
      initialState,
      graph,
      SAMPLE_NODE_IDS.preparation,
    )
    const edgeSelected = selectEdge(
      nodeSelected,
      graph,
      'execution->preparation',
    )

    expect(nodeSelected).toMatchObject({
      selectedNodeId: SAMPLE_NODE_IDS.preparation,
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(edgeSelected).toMatchObject({
      selectedNodeId: null,
      selectedEdgeId: 'execution->preparation',
      projectionRevision: 0,
    })
    expect(clearSelection(edgeSelected)).toMatchObject({
      selectedNodeId: null,
      selectedEdgeId: null,
      projectionRevision: 0,
    })
  })

  it('returns the identical state for every invalid action and root back action', () => {
    const state = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const graph = project(state)

    expect(selectNode(state, graph, SAMPLE_NODE_IDS.validateInput)).toBe(state)
    expect(selectNode(state, graph, 'missing-node')).toBe(state)
    expect(selectEdge(state, graph, 'missing-edge')).toBe(state)
    expect(
      clickIntoComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.report,
      ),
    ).toBe(state)
    expect(
      clickIntoComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.validateInput,
      ),
    ).toBe(state)
    expect(
      clickIntoComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.preparationChecks,
      ),
    ).toBe(state)
    expect(
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.report,
      ),
    ).toBe(state)
    expect(
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.validateInput,
      ),
    ).toBe(state)
    expect(
      expandComposite(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.preparationChecks,
      ),
    ).toBe(state)
    expect(returnToEnclosingScope(state)).toBe(state)
  })
})
