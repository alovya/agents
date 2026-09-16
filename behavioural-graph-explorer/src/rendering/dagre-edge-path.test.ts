import { describe, expect, it } from 'vitest'
import { createDagreRoutePath } from './dagre-edge-path'

describe('createDagreRoutePath', () => {
  it('turns Dagre route points into an SVG polyline path', () => {
    expect(
      createDagreRoutePath([
        { x: 10, y: 20 },
        { x: 40, y: 20 },
        { x: 40, y: 80 },
      ]),
    ).toBe('M10,20 L40,20 L40,80')
  })

  it('rejects routes without a source and target point', () => {
    expect(() => createDagreRoutePath([{ x: 10, y: 20 }])).toThrow(
      'Dagre edge routes must contain at least two points',
    )
  })
})
