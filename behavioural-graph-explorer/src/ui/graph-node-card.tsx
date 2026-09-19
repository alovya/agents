import { Handle, Position } from '@xyflow/react'
import type { Node, NodeProps } from '@xyflow/react'
import {
  SELECTION_COLOUR_PALETTE_SIZE,
  type GraphFlowNodeData,
} from '../rendering/react-flow-adapter'

const NODE_HANDLE_POSITIONS = [
  { side: 'top', position: Position.Top },
  { side: 'right', position: Position.Right },
  { side: 'bottom', position: Position.Bottom },
  { side: 'left', position: Position.Left },
] as const

export function GraphNodeCard({ data }: NodeProps<Node<GraphFlowNodeData>>) {
  const isComposite = data.kind === 'composite'
  const selectionColourClasses = data.selectionColourIds.map(
    (selectionColourId) =>
      `graph-node--selection-${selectionColourId % SELECTION_COLOUR_PALETTE_SIZE}`,
  )

  return (
    <div
      className={[
        'graph-node',
        `graph-node--${data.kind}`,
        ...selectionColourClasses,
      ].join(' ')}
    >
      {NODE_HANDLE_POSITIONS.map(({ side, position }) => (
        <Handle
          key={`target-${side}`}
          id={`target-${side}`}
          type="target"
          position={position}
        />
      ))}
      <strong className="graph-node__label">{data.label}</strong>
      {data.selectionColourIds.length > 1 && (
        <span className="graph-node__selection-markers" aria-hidden="true">
          {data.selectionColourIds.map((selectionColourId) => (
            <span
              className={`graph-node__selection-marker graph-node--selection-${selectionColourId % SELECTION_COLOUR_PALETTE_SIZE}`}
              key={selectionColourId}
            />
          ))}
        </span>
      )}
      {(isComposite || data.canCollapse) && (
        <div className="graph-node__actions">
          {data.canClickInto && (
            <button
              type="button"
              aria-label="Open subgraph"
              title="Open subgraph"
              onClick={(event) => {
                event.stopPropagation()
                data.onClickInto?.()
              }}
            >
              <span
                className="graph-node__action-symbol graph-node__action-symbol--open"
                aria-hidden="true"
              />
            </button>
          )}
          {data.canExpand && (
            <button
              type="button"
              aria-label="Expand"
              title="Expand"
              onClick={(event) => {
                event.stopPropagation()
                data.onExpand?.()
              }}
            >
              <span
                className="graph-node__action-symbol graph-node__action-symbol--expand"
                aria-hidden="true"
              />
            </button>
          )}
          {data.canCollapse && (
            <button
              type="button"
              aria-label="Collapse one level"
              title="Collapse one level"
              onClick={(event) => {
                event.stopPropagation()
                data.onCollapse?.()
              }}
            >
              <span
                className="graph-node__action-symbol graph-node__action-symbol--collapse"
                aria-hidden="true"
              />
            </button>
          )}
        </div>
      )}
      {NODE_HANDLE_POSITIONS.map(({ side, position }) => (
        <Handle
          key={`source-${side}`}
          id={`source-${side}`}
          type="source"
          position={position}
        />
      ))}
    </div>
  )
}
