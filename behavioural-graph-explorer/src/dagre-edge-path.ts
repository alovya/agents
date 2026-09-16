import type { LayoutPoint } from './dagre-layout'

export function createDagreRoutePath(
  points: ReadonlyArray<LayoutPoint>,
): string {
  if (points.length < 2) {
    throw new Error('Dagre edge routes must contain at least two points')
  }

  return points
    .map(({ x, y }, index) => `${index === 0 ? 'M' : 'L'}${x},${y}`)
    .join(' ')
}
