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
      label: 'Behavioural Graph Explorer',
      kind: 'composite',
      parentId: null,
    },
    {
      id: SAMPLE_NODE_IDS.preparation,
      label: 'Build visible graph',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.root,
    },
    {
      id: SAMPLE_NODE_IDS.preparationInput,
      label: 'Receive complete graph',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparation,
    },
    {
      id: SAMPLE_NODE_IDS.preparationChecks,
      label: 'Project visible graph',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.preparation,
    },
    {
      id: SAMPLE_NODE_IDS.validateInput,
      label: 'Resolve visible representatives',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparationChecks,
    },
    {
      id: SAMPLE_NODE_IDS.normaliseInput,
      label: 'Group summary edges',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.preparationChecks,
    },
    {
      id: SAMPLE_NODE_IDS.execution,
      label: 'Explore current view',
      kind: 'composite',
      parentId: SAMPLE_NODE_IDS.root,
    },
    {
      id: SAMPLE_NODE_IDS.runTask,
      label: 'Select node or edge',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.execution,
    },
    {
      id: SAMPLE_NODE_IDS.recordResult,
      label: 'Apply exploration action',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.execution,
    },
    {
      id: SAMPLE_NODE_IDS.report,
      label: 'Render current view',
      kind: 'leaf',
      parentId: SAMPLE_NODE_IDS.root,
    },
  ],
  edges: [
    {
      id: 'prepare-to-run',
      from: SAMPLE_NODE_IDS.normaliseInput,
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
      from: SAMPLE_NODE_IDS.preparationInput,
      to: SAMPLE_NODE_IDS.validateInput,
    },
    {
      id: 'validate-to-normalise',
      from: SAMPLE_NODE_IDS.validateInput,
      to: SAMPLE_NODE_IDS.normaliseInput,
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
