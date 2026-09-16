import type {
  GraphDocument,
  GraphEdge,
  GraphMetadata,
  GraphNode,
} from './graph'

const DOCUMENT_FIELDS = ['rootId', 'nodes', 'edges'] as const
const NODE_REQUIRED_FIELDS = ['id', 'label', 'kind', 'parentId'] as const
const NODE_OPTIONAL_FIELDS = ['metadata'] as const
const EDGE_REQUIRED_FIELDS = ['id', 'from', 'to'] as const
const EDGE_OPTIONAL_FIELDS = ['label'] as const

type ObjectRecord = Record<string, unknown>

export class GraphDocumentError extends Error {
  readonly code: 'invalid-json' | 'invalid-document'

  constructor(code: GraphDocumentError['code'], message: string) {
    super(message)
    this.name = 'GraphDocumentError'
    this.code = code
  }
}

export function parseGraphDocumentText(source: string): GraphDocument {
  let value: unknown

  try {
    value = JSON.parse(source)
  } catch (error) {
    if (error instanceof SyntaxError) {
      throw new GraphDocumentError('invalid-json', `Invalid graph JSON: ${error.message}`)
    }

    throw error
  }

  return validateGraphDocument(value)
}

export function validateGraphDocument(value: unknown): GraphDocument {
  const document = validateObjectShape(value, '', DOCUMENT_FIELDS, [])
  validateNonEmptyString(document.rootId, 'rootId')
  const nodes = validateArray(document.nodes, 'nodes')
  const edges = validateArray(document.edges, 'edges')
  const nodeIds = nodes.map((node, index) =>
    validateNode(node, `nodes[${index}]`).id,
  )
  const edgeIds = edges.map((edge, index) =>
    validateEdge(edge, `edges[${index}]`).id,
  )

  assertUniqueIds(nodeIds, 'nodes')
  assertUniqueIds(edgeIds, 'edges')

  return document as GraphDocument
}

function validateNode(value: unknown, path: string): GraphNode {
  const node = validateObjectShape(
    value,
    path,
    NODE_REQUIRED_FIELDS,
    NODE_OPTIONAL_FIELDS,
  )

  validateNonEmptyString(node.id, `${path}.id`)
  validateNonEmptyString(node.label, `${path}.label`)
  validateNodeKind(node.kind, `${path}.kind`)
  validateParentId(node.parentId, `${path}.parentId`)

  if (Object.hasOwn(node, 'metadata')) {
    validateMetadata(node.metadata, `${path}.metadata`)
  }

  return node as GraphNode
}

function validateEdge(value: unknown, path: string): GraphEdge {
  const edge = validateObjectShape(
    value,
    path,
    EDGE_REQUIRED_FIELDS,
    EDGE_OPTIONAL_FIELDS,
  )

  validateNonEmptyString(edge.id, `${path}.id`)
  validateNonEmptyString(edge.from, `${path}.from`)
  validateNonEmptyString(edge.to, `${path}.to`)

  if (Object.hasOwn(edge, 'label')) {
    validateNonEmptyString(edge.label, `${path}.label`)
  }

  return edge as GraphEdge
}

function validateObjectShape(
  value: unknown,
  path: string,
  requiredFields: readonly string[],
  optionalFields: readonly string[],
): ObjectRecord {
  if (!isObjectRecord(value)) {
    fail(path, 'must be a non-null, non-array object')
  }

  const allowedFields = [...requiredFields, ...optionalFields]

  for (const field of Reflect.ownKeys(value)) {
    if (typeof field !== 'string' || !allowedFields.includes(field)) {
      fail(
        propertyPath(path, field),
        `is an unexpected property named "${String(field)}"`,
      )
    }
  }

  for (const field of requiredFields) {
    if (!Object.hasOwn(value, field)) {
      fail(propertyPath(path, field), 'is required')
    }
  }

  return value
}

function validateArray(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) {
    fail(path, 'must be an array')
  }

  return value
}

function validateNonEmptyString(value: unknown, path: string): string {
  if (typeof value !== 'string' || value.length === 0) {
    fail(path, 'must be a non-empty string')
  }

  return value
}

function validateNodeKind(value: unknown, path: string): void {
  if (value !== 'leaf' && value !== 'composite') {
    fail(path, "must be either 'leaf' or 'composite'")
  }
}

function validateParentId(value: unknown, path: string): void {
  if (value !== null && (typeof value !== 'string' || value.length === 0)) {
    fail(path, 'must be null or a non-empty string')
  }
}

function validateMetadata(value: unknown, path: string): GraphMetadata {
  if (!isPlainObject(value)) {
    fail(path, 'must be a plain JSON object')
  }

  validateJsonObjectContents(value, path)
  return value as GraphMetadata
}

function validateJsonValue(value: unknown, path: string): void {
  if (value === null) {
    return
  }

  if (typeof value === 'string' || typeof value === 'boolean') {
    return
  }

  if (typeof value === 'number') {
    if (Number.isFinite(value)) {
      return
    }

    fail(path, 'must be a finite number')
  }

  if (Array.isArray(value)) {
    validateJsonArrayContents(value, path)
    return
  }

  if (isPlainObject(value)) {
    validateJsonObjectContents(value, path)
    return
  }

  fail(path, 'must be a JSON value')
}

function validateJsonArrayContents(value: unknown[], path: string): void {
  for (const field of Reflect.ownKeys(value)) {
    if (field === 'length') {
      continue
    }

    if (
      typeof field !== 'string' ||
      !isArrayIndex(field, value.length)
    ) {
      fail(propertyPath(path, field), 'is not a JSON array property')
    }
  }

  for (let index = 0; index < value.length; index += 1) {
    const itemPath = `${path}[${index}]`

    if (!Object.hasOwn(value, index)) {
      fail(itemPath, 'must be a JSON value')
    }

    validateJsonValue(value[index], itemPath)
  }
}

function validateJsonObjectContents(value: ObjectRecord, path: string): void {
  for (const field of Reflect.ownKeys(value)) {
    if (typeof field !== 'string') {
      fail(propertyPath(path, field), 'is not a valid JSON object key')
    }

    validateJsonValue(value[field], propertyPath(path, field))
  }
}

function assertUniqueIds(
  ids: readonly string[],
  collection: 'nodes' | 'edges',
): void {
  const seenIds = new Set<string>()

  ids.forEach((id, index) => {
    if (seenIds.has(id)) {
      fail(
        `${collection}[${index}].id`,
        `is a duplicate ID "${id}" in ${collection}`,
      )
    }

    seenIds.add(id)
  })
}

function isObjectRecord(value: unknown): value is ObjectRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isPlainObject(value: unknown): value is ObjectRecord {
  if (!isObjectRecord(value)) {
    return false
  }

  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function isArrayIndex(value: string, length: number): boolean {
  const index = Number(value)
  return Number.isInteger(index) && index >= 0 && index < length && String(index) === value
}

function propertyPath(path: string, field: PropertyKey): string {
  const fieldName = String(field)
  return path === '' ? fieldName : `${path}.${fieldName}`
}

function fail(path: string, reason: string): never {
  const fieldPath = path === '' ? 'document' : path
  throw new GraphDocumentError(
    'invalid-document',
    `Invalid graph document: ${fieldPath} ${reason}`,
  )
}
