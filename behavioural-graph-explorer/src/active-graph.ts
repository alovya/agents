import type { GraphDocument } from './graph'
import {
  createInitialExplorationState,
  type ExplorationState,
} from './exploration'

export type ActiveGraph = {
  document: GraphDocument
  exploration: ExplorationState
}

export function activateGraphDocument(document: GraphDocument): ActiveGraph {
  return {
    document,
    exploration: createInitialExplorationState(document),
  }
}
