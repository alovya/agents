import { BaseEdge } from '@xyflow/react'
import type { Edge, EdgeProps } from '@xyflow/react'
import { createDagreRoutePath } from './dagre-edge-path'
import type { LayoutPoint } from './dagre-layout'

export type DagreRouteEdgeData = {
  route: ReadonlyArray<LayoutPoint>
}

export type DagreRouteEdge = Edge<DagreRouteEdgeData, 'dagre'>

export function DagreRouteEdge({
  id,
  data,
  style,
  markerEnd,
  markerStart,
  interactionWidth,
}: EdgeProps<DagreRouteEdge>) {
  if (!data) {
    throw new Error(`Missing Dagre route data for edge: ${id}`)
  }

  return (
    <BaseEdge
      id={id}
      path={createDagreRoutePath(data.route)}
      style={style}
      markerEnd={markerEnd}
      markerStart={markerStart}
      interactionWidth={interactionWidth}
    />
  )
}
