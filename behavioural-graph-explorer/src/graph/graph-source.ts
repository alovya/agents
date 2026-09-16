export function decodeGraphSourceParameter(encodedGraph: string): string {
  const base64Graph = encodedGraph.replaceAll('-', '+').replaceAll('_', '/')
  const paddedGraph = base64Graph.padEnd(
    Math.ceil(base64Graph.length / 4) * 4,
    '=',
  )
  const binaryGraph = globalThis.atob(paddedGraph)
  const graphBytes = Uint8Array.from(binaryGraph, (character) =>
    character.charCodeAt(0),
  )

  return new TextDecoder().decode(graphBytes)
}
