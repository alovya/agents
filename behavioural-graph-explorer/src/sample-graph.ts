import type { GraphDocument } from './graph'

export const SAMPLE_NODE_IDS = {
  root: 'root',
  preparation: 'preparation',
  preparationInput: 'prepare-input',
  preparationChecks: 'preparation-checks',
  validateInput: 'validate-input',
  normaliseInput: 'normalise-input',
  execution: 'execution',
  runTask: 'run-task',
  recordResult: 'record-result',
  report: 'report',
} as const

export const SAMPLE_GRAPH_DOCUMENT: GraphDocument = {
  rootId: SAMPLE_NODE_IDS.root,
  nodes: [
    {
      id: SAMPLE_NODE_IDS.root,
      label: 'Behavioural workflow',
      kind: 'composite',
      parentId: null,
    },
    {
      id: SAMPLE_NODE_IDS.preparation,
      label: 'Preparation',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.root,
    },
    {
      id: SAMPLE_NODE_IDS.preparationInput,
      label: 'Prepare input',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparation,
    },
    {
      id: SAMPLE_NODE_IDS.preparationChecks,
      label: 'Preparation checks',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.preparation,
    },
    {
      id: SAMPLE_NODE_IDS.validateInput,
      label: 'Validate input',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparationChecks,
    },
    {
      id: SAMPLE_NODE_IDS.normaliseInput,
      label: 'Normalise input',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparationChecks,
    },
    {
      id: SAMPLE_NODE_IDS.execution,
      label: 'Execution',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.root,
    },
    {
      id: SAMPLE_NODE_IDS.runTask,
      label: 'Run task',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.execution,
    },
    {
      id: SAMPLE_NODE_IDS.recordResult,
      label: 'Record result',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.execution,
    },
    {
      id: SAMPLE_NODE_IDS.report,
      label: 'Report',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.root,
    },
  ],
  edges: [
    {
      id: 'prepare-to-run',
      from: SAMPLE_NODE_IDS.preparationInput,
      to: SAMPLE_NODE_IDS.runTask,
    },
    {
      id: 'record-to-report',
      from: SAMPLE_NODE_IDS.recordResult,
      to: SAMPLE_NODE_IDS.report,
    },
    {
      id: 'run-to-prepare',
      from: SAMPLE_NODE_IDS.runTask,
      to: SAMPLE_NODE_IDS.preparationInput,
    },
    {
      id: 'validate-preparation',
      from: SAMPLE_NODE_IDS.validateInput,
      to: SAMPLE_NODE_IDS.preparationInput,
    },
    {
      id: 'run-to-record',
      from: SAMPLE_NODE_IDS.runTask,
      to: SAMPLE_NODE_IDS.recordResult,
    },
    {
      id: 'record-to-run',
      from: SAMPLE_NODE_IDS.recordResult,
      to: SAMPLE_NODE_IDS.runTask,
    },
  ],
}
