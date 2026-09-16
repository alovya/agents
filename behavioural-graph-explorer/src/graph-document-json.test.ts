import { describe, expect, it } from 'vitest'
import type { GraphDocument } from './graph'
import {
  GraphDocumentError,
  parseGraphDocumentText,
  validateGraphDocument,
} from './graph-document-json'

const validDocument: GraphDocument = {
  rootId: 'root',
  nodes: [
    { id: 'root', label: 'Root', kind: 'composite', parentId: null },
    { id: 'branch-a', label: 'Branch A', kind: 'composite', parentId: 'root' },
    { id: 'branch-b', label: 'Branch B', kind: 'composite', parentId: 'root' },
    {
      id: 'a-1',
      label: 'A one',
      kind: 'leaf',
      parentId: 'branch-a',
      metadata: {
        owner: 'agent',
        count: 2,
        enabled: true,
        empty: null,
        flags: [true, null],
        details: { stage: 'review' },
      },
    },
    { id: 'a-2', label: 'A two', kind: 'leaf', parentId: 'branch-a' },
    { id: 'b-1', label: 'B one', kind: 'leaf', parentId: 'branch-b' },
    { id: 'b-2', label: 'B two', kind: 'leaf', parentId: 'branch-b' },
  ],
  edges: [
    { id: 'a-forward', from: 'a-1', to: 'a-2', label: 'Continue' },
    { id: 'a-retry', from: 'a-2', to: 'a-1' },
  ],
}

type StructuralFailure = {
  name: string
  makeValue: () => unknown
  reason: RegExp
}

const structuralFailures: StructuralFailure[] = [
  {
    name: 'null top-level value',
    makeValue: () => null,
    reason: /document.*non-null.*object/i,
  },
  {
    name: 'array top-level value',
    makeValue: () => [],
    reason: /document.*non-null.*array.*object/i,
  },
  {
    name: 'primitive top-level value',
    makeValue: () => 'graph',
    reason: /document.*non-null.*object/i,
  },
  {
    name: 'missing rootId',
    makeValue: () => withDocument((document) => deleteField(document, 'rootId')),
    reason: /rootId.*required/i,
  },
  {
    name: 'missing nodes',
    makeValue: () => withDocument((document) => deleteField(document, 'nodes')),
    reason: /nodes.*required/i,
  },
  {
    name: 'missing edges',
    makeValue: () => withDocument((document) => deleteField(document, 'edges')),
    reason: /edges.*required/i,
  },
  {
    name: 'unknown top-level property',
    makeValue: () => withDocument((document) => setField(document, 'extra', true)),
    reason: /unexpected.*extra/i,
  },
  {
    name: 'empty rootId',
    makeValue: () => withDocument((document) => setField(document, 'rootId', '')),
    reason: /rootId.*non-empty string/i,
  },
  {
    name: 'non-string rootId',
    makeValue: () => withDocument((document) => setField(document, 'rootId', 42)),
    reason: /rootId.*non-empty string/i,
  },
  {
    name: 'non-array nodes',
    makeValue: () => withDocument((document) => setField(document, 'nodes', {})),
    reason: /nodes.*array/i,
  },
  {
    name: 'non-array edges',
    makeValue: () => withDocument((document) => setField(document, 'edges', 'edges')),
    reason: /edges.*array/i,
  },
  {
    name: 'null node',
    makeValue: () => withDocument((document) => replaceItem(document.nodes, 0, null)),
    reason: /nodes\[0\].*non-null.*object/i,
  },
  {
    name: 'array node',
    makeValue: () => withDocument((document) => replaceItem(document.nodes, 0, [])),
    reason: /nodes\[0\].*array.*object/i,
  },
  {
    name: 'primitive node',
    makeValue: () => withDocument((document) => replaceItem(document.nodes, 0, 'node')),
    reason: /nodes\[0\].*non-null.*object/i,
  },
  {
    name: 'missing node id',
    makeValue: () =>
      withDocument((document) => deleteField(document.nodes[0], 'id')),
    reason: /nodes\[0\]\.id.*required/i,
  },
  {
    name: 'missing node label',
    makeValue: () =>
      withDocument((document) => deleteField(document.nodes[0], 'label')),
    reason: /nodes\[0\]\.label.*required/i,
  },
  {
    name: 'missing node kind',
    makeValue: () =>
      withDocument((document) => deleteField(document.nodes[0], 'kind')),
    reason: /nodes\[0\]\.kind.*required/i,
  },
  {
    name: 'missing node parentId',
    makeValue: () =>
      withDocument((document) => deleteField(document.nodes[0], 'parentId')),
    reason: /nodes\[0\]\.parentId.*required/i,
  },
  {
    name: 'unknown node property',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[0], 'extra', true)),
    reason: /nodes\[0\].*unexpected.*extra/i,
  },
  {
    name: 'empty node id',
    makeValue: () => withDocument((document) => setField(document.nodes[0], 'id', '')),
    reason: /nodes\[0\]\.id.*non-empty string/i,
  },
  {
    name: 'non-string node id',
    makeValue: () => withDocument((document) => setField(document.nodes[0], 'id', 9)),
    reason: /nodes\[0\]\.id.*non-empty string/i,
  },
  {
    name: 'empty node label',
    makeValue: () => withDocument((document) => setField(document.nodes[0], 'label', '')),
    reason: /nodes\[0\]\.label.*non-empty string/i,
  },
  {
    name: 'non-string node label',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[0], 'label', false)),
    reason: /nodes\[0\]\.label.*non-empty string/i,
  },
  {
    name: 'invalid node kind',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[0], 'kind', 'branch')),
    reason: /nodes\[0\]\.kind.*leaf.*composite/i,
  },
  {
    name: 'empty node parentId',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[0], 'parentId', '')),
    reason: /nodes\[0\]\.parentId.*null.*non-empty string/i,
  },
  {
    name: 'invalid node parentId',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[0], 'parentId', 7)),
    reason: /nodes\[0\]\.parentId.*null.*non-empty string/i,
  },
  {
    name: 'null metadata',
    makeValue: () => withDocument((document) => setNodeMetadata(document, null)),
    reason: /nodes\[3\]\.metadata.*plain JSON object/i,
  },
  {
    name: 'array metadata',
    makeValue: () => withDocument((document) => setNodeMetadata(document, [])),
    reason: /nodes\[3\]\.metadata.*plain JSON object/i,
  },
  {
    name: 'undefined metadata',
    makeValue: () =>
      withDocument((document) => setNodeMetadata(document, undefined)),
    reason: /nodes\[3\]\.metadata.*plain JSON object/i,
  },
  {
    name: 'non-plain metadata',
    makeValue: () =>
      withDocument((document) => setNodeMetadata(document, new Date(0))),
    reason: /nodes\[3\]\.metadata.*plain JSON object/i,
  },
  {
    name: 'null edge',
    makeValue: () => withDocument((document) => replaceItem(document.edges, 0, null)),
    reason: /edges\[0\].*non-null.*object/i,
  },
  {
    name: 'array edge',
    makeValue: () => withDocument((document) => replaceItem(document.edges, 0, [])),
    reason: /edges\[0\].*array.*object/i,
  },
  {
    name: 'primitive edge',
    makeValue: () => withDocument((document) => replaceItem(document.edges, 0, 'edge')),
    reason: /edges\[0\].*non-null.*object/i,
  },
  {
    name: 'missing edge id',
    makeValue: () =>
      withDocument((document) => deleteField(document.edges[0], 'id')),
    reason: /edges\[0\]\.id.*required/i,
  },
  {
    name: 'missing edge from',
    makeValue: () =>
      withDocument((document) => deleteField(document.edges[0], 'from')),
    reason: /edges\[0\]\.from.*required/i,
  },
  {
    name: 'missing edge to',
    makeValue: () =>
      withDocument((document) => deleteField(document.edges[0], 'to')),
    reason: /edges\[0\]\.to.*required/i,
  },
  {
    name: 'unknown edge property',
    makeValue: () =>
      withDocument((document) => setField(document.edges[0], 'extra', true)),
    reason: /edges\[0\].*unexpected.*extra/i,
  },
  {
    name: 'empty edge id',
    makeValue: () => withDocument((document) => setField(document.edges[0], 'id', '')),
    reason: /edges\[0\]\.id.*non-empty string/i,
  },
  {
    name: 'non-string edge id',
    makeValue: () => withDocument((document) => setField(document.edges[0], 'id', 9)),
    reason: /edges\[0\]\.id.*non-empty string/i,
  },
  {
    name: 'non-string edge from',
    makeValue: () =>
      withDocument((document) => setField(document.edges[0], 'from', null)),
    reason: /edges\[0\]\.from.*non-empty string/i,
  },
  {
    name: 'empty edge from',
    makeValue: () => withDocument((document) => setField(document.edges[0], 'from', '')),
    reason: /edges\[0\]\.from.*non-empty string/i,
  },
  {
    name: 'empty edge to',
    makeValue: () => withDocument((document) => setField(document.edges[0], 'to', '')),
    reason: /edges\[0\]\.to.*non-empty string/i,
  },
  {
    name: 'non-string edge to',
    makeValue: () => withDocument((document) => setField(document.edges[0], 'to', null)),
    reason: /edges\[0\]\.to.*non-empty string/i,
  },
  {
    name: 'empty edge label',
    makeValue: () =>
      withDocument((document) => setField(document.edges[0], 'label', '')),
    reason: /edges\[0\]\.label.*non-empty string/i,
  },
  {
    name: 'non-string edge label',
    makeValue: () =>
      withDocument((document) => setField(document.edges[0], 'label', 1)),
    reason: /edges\[0\]\.label.*non-empty string/i,
  },
  {
    name: 'duplicate node id',
    makeValue: () =>
      withDocument((document) => setField(document.nodes[1], 'id', 'root')),
    reason: /nodes\[1\]\.id.*duplicate.*root.*nodes/i,
  },
  {
    name: 'duplicate edge id',
    makeValue: () =>
      withDocument((document) => setField(document.edges[1], 'id', 'a-forward')),
    reason: /edges\[1\]\.id.*duplicate.*a-forward.*edges/i,
  },
]

function withDocument(mutate: (document: GraphDocument) => void): GraphDocument {
  const document = structuredClone(validDocument)
  mutate(document)
  return document
}

function setField(target: object, field: string, value: unknown): void {
  const record = target as Record<string, unknown>
  record[field] = value
}

function deleteField(target: object, field: string): void {
  const record = target as Record<string, unknown>
  delete record[field]
}

function replaceItem(items: readonly unknown[], index: number, value: unknown): void {
  const mutableItems = items as unknown as unknown[]
  mutableItems[index] = value
}

function setNodeMetadata(document: GraphDocument, value: unknown): void {
  setField(document.nodes[3], 'metadata', value)
}

function captureGraphDocumentError(action: () => unknown): GraphDocumentError {
  try {
    action()
  } catch (error) {
    if (error instanceof GraphDocumentError) {
      return error
    }

    throw error
  }

  throw new Error('Expected graph document validation to fail')
}

describe('validateGraphDocument', () => {
  it.each(structuralFailures)('$name', ({ makeValue, reason }) => {
    const error = captureGraphDocumentError(() =>
      validateGraphDocument(makeValue()),
    )

    expect(error.code).toBe('invalid-document')
    expect(error.message).toMatch(/^Invalid graph document:/)
    expect(error.message).toMatch(reason)
  })

  it('accepts every valid node kind', () => {
    for (const kind of ['leaf', 'composite'] as const) {
      const document = withDocument((value) =>
        setField(value.nodes[3], 'kind', kind),
      )

      expect(validateGraphDocument(document)).toBe(document)
    }
  })

  it('accepts zero edges and absent optional fields', () => {
    const document = withDocument((value) => setField(value, 'edges', []))

    expect(validateGraphDocument(document)).toBe(document)
  })

  it('accepts zero nodes at the shape boundary', () => {
    const document = withDocument((value) => setField(value, 'nodes', []))

    expect(validateGraphDocument(document)).toBe(document)
  })

  it('accepts non-empty strings without trimming or normalising them', () => {
    const document = withDocument((value) => {
      setField(value, 'rootId', ' ')
      setField(value.nodes[0], 'label', '  Root  ')
      setField(value.nodes[1], 'parentId', ' ')
      setField(value.edges[0], 'label', '  Continue  ')
    })

    const accepted = validateGraphDocument(document)

    expect(accepted.rootId).toBe(' ')
    expect(accepted.nodes[0].label).toBe('  Root  ')
    expect(accepted.nodes[1].parentId).toBe(' ')
    expect(accepted.edges[0].label).toBe('  Continue  ')
  })

  it('accepts nested JSON metadata and keeps it unchanged', () => {
    const document = withDocument((value) =>
      setNodeMetadata(value, {
        text: 'value',
        number: 3.5,
        truth: false,
        nothing: null,
        list: [{ nested: ['value', 1] }],
      }),
    )
    const before = structuredClone(document)

    const accepted = validateGraphDocument(document)

    expect(accepted).toBe(document)
    expect(document).toEqual(before)
  })

  it.each([
    { name: 'undefined', value: undefined },
    { name: 'function', value: () => undefined },
    { name: 'symbol', value: Symbol('metadata') },
    { name: 'bigint', value: BigInt(1) },
    { name: 'NaN', value: Number.NaN },
    { name: 'positive infinity', value: Number.POSITIVE_INFINITY },
    { name: 'negative infinity', value: Number.NEGATIVE_INFINITY },
    { name: 'non-plain object', value: new Map() },
  ])('rejects a $name nested metadata value', ({ value }) => {
    const document = withDocument((validValue) =>
      setNodeMetadata(validValue, { invalid: value }),
    )
    const error = captureGraphDocumentError(() =>
      validateGraphDocument(document),
    )

    expect(error.message).toMatch(/nodes\[3\]\.metadata\.invalid/)
  })

  it('round-trips the fixture through JSON text', () => {
    const parsed = parseGraphDocumentText(JSON.stringify(validDocument))

    expect(parsed).toEqual(validDocument)
  })

  it('reports malformed JSON with the stable syntax error code and prefix', () => {
    const error = captureGraphDocumentError(() =>
      parseGraphDocumentText('{"rootId":'),
    )

    expect(error.code).toBe('invalid-json')
    expect(error.message).toMatch(/^Invalid graph JSON:/)
  })

  it('reports structural errors from parsed JSON as document errors', () => {
    const error = captureGraphDocumentError(() =>
      parseGraphDocumentText(JSON.stringify({ ...validDocument, extra: true })),
    )

    expect(error.code).toBe('invalid-document')
    expect(error.message).toMatch(/^Invalid graph document:.*extra.*unexpected/i)
  })

  it('does not mutate the document it validates', () => {
    const document = structuredClone(validDocument)
    const before = structuredClone(document)

    validateGraphDocument(document)

    expect(document).toEqual(before)
  })
})
