import { describe, expect, it } from 'vitest'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import {
  canCollapseOneLevel,
  clearSelectedNodesAndArrows,
  clearSelection,
  collapseAllComposites,
  collapseOneVisibleLevel,
  clickIntoComposite,
  collapseOneLevel,
  createInitialExplorationState,
  expandAllComposites,
  expandComposite,
  expandVisibleComposites,
  findConnectedEdgeIds,
  selectEdge,
  selectNode,
} from './explore-graph'
import {
  SAMPLE_GRAPH_DOCUMENT,
  SAMPLE_NODE_IDS,
} from '../graph/sample-graph'

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
      boldedEdgeIds: new Set(),
      selectedNodeIds: new Set(),
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
        id: 'preparation-checks->execution',
        source: SAMPLE_NODE_IDS.preparationChecks,
        target: SAMPLE_NODE_IDS.execution,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'prepare-input->preparation-checks',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.preparationChecks,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])
  })

  it('collapses a visible node and its siblings into their parent composite', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const expandedState = expandComposite(
      SAMPLE_GRAPH_DOCUMENT,
      project(initialState),
      initialState,
      SAMPLE_NODE_IDS.preparation,
    )
    const expandedGraph = project(expandedState)

    expect(canCollapseOneLevel(
      SAMPLE_GRAPH_DOCUMENT,
      expandedGraph,
      expandedState,
      SAMPLE_NODE_IDS.preparationInput,
    )).toBe(true)

    const collapsedState = collapseOneLevel(
      SAMPLE_GRAPH_DOCUMENT,
      expandedGraph,
      expandedState,
      SAMPLE_NODE_IDS.preparationInput,
    )

    expect(collapsedState.expandedNodeIds).toEqual(new Set())
    expect(nodeIds(collapsedState)).toEqual([
      SAMPLE_NODE_IDS.preparation,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(collapsedState.projectionRevision).toBe(2)
  })

  it('does not collapse a node whose parent is the current scope', () => {
    const state = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const graph = project(state)

    expect(canCollapseOneLevel(
      SAMPLE_GRAPH_DOCUMENT,
      graph,
      state,
      SAMPLE_NODE_IDS.preparation,
    )).toBe(false)
    expect(
      collapseOneLevel(
        SAMPLE_GRAPH_DOCUMENT,
        graph,
        state,
        SAMPLE_NODE_IDS.preparation,
      ),
    ).toBe(state)
  })

  it('collapses every expanded direct child of the current scope by one level', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const expandedState = expandVisibleComposites(
      project(initialState),
      initialState,
    )

    const collapsedState = collapseOneVisibleLevel(
      SAMPLE_GRAPH_DOCUMENT,
      expandedState,
    )

    expect(collapsedState.expandedNodeIds).toEqual(new Set())
    expect(collapsedState.projectionRevision).toBe(2)
    expect(collapseOneVisibleLevel(SAMPLE_GRAPH_DOCUMENT, collapsedState)).toBe(
      collapsedState,
    )
  })

  it('collapses every expanded descendant of the current scope', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const expandedState = expandAllComposites(
      SAMPLE_GRAPH_DOCUMENT,
      initialState,
    )

    const collapsedState = collapseAllComposites(
      SAMPLE_GRAPH_DOCUMENT,
      expandedState,
    )

    expect(collapsedState.expandedNodeIds).toEqual(new Set())
    expect(collapsedState.projectionRevision).toBe(2)
    expect(collapseAllComposites(SAMPLE_GRAPH_DOCUMENT, collapsedState)).toBe(
      collapsedState,
    )
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
    expect(expandedOnce.selectedNodeIds).toEqual(new Set())
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
        id: 'preparation-checks->run-task',
        source: SAMPLE_NODE_IDS.preparationChecks,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'prepare-input->preparation-checks',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.preparationChecks,
        underlyingEdgeIds: ['validate-preparation'],
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
        id: 'normalise-input->run-task',
        source: SAMPLE_NODE_IDS.normaliseInput,
        target: SAMPLE_NODE_IDS.runTask,
        underlyingEdgeIds: ['prepare-to-run'],
      },
      {
        id: 'prepare-input->validate-input',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.validateInput,
        underlyingEdgeIds: ['validate-preparation'],
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
        id: 'validate-input->normalise-input',
        source: SAMPLE_NODE_IDS.validateInput,
        target: SAMPLE_NODE_IDS.normaliseInput,
        underlyingEdgeIds: ['validate-to-normalise'],
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

  it('finds every visible edge connected to a node', () => {
    const state = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const graph = project(state)

    expect(findConnectedEdgeIds(graph, SAMPLE_NODE_IDS.preparation)).toEqual([
      'execution->preparation',
      'preparation->execution',
    ])
    expect(findConnectedEdgeIds(graph, SAMPLE_NODE_IDS.report)).toEqual([
      'execution->report',
    ])
    expect(findConnectedEdgeIds(graph, 'missing-node')).toEqual([])
  })

  it('toggles multiple node selections and keeps edge selection mutually exclusive', () => {
    const initialState = createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT)
    const graph = project(initialState)
    const nodeSelected = selectNode(
      initialState,
      graph,
      SAMPLE_NODE_IDS.preparation,
    )
    const multipleNodesSelected = selectNode(
      nodeSelected,
      graph,
      SAMPLE_NODE_IDS.report,
    )
    const deselected = selectNode(
      multipleNodesSelected,
      graph,
      SAMPLE_NODE_IDS.preparation,
    )
    const edgeSelected = selectEdge(
      multipleNodesSelected,
      graph,
      'execution->preparation',
    )

    expect(nodeSelected).toMatchObject({
      selectedNodeIds: new Set([SAMPLE_NODE_IDS.preparation]),
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(multipleNodesSelected).toMatchObject({
      selectedNodeIds: new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.report,
      ]),
      boldedEdgeIds: new Set([
        'execution->preparation',
        'execution->report',
        'preparation->execution',
      ]),
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(deselected.selectedNodeIds).toEqual(new Set([SAMPLE_NODE_IDS.report]))
    expect(clearSelectedNodesAndArrows(multipleNodesSelected)).toMatchObject({
      selectedNodeIds: new Set(),
      boldedEdgeIds: new Set(),
      selectedEdgeId: null,
    })
    expect(edgeSelected).toMatchObject({
      selectedNodeIds: new Set(),
      selectedEdgeId: 'execution->preparation',
      projectionRevision: 0,
    })
    expect(selectEdge(edgeSelected, graph, 'execution->preparation')).toMatchObject({
      selectedNodeIds: new Set(),
      selectedEdgeId: null,
      projectionRevision: 0,
    })
    expect(clearSelection(edgeSelected)).toMatchObject({
      selectedNodeIds: new Set(),
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
  })
})
