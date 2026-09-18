import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Background, Controls, ReactFlow } from '@xyflow/react'
import type { Node } from '@xyflow/react'
import { DagreRouteEdge } from '../rendering/dagre-edge'
import { projectVisibleGraph } from '../graph/project-visible-graph'
import {
  activateGraphDocument,
  applyExplorationTransition,
  type ActiveGraph,
  redoLastViewChange,
  undoLastViewChange,
} from '../exploration/active-graph'
import { DagreLayoutEngine } from '../layout/dagre-layout'
import {
  canCollapseOneLevel,
  clearSelection,
  clickIntoComposite,
  collapseOneLevel,
  expandAllComposites,
  expandComposite,
  expandVisibleComposites,
  findConnectedEdgeIds,
  selectEdge,
  selectNode,
} from '../exploration/explore-graph'
import { convertToReactFlow, type GraphFlowNodeData } from '../rendering/react-flow-adapter'
import {
  canRenderLayoutForGraph,
  createLatestLayoutRunner,
  type ApplyLatestLayout,
  type LaidOutGraph,
} from './apply-latest-layout'
import { GraphDocumentError, parseGraphDocumentText } from '../graph/graph-document-json'
import { GraphImport } from '../ui/graph-import'
import { GraphNodeCard } from '../ui/graph-node-card'
import {
  createInitialGraphView,
  fetchGraphFileSource,
  readGraphFileRouteFromLocation,
} from './load-requested-graph'

import './App.css'

const graphNodeTypes = {
  graph: GraphNodeCard,
}

const graphEdgeTypes = {
  dagre: DagreRouteEdge,
}

const NODE_KIND_LEGEND = [
  { label: 'Composite', colour: '#1d4ed8' },
  { label: 'Leaf', colour: '#64748b' },
] as const

function App() {
  const [initialGraphView] = useState(() => createInitialGraphView(null))
  const [activeGraph, setActiveGraph] = useState<ActiveGraph>(
    initialGraphView.activeGraph,
  )
  const [graphJsonSource, setGraphJsonSource] = useState(
    initialGraphView.graphJsonSource,
  )
  const [importError, setImportError] = useState<string | null>(
    initialGraphView.importError,
  )
  const [boldedEdgeIds, setBoldedEdgeIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  )
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
  const [laidOutGraph, setLaidOutGraph] = useState<LaidOutGraph | null>(null)
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
      setBoldedEdgeIds(new Set())
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
  useEffect(() => {
    const graphFileRoute = readGraphFileRouteFromLocation()

    if (graphFileRoute === null) return

    let isCancelled = false

    void fetchGraphFileSource(graphFileRoute)
      .then((source) => {
        if (isCancelled) return

        setGraphJsonSource(source)
        loadGraphDocumentSource(source)
      })
      .catch((error: unknown) => {
        if (isCancelled) return

        setImportError(
          error instanceof Error
            ? error.message
            : 'Could not load graph JSON file.',
        )
      })

    return () => {
      isCancelled = true
    }
  }, [loadGraphDocumentSource])
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
      const connectedEdgeIds = findConnectedEdgeIds(visibleGraph, nodeId)

      setBoldedEdgeIds(new Set(connectedEdgeIds))
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
      setBoldedEdgeIds((edgeIds) => {
        const nextEdgeIds = new Set(edgeIds)

        if (nextEdgeIds.has(edgeId)) {
          nextEdgeIds.delete(edgeId)
        } else {
          nextEdgeIds.add(edgeId)
        }

        return nextEdgeIds
      })
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          selectEdge(graph.exploration, visibleGraph, edgeId),
        ),
      )
    },
    [visibleGraph],
  )
  const handleClearBoldedEdges = useCallback(() => {
    const visibleEdgeIds = new Set(
      visibleGraph.edges.map((edge) => edge.id),
    )

    setBoldedEdgeIds((edgeIds) => {
      const remainingEdgeIds = new Set(
        [...edgeIds].filter((edgeId) => !visibleEdgeIds.has(edgeId)),
      )

      return remainingEdgeIds.size === edgeIds.size ? edgeIds : remainingEdgeIds
    })
  }, [visibleGraph])
  const handleClearSelection = useCallback(() => {
    setActiveGraph((graph) =>
      applyExplorationTransition(graph, clearSelection(graph.exploration)),
    )
  }, [])
  const handleUndo = useCallback(() => {
    setActiveGraph(undoLastViewChange)
  }, [])
  const handleRedo = useCallback(() => {
    setActiveGraph(redoLastViewChange)
  }, [])

  useEffect(() => {
    const layoutRunner = layoutRunnerRef.current

    if (layoutRunner) {
      void layoutRunner(visibleGraph)
    }
  }, [explorationState.projectionRevision, visibleGraph])

  const handleCollapse = useCallback(
    (nodeId: string) => {
      setActiveGraph((graph) =>
        applyExplorationTransition(
          graph,
          collapseOneLevel(
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
  const graphActions = useMemo(
    () => ({
      onClickInto: handleClickInto,
      onExpand: handleExpand,
      canCollapse: (nodeId: string) =>
        canCollapseOneLevel(
          activeGraph.document,
          visibleGraph,
          explorationState,
          nodeId,
        ),
      onCollapse: handleCollapse,
    }),
    [
      activeGraph.document,
      explorationState,
      handleClickInto,
      handleCollapse,
      handleExpand,
      visibleGraph,
    ],
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
        selected: boldedEdgeIds.has(edge.id),
      })),
    }
  }, [
    explorationState.selectedNodeId,
    boldedEdgeIds,
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
  const currentScope = activeGraph.document.nodes.find(
    (node) => node.id === explorationState.currentScopeId,
  )

  if (currentScope === undefined) {
    throw new Error(
      `Missing current scope node: ${explorationState.currentScopeId}`,
    )
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <h1>Behavioural graph explorer</h1>
      </header>

      <div className="viewer-layout">
        <section className="graph-panel" aria-label="Behavioural workflow graph">
        {flowGraph === null ? (
          <p className="graph-loading">Calculating graph layout…</p>
        ) : (
          <ReactFlow<Node<GraphFlowNodeData>>
            nodes={flowGraph.nodes}
            edges={flowGraph.edges}
            nodeTypes={graphNodeTypes}
            edgeTypes={graphEdgeTypes}
            nodesDraggable={false}
            nodesConnectable={false}
            edgesReconnectable={false}
            onNodeClick={(_, node) => handleSelectNode(node.id)}
            onEdgeClick={(_, edge) => handleSelectEdge(edge.id)}
            onPaneClick={handleClearSelection}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            minZoom={0.05}
            aria-label="Current workflow graph"
          >
            <Background gap={24} size={1} />
            <Controls aria-label="Graph controls" />
          </ReactFlow>
        )}
        </section>

        <aside className="viewer-sidebar" aria-label="Graph controls and input">
          <section className="exploration-toolbar" aria-label="View actions">
            <div>
              <span className="exploration-toolbar__scope">
                Current subgraph: {currentScope.label}
              </span>
              <span className="exploration-toolbar__status">
                {visibleCompositeCount} visible composite
                {visibleCompositeCount === 1 ? '' : 's'} · {expandableDescendantCount}{' '}
                available below this scope
              </span>
              <div className="graph-legend node-type-legend" aria-label="Node type legend">
                <span className="graph-legend__label">Node type</span>
                {NODE_KIND_LEGEND.map(({ label, colour }) => (
                  <span className="graph-legend__item" key={label}>
                    <span
                      className="graph-legend__swatch"
                      style={{ backgroundColor: colour }}
                    />
                    {label}
                  </span>
                ))}
              </div>
              <div className="graph-legend graph-control-legend" aria-label="Composite control legend">
                <span className="graph-legend__label">Composite controls</span>
                <span className="graph-legend__item">
                  <span className="graph-legend__symbol" aria-hidden="true">›</span>
                  Open subgraph
                </span>
                <span className="graph-legend__item">
                  <span className="graph-legend__symbol" aria-hidden="true">+</span>
                  Expand one level
                </span>
                <span className="graph-legend__item">
                  <span className="graph-legend__symbol" aria-hidden="true">−</span>
                  Collapse one level
                </span>
              </div>
            </div>
            <div className="exploration-toolbar__actions">
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
              <button
                type="button"
                onClick={handleUndo}
                disabled={activeGraph.viewHistory.length === 0}
              >
                Undo last view change
              </button>
              <button
                type="button"
                onClick={handleRedo}
                disabled={activeGraph.redoHistory.length === 0}
              >
                Redo last view change
              </button>
              <button
                type="button"
                onClick={handleClearBoldedEdges}
                disabled={
                  !visibleGraph.edges.some((edge) => boldedEdgeIds.has(edge.id))
                }
              >
                Clear bold arrows
              </button>
            </div>
          </section>

          <GraphImport
            source={graphJsonSource}
            errorMessage={importError}
            onSourceChange={setGraphJsonSource}
            onLoadText={handleLoadText}
            onChooseFile={handleChooseFile}
          />
        </aside>
      </div>
    </main>
  )
}

export default App
