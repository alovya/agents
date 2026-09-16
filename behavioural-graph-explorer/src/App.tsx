import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
} from '@xyflow/react'
import type { Node, NodeProps } from '@xyflow/react'
import { projectVisibleGraph, type VisibleGraph } from './graph'
import {
  activateGraphDocument,
  applyExplorationTransition,
  type ActiveGraph,
  undoLastViewChange,
} from './active-graph'
import {
  DagreLayoutEngine,
  type LayoutResult,
} from './dagre-layout'
import {
  clearSelection,
  clickIntoComposite,
  expandAllComposites,
  expandComposite,
  expandVisibleComposites,
  returnToEnclosingScope,
  selectEdge,
  selectNode,
} from './exploration'
import {
  convertToReactFlow,
  type GraphFlowNodeData,
} from './react-flow-adapter'
import {
  canRenderLayoutForGraph,
  createLatestLayoutRunner,
  type ApplyLatestLayout,
} from './latest-layout'
import { GraphDocumentError, parseGraphDocumentText } from './graph-document-json'
import { GraphImport } from './graph-import'
import { SAMPLE_GRAPH_DOCUMENT } from './sample-graph'

import './App.css'

const graphNodeTypes = {
  graph: GraphNodeCard,
}

function App() {
  const [activeGraph, setActiveGraph] = useState<ActiveGraph>(() =>
    activateGraphDocument(SAMPLE_GRAPH_DOCUMENT),
  )
  const [graphJsonSource, setGraphJsonSource] = useState(() =>
    JSON.stringify(SAMPLE_GRAPH_DOCUMENT, null, 2),
  )
  const [importError, setImportError] = useState<string | null>(null)
  const visibleGraph = useMemo(
    () =>
      projectVisibleGraph(
        activeGraph.document,
        activeGraph.exploration.currentScopeId,
        activeGraph.exploration.expandedNodeIds,
      ),
    [
      activeGraph.document,
      activeGraph.exploration.currentScopeId,
      activeGraph.exploration.expandedNodeIds,
    ],
  )
  const explorationState = activeGraph.exploration
  const [laidOutGraph, setLaidOutGraph] = useState<{
    graph: VisibleGraph
    layout: LayoutResult
  } | null>(null)
  const layoutRunnerRef = useRef<ApplyLatestLayout | null>(null)

  if (layoutRunnerRef.current === null) {
    layoutRunnerRef.current = createLatestLayoutRunner(
      new DagreLayoutEngine(),
      (graph, layout) => setLaidOutGraph({ graph, layout }),
    )
  }

  const loadGraphDocumentSource = useCallback((source: string) => {
    try {
      const document = parseGraphDocumentText(source)
      setActiveGraph(activateGraphDocument(document))
      setLaidOutGraph(null)
      setImportError(null)
    } catch (error) {
      if (error instanceof GraphDocumentError) {
        setImportError(error.message)
        return
      }

      throw error
    }
  }, [])
  const handleLoadText = useCallback(() => {
    loadGraphDocumentSource(graphJsonSource)
  }, [graphJsonSource, loadGraphDocumentSource])
  const handleChooseFile = useCallback(
    async (file: File) => {
      let source: string

      try {
        source = await file.text()
      } catch {
        setImportError('Could not read graph JSON file.')
        return
      }

      setGraphJsonSource(source)
      loadGraphDocumentSource(source)
    },
    [loadGraphDocumentSource],
  )
  const handleClickInto = useCallback(
    (nodeId: string) => {
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          clickIntoComposite(
            activeGraph.document,
            visibleGraph,
            graph.exploration,
            nodeId,
          ),
        ),
      )
    },
    [activeGraph.document, visibleGraph],
  )
  const handleExpand = useCallback(
    (nodeId: string) => {
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          expandComposite(
            activeGraph.document,
            visibleGraph,
            graph.exploration,
            nodeId,
          ),
        ),
      )
    },
    [activeGraph.document, visibleGraph],
  )
  const handleExpandVisible = useCallback(() => {
    setActiveGraph((graph) =>
      applyExplorationTransition(
        graph,
        expandVisibleComposites(visibleGraph, graph.exploration),
      ),
    )
  }, [visibleGraph])
  const handleExpandAll = useCallback(() => {
    setActiveGraph((graph) =>
      applyExplorationTransition(
        graph,
        expandAllComposites(activeGraph.document, graph.exploration),
      ),
    )
  }, [activeGraph.document])
  const handleSelectNode = useCallback(
    (nodeId: string) => {
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          selectNode(graph.exploration, visibleGraph, nodeId),
        ),
      )
    },
    [visibleGraph],
  )
  const handleSelectEdge = useCallback(
    (edgeId: string) => {
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          selectEdge(graph.exploration, visibleGraph, edgeId),
        ),
      )
    },
    [visibleGraph],
  )
  const handleClearSelection = useCallback(() => {
    setActiveGraph((graph) =>
      applyExplorationTransition(graph, clearSelection(graph.exploration)),
    )
  }, [])
  const handleReturn = useCallback(() => {
    setActiveGraph((graph) =>
      applyExplorationTransition(
        graph,
        returnToEnclosingScope(graph.exploration),
      ),
    )
  }, [])
  const handleUndo = useCallback(() => {
    setActiveGraph(undoLastViewChange)
  }, [])

  useEffect(() => {
    const layoutRunner = layoutRunnerRef.current

    if (layoutRunner) {
      void layoutRunner(visibleGraph)
    }
  }, [explorationState.projectionRevision, visibleGraph])

  const graphActions = useMemo(
    () => ({ onClickInto: handleClickInto, onExpand: handleExpand }),
    [handleClickInto, handleExpand],
  )
  const flowGraph = useMemo(() => {
    if (!canRenderLayoutForGraph(laidOutGraph, visibleGraph)) {
      return null
    }

    const convertedGraph = convertToReactFlow(
      visibleGraph,
      laidOutGraph.layout,
      graphActions,
    )

    return {
      nodes: convertedGraph.nodes.map((node) => ({
        ...node,
        selected: node.id === explorationState.selectedNodeId,
      })),
      edges: convertedGraph.edges.map((edge) => ({
        ...edge,
        selected: edge.id === explorationState.selectedEdgeId,
      })),
    }
  }, [
    explorationState.selectedEdgeId,
    explorationState.selectedNodeId,
    graphActions,
    laidOutGraph,
    visibleGraph,
  ])
  const visibleCompositeCount = visibleGraph.nodes.filter(
    (node) => node.kind === 'composite',
  ).length
  const stateAfterExpandAll = expandAllComposites(
    activeGraph.document,
    explorationState,
  )
  const expandableDescendantCount =
    stateAfterExpandAll.expandedNodeIds.size -
    explorationState.expandedNodeIds.size
  const isAtRoot = explorationState.scopePath.length === 1

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>Behavioural graph explorer</h1>
      </header>

      <GraphImport
        source={graphJsonSource}
        errorMessage={importError}
        onSourceChange={setGraphJsonSource}
        onLoadText={handleLoadText}
        onChooseFile={handleChooseFile}
      />

      <section className="exploration-toolbar" aria-label="View actions">
        <div>
          <span className="exploration-toolbar__label">Expansion</span>
          <span className="exploration-toolbar__status">
            {visibleCompositeCount} visible composite
            {visibleCompositeCount === 1 ? '' : 's'} · {expandableDescendantCount}{' '}
            available below this scope
          </span>
        </div>
        <div className="exploration-toolbar__actions">
          <button
            type="button"
            onClick={handleUndo}
            disabled={activeGraph.viewHistory.length === 0}
          >
            Undo last view change
          </button>
          <button
            type="button"
            className="back-control"
            onClick={handleReturn}
            disabled={isAtRoot}
          >
            Back to enclosing scope
          </button>
          <button
            type="button"
            onClick={handleExpandVisible}
            disabled={visibleCompositeCount === 0}
          >
            Expand one level
          </button>
          <button
            type="button"
            onClick={handleExpandAll}
            disabled={stateAfterExpandAll === explorationState}
          >
            Expand all
          </button>
        </div>
      </section>

      <section className="graph-panel" aria-label="Behavioural workflow graph">
        {flowGraph === null ? (
          <p className="graph-loading">Calculating graph layout…</p>
        ) : (
          <ReactFlow<Node<GraphFlowNodeData>>
            nodes={flowGraph.nodes}
            edges={flowGraph.edges}
            nodeTypes={graphNodeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            edgesReconnectable={false}
            onNodeClick={(_, node) => handleSelectNode(node.id)}
            onEdgeClick={(_, edge) => handleSelectEdge(edge.id)}
            onPaneClick={handleClearSelection}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            aria-label="Current workflow graph"
          >
            <Background gap={24} size={1} />
            <Controls aria-label="Graph controls" />
          </ReactFlow>
        )}
      </section>
    </main>
  )
}

function GraphNodeCard({ data }: NodeProps<Node<GraphFlowNodeData>>) {
  const isComposite = data.kind === 'composite'

  return (
    <div className={`graph-node graph-node--${data.kind}`}>
      <Handle type="target" position={Position.Left} />
      <div className="graph-node__heading">
        <span className="graph-node__kind">
          {isComposite ? 'Composite scope' : 'Leaf behaviour'}
        </span>
      </div>
      <strong className="graph-node__label">{data.label}</strong>
      <span className="graph-node__id">{data.graphNodeId}</span>
      {isComposite && (
        <div className="graph-node__actions">
          {data.canClickInto && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                data.onClickInto?.()
              }}
            >
              Open scope
            </button>
          )}
          {data.canExpand && (
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                data.onExpand?.()
              }}
            >
              Expand
            </button>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default App
