import { describe, expect, it } from 'vitest'
import {
  SAMPLE_GRAPH_DOCUMENT,
  SAMPLE_NODE_IDS,
} from './sample-graph'
import { projectVisibleGraph } from './project-visible-graph'

describe('SAMPLE_GRAPH_DOCUMENT', () => {
  it('has the collapsed root projection in direct-child order', () => {
    const graph = projectVisibleGraph(SAMPLE_GRAPH_DOCUMENT, 'root', new Set())

    expect(graph.nodes.map((node) => node.id)).toEqual([
      SAMPLE_NODE_IDS.preparation,
      SAMPLE_NODE_IDS.execution,
      SAMPLE_NODE_IDS.report,
    ])
    expect(graph.edges).toEqual([
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

  it('shows preparation internals without leaking cross-boundary edges', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      SAMPLE_NODE_IDS.preparation,
      new Set(),
    )

    expect(graph.nodes.map((node) => node.id)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.preparationChecks,
    ])
    expect(graph.edges).toEqual([
      {
        id: 'prepare-input->preparation-checks',
        source: SAMPLE_NODE_IDS.preparationInput,
        target: SAMPLE_NODE_IDS.preparationChecks,
        underlyingEdgeIds: ['validate-preparation'],
      },
    ])
  })

  it('shows the canonical execution-leaf cycle when fully expanded', () => {
    const graph = projectVisibleGraph(
      SAMPLE_GRAPH_DOCUMENT,
      'root',
      new Set([
        SAMPLE_NODE_IDS.preparation,
        SAMPLE_NODE_IDS.preparationChecks,
        SAMPLE_NODE_IDS.execution,
      ]),
    )

    expect(graph.nodes.map((node) => node.id)).toEqual([
      SAMPLE_NODE_IDS.preparationInput,
      SAMPLE_NODE_IDS.validateInput,
      SAMPLE_NODE_IDS.normaliseInput,
      SAMPLE_NODE_IDS.runTask,
      SAMPLE_NODE_IDS.recordResult,
      SAMPLE_NODE_IDS.report,
    ])
    expect(graph.edges).toEqual([
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

    expect(graph.edges).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          id: 'run-task->record-result',
          source: SAMPLE_NODE_IDS.runTask,
          target: SAMPLE_NODE_IDS.recordResult,
        }),
        expect.objectContaining({
          id: 'record-result->run-task',
          source: SAMPLE_NODE_IDS.recordResult,
          target: SAMPLE_NODE_IDS.runTask,
        }),
      ]),
    )
  })
})
