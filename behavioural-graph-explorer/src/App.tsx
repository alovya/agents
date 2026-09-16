import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Background,
  Controls,
  Handle,
  Position,
  ReactFlow,
} from '@xyflow/react'
import type { Node, NodeProps } from '@xyflow/react'
import { projectVisibleGraph } from './graph'
import {
  DagreLayoutEngine,
  type LayoutResult,
} from './dagre-layout'
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
  const visibleGraph = useMemo(
    () => projectVisibleGraph(SAMPLE_GRAPH_DOCUMENT, SAMPLE_GRAPH_DOCUMENT.rootId, new Set()),
    [],
  )
  const [layout, setLayout] = useState<LayoutResult | null>(null)
  const layoutRunnerRef = useRef<ApplyLatestLayout | null>(null)

  if (layoutRunnerRef.current === null) {
    layoutRunnerRef.current = createLatestLayoutRunner(
      new DagreLayoutEngine(),
      (_graph, nextLayout) => setLayout(nextLayout),
    )
  }

  useEffect(() => {
    const layoutRunner = layoutRunnerRef.current

    if (layoutRunner) {
      void layoutRunner(visibleGraph)
    }
  }, [visibleGraph])

  const flowGraph = useMemo(
    () =>
      layout === null
        ? null
        : convertToReactFlow(visibleGraph, layout, {}),
    [layout, visibleGraph],
  )

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="app-kicker">Behavioural Graph Explorer</p>
          <h1>Sample workflow</h1>
          <p className="app-description">
            A read-only view of the workflow&apos;s collapsed root projection.
          </p>
        </div>
        <div className="app-summary" aria-label="Current graph view">
          <span className="app-summary__label">Scope</span>
          <strong>Behavioural workflow</strong>
          <span className="app-summary__status">Collapsed root</span>
        </div>
      </header>

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
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

export default App
