import {
  activateGraphDocument,
  type ActiveGraph,
} from '../exploration/active-graph'
import {
  GraphDocumentError,
  parseGraphDocumentText,
} from '../graph/graph-document-json'
import { SAMPLE_GRAPH_DOCUMENT } from '../graph/sample-graph'

export type InitialGraphView = {
  activeGraph: ActiveGraph
  graphJsonSource: string
  importError: string | null
}

export function createInitialGraphView(
  inlineGraphSource: string | null,
): InitialGraphView {
  if (inlineGraphSource === null) {
    return createSampleGraphView(JSON.stringify(SAMPLE_GRAPH_DOCUMENT, null, 2), null)
  }

  try {
    return {
      activeGraph: activateGraphDocument(
        parseGraphDocumentText(inlineGraphSource),
      ),
      graphJsonSource: inlineGraphSource,
      importError: null,
    }
  } catch (error) {
    if (error instanceof GraphDocumentError) {
      return createSampleGraphView(inlineGraphSource, error.message)
    }

    throw error
  }
}

export async function fetchGraphFileSource(
  graphFileRoute: string,
): Promise<string> {
  const response = await globalThis.fetch(graphFileRoute, {
    cache: 'no-store',
  })

  if (!response.ok) {
    throw new Error(`Could not load graph JSON file (${response.status}).`)
  }

  return response.text()
}

export function readGraphFileRouteFromLocation(): string | null {
  return new URLSearchParams(window.location.search).get('graphFile')
}

function createSampleGraphView(
  graphJsonSource: string,
  importError: string | null,
): InitialGraphView {
  return {
    activeGraph: activateGraphDocument(SAMPLE_GRAPH_DOCUMENT),
    graphJsonSource,
    importError,
  }
}
