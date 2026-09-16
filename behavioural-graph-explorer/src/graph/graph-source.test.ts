import { describe, expect, it } from 'vitest'
import { decodeGraphSourceParameter } from './graph-source'

describe('decodeGraphSourceParameter', () => {
  it('decodes UTF-8 graph JSON from a URL-safe base64 value', () => {
    const graphSource = '{"label":"héllo"}'
    const encodedGraph = 'eyJsYWJlbCI6ImjDqWxsbyJ9'

    expect(decodeGraphSourceParameter(encodedGraph)).toBe(graphSource)
  })
})
