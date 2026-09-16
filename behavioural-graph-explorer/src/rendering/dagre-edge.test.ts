import { describe, expect, it } from 'vitest'
import { Position, type EdgeProps } from '@xyflow/react'
import { DagreRouteEdge } from './dagre-edge'
import type { DagreRouteEdgeData } from './dagre-edge'

function createEdgeProps(data: DagreRouteEdgeData | undefined): EdgeProps<DagreRouteEdge> {
  return {
    id: 'prepare->execute',
    type: 'dagre',
    source: 'prepare',
    target: 'execute',
    sourceX: 0,
    sourceY: 20,
    targetX: 100,
    targetY: 80,
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    data,
  }
}

describe('DagreRouteEdge', () => {
  it('refuses to render an edge without Dagre route data', () => {
    expect(() => DagreRouteEdge(createEdgeProps(undefined))).toThrow(
      'Missing Dagre route data for edge: prepare->execute',
    )
  })

  it('draws the Dagre route it was given', () => {
    const element = DagreRouteEdge(
      createEdgeProps({
        route: [
          { x: 10, y: 20 },
          { x: 40, y: 80 },
        ],
      }),
    )

    expect(element.props.path).toBe('M10,20 L40,80')
  })
})
