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
  DagreLayoutEngine,
  type LayoutResult,
} from './dagre-layout'
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
  convertToReactFlow,
  type GraphFlowNodeData,
} from './react-flow-adapter'
import { createLatestLayoutRunner, type ApplyLatestLayout } from './latest-layout'
import { SAMPLE_GRAPH_DOCUMENT } from './sample-graph'

import './App.css'

const graphNodeTypes = {
  graph: GraphNodeCard,
}

function App() {
  const [explorationState, setExplorationState] = useState(() =>
    createInitialExplorationState(SAMPLE_GRAPH_DOCUMENT),
  )
  const visibleGraph = useMemo(
    () =>
      projectVisibleGraph(
        SAMPLE_GRAPH_DOCUMENT,
        explorationState.currentScopeId,
        explorationState.expandedNodeIds,
      ),
    [explorationState.currentScopeId, explorationState.expandedNodeIds],
  )
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

  const handleClickInto = useCallback(
    (nodeId: string) => {
      setExplorationState((state) =>
        clickIntoComposite(SAMPLE_GRAPH_DOCUMENT, visibleGraph, state, nodeId),
      )
    },
    [visibleGraph],
  )
  const handleExpand = useCallback(
    (nodeId: string) => {
      setExplorationState((state) =>
        expandComposite(SAMPLE_GRAPH_DOCUMENT, visibleGraph, state, nodeId),
      )
    },
    [visibleGraph],
  )
  const handleExpandVisible = useCallback(() => {
    setExplorationState((state) => expandVisibleComposites(visibleGraph, state))
  }, [visibleGraph])
  const handleExpandAll = useCallback(() => {
    setExplorationState((state) =>
      expandAllComposites(SAMPLE_GRAPH_DOCUMENT, state),
    )
  }, [])
  const handleSelectNode = useCallback(
    (nodeId: string) => {
      setExplorationState((state) => selectNode(state, visibleGraph, nodeId))
    },
    [visibleGraph],
  )
  const handleSelectEdge = useCallback(
    (edgeId: string) => {
      setExplorationState((state) => selectEdge(state, visibleGraph, edgeId))
    },
    [visibleGraph],
  )
  const handleClearSelection = useCallback(() => {
    setExplorationState(clearSelection)
  }, [])
  const handleReturn = useCallback(() => {
    setExplorationState(returnToEnclosingScope)
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
    if (laidOutGraph === null || laidOutGraph.graph !== visibleGraph) {
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
  const currentScope = SAMPLE_GRAPH_DOCUMENT.nodes.find(
    (node) => node.id === explorationState.currentScopeId,
  )
  const selectedNode = visibleGraph.nodes.find(
    (node) => node.id === explorationState.selectedNodeId,
  )
  const selectedEdge = visibleGraph.edges.find(
    (edge) => edge.id === explorationState.selectedEdgeId,
  )
  const visibleCompositeCount = visibleGraph.nodes.filter(
    (node) => node.kind === 'composite',
  ).length
  const stateAfterExpandAll = expandAllComposites(
    SAMPLE_GRAPH_DOCUMENT,
    explorationState,
  )
  const expandableDescendantCount =
    stateAfterExpandAll.expandedNodeIds.size -
    explorationState.expandedNodeIds.size
  const isAtRoot = explorationState.scopePath.length === 1
  const scopePathLabels = explorationState.scopePath.map(
    (scopeId) =>
      SAMPLE_GRAPH_DOCUMENT.nodes.find((node) => node.id === scopeId)?.label ??
      scopeId,
  )

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="app-kicker">Behavioural Graph Explorer</p>
          <h1>How the explorer works</h1>
          <p className="app-description">
            Follow the graph from its complete source through projection, exploration, and rendering.
          </p>
        </div>
        <div className="app-summary" aria-label="Current graph view">
          <span className="app-summary__label">Scope</span>
          <strong>{currentScope?.label}</strong>
          <span className="app-summary__status">
            {isAtRoot && explorationState.expandedNodeIds.size === 0
              ? 'Collapsed root'
              : isAtRoot
                ? 'Root scope'
                : 'Enclosed scope'}
          </span>
          <span className="app-summary__path">
            {scopePathLabels.join(' / ')}
          </span>
          <span className="app-summary__label">Selection</span>
          <strong>
            {selectedNode?.label ??
              (selectedEdge
                ? `${selectedEdge.source} → ${selectedEdge.target}`
                : 'Nothing selected')}
          </strong>
          <span className="app-summary__path">
            {selectedNode
              ? `Node: ${selectedNode.id}`
              : selectedEdge
                ? `Edge: ${selectedEdge.id}`
                : 'Click a node or edge to select it'}
          </span>
          <button
            type="button"
            className="back-control"
            onClick={handleReturn}
            disabled={isAtRoot}
          >
            Back to enclosing scope
          </button>
        </div>
      </header>

      <section className="exploration-toolbar" aria-label="Expansion actions">
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
            aria-label="Sample workflow graph"
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
