# Architecture

This document explains how `bgexp` is put together, for anyone changing it. If you only want to use it, [README.md](README.md) is enough.

## Graph document format

A document is one flat object. Nesting is expressed by each node naming its parent, not by nesting the JSON, which keeps validation and projection simple:

```ts
type GraphDocument = {
  rootId: string
  nodes: readonly GraphNode[]
  edges: readonly GraphEdge[]
}

type GraphNode = {
  id: string
  label: string
  kind: 'leaf' | 'composite'
  parentId: string | null
  metadata?: Readonly<Record<string, unknown>>
}

type GraphEdge = {
  id: string
  from: string
  to: string
  label?: string
}
```

`src/graph/graph-document-json.ts` accepts a document only if all of the following hold. Each failure names the offending field, for example `nodes[7].parentId must name an existing composite node`.

1. The document, every node, and every edge is a **closed** object: unknown properties are rejected rather than ignored, so a typo like `parent` instead of `parentId` fails loudly. The single exception is `metadata`, whose own contents are opaque.
2. `rootId`, node IDs, node labels, edge IDs, and edge endpoints are non-empty strings. Node IDs are unique among nodes, edge IDs are unique among edges, and node and edge IDs occupy separate namespaces. `kind` is exactly `leaf` or `composite`.
3. `rootId` names a composite whose `parentId` is `null`. Every other node reaches the root through existing composite parents, so containment cycles and orphans are invalid.
4. Every composite has at least two direct children, and every leaf has none. Nested composites count as children.
5. Every edge endpoint names an existing **leaf**. Zero edges is valid. Directed cycles between leaves, retries, and opposing pairs are all valid and are preserved.
6. `metadata`, when present, is a plain JSON object. Its values may be any JSON, including nested objects and arrays, but not functions, `NaN`, or `Infinity`.
7. An edge `label` is optional, and must be a non-empty string when present.

Rule 4 is a deliberate tightening: a composite with one child adds a level of indirection without adding information, so the viewer refuses it rather than drawing it.

### Generating a document from a procedure

When an agent turns a real procedure into a document, the behaviour is the source of truth, not the code layout:

1. Identify the composite semantic scopes in the procedure.
2. Classify each action. A composite holds an internal sequence, decision, retry, recovery path, or loop; a leaf is one action, outcome, or decision shown completely in its parent.
3. Give each composite a meaningful label and a stable ID.
4. Preserve normal flow, decisions, retries, recovery, pauses, and loops, including every cycle's return path.
5. Express control flow **only** as directed edges between leaves.
6. Emit the whole canonical graph, not the projection visible at one scope. Composite-to-composite arrows are derived at projection time, so authoring them duplicates information and produces double arrows.

## The rendering pipeline

The accepted `GraphDocument` is the source of truth and is never mutated. Everything on screen is derived from it in four stages:

1. **Project** — `src/graph/project-visible-graph.ts` walks the current scope's children, substituting a composite's contents wherever it has been expanded, and produces a `VisibleGraph`. Canonical leaf edges whose endpoints are currently hidden are lifted to the nearest visible ancestor, and several canonical edges collapsing onto the same pair become one summary edge that records its `underlyingEdgeIds`. Edges within a single visible node are dropped.
2. **Lay out** — `src/layout/dagre-layout.ts` gives Dagre the projection and reads back node positions *and* edge route points. Keeping the routes matters: React Flow's own `smoothstep` would discard them and route straight through node boxes.
3. **Adapt** — `src/rendering/react-flow-adapter.ts` converts the projection plus layout into React Flow nodes and edges, choosing which of a card's four handles each edge attaches to, and giving a pair of opposing edges separate lanes so they do not overlap.
4. **Render** — `src/app/App.tsx` renders the result and `src/ui/graph-node-card.tsx` draws each card. `src/rendering/dagre-edge.tsx` draws each edge along its Dagre route via `BaseEdge`, with the path built by `src/rendering/dagre-edge-path.ts`.

Layout cannot guarantee zero edge crossings for a non-planar graph. Dagre substantially reduces crossings and node overlaps; ELK would do better and remains optional future work.

## State

Two pieces of state, deliberately separate:

1. `ExplorationState` in `src/exploration/explore-graph.ts` — current scope, scope path, expanded node IDs, and selection. Every transition is a pure function returning either a new state or the identical object when nothing changed, which is what lets buttons disable themselves precisely.
2. `ActiveGraph` in `src/exploration/active-graph.ts` — the document, its exploration state, and a history of view snapshots. Only transitions that change the projection are recorded, so **Undo last view change** steps through expansions and scope changes without replaying selections.

Bolded edge IDs live in `src/app/App.tsx` rather than in exploration state, because they are presentation and do not affect projection.

`projectionRevision` is a counter incremented by projection-changing transitions. It is the signal that triggers relayout.

### Discarding stale layout

Layout is asynchronous, so two overlapping runs can finish out of order. `src/app/apply-latest-layout.ts` guards against that twice:

1. `createLatestLayoutRunner` issues a token per request and applies a result only if its token is still the latest, so a slow earlier run cannot overwrite a newer one.
2. `canRenderLayoutForGraph` compares the stored `VisibleGraph` by reference against the current one, so a layout is drawn only alongside the exact projection it was computed for.

Without the second check, expanding a scope would hand the adapter a new projection with old coordinates, and it would throw `Missing layout position for visible node: …`.

## How `bgexp` reaches a browser

A browser tab cannot read the filesystem, so naming a file on the command line requires a server to hand it over. `bin/bgexp.mjs` is that bridge, and it is intentionally thin:

1. It resolves the path argument and reads the file immediately, so a missing file fails at once with a real error instead of a blank page.
2. It spawns Vite from the package's own `node_modules`, passing the resolved path in `BGEXP_GRAPH_FILE_PATH`.
3. It passes `--open /?graphFile=/__bgexp/graph.json`, so Vite starts and opens the browser at a URL carrying a **pointer**, not the document.
4. A plugin in `vite.config.ts` serves that route by reading `BGEXP_GRAPH_FILE_PATH` from disk.
5. `src/app/load-requested-graph.ts` fetches that route, and `App.tsx` guards against a stale response overwriting a document the user has since loaded by hand.

The document travels as an HTTP response body because an earlier design base64-encoded it into the URL, and a 42KB document produced a 57,000-character URL that exceeded Node's header limit, giving `431 Request Header Fields Too Large`. That failed only above a size threshold, so small graphs hid the bug.

The plugin exists only in `configureServer`, so `?graphFile=` works under `bgexp` and `npm run dev` but not in a built `dist/`, where no server is left to read the filesystem.

A document is otherwise only ever passed as an HTTP body or picked from a file dialogue. There is no mode that carries a document inside a URL.

## Module map

```text
bin/bgexp.mjs            launcher: reads the path, starts Vite, opens the browser
vite.config.ts           dev server plus the /__bgexp/graph.json route

src/main.tsx             browser entrypoint
src/app/                 the shell and what it starts
  App.tsx                state, exploration callbacks, toolbar, graph panel
  load-requested-graph.ts   initial document, sample fallback, graph-file fetch
  apply-latest-layout.ts    discards stale layout results
src/graph/               the document itself
  graph-document.ts      document and projection types
  project-visible-graph.ts  projection to a VisibleGraph
  graph-document-json.ts    parsing and validation, GraphDocumentError
  sample-graph.ts        the built-in starting document
src/exploration/         what the user is looking at
  explore-graph.ts       scope, expansion, and selection transitions
  active-graph.ts        active document plus view history and undo
src/layout/              geometry
  dagre-layout.ts        Dagre positions and edge routes
src/rendering/           React Flow specifics
  react-flow-adapter.ts  projection plus layout to React Flow nodes and edges
  dagre-edge.tsx         custom edge drawing a Dagre route
  dagre-edge-path.ts     Dagre route points to an SVG path
src/ui/                  presentation
  graph-import.tsx       the paste and file-choose controls
  graph-node-card.tsx    one node card with its handles and buttons
```

The folders answer different questions, so a reader can start from the one they need: `graph/` is what the document *is*, `exploration/` is what the user is *looking at*, `layout/` is *where* things go, `rendering/` is *how* they are drawn, and `app/` wires those together. Two placements are deliberate: `dagre-edge-path.ts` sits with the edge that consumes it rather than with Dagre, and `apply-latest-layout.ts` sits with the shell because it schedules layout rather than computing it.

Tests are colocated as `*.test.ts` beside each module and run in Node under Vitest, with no DOM environment and no component-testing library.

## Deliberate constraints

1. **Read-only.** No editing, no persistence, no backend, no authentication, no agent runtime. An external agent emits a document; this viewer validates and draws it.
2. **Canonical edges join leaves.** Containment implies no ordering, and composite summaries are derived, so the same document renders consistently at every scope and expansion level.
3. **Cycles stay visible.** A retry loop in a real workflow is information, not a defect to be flattened.
4. **Few dependencies.** React, React Flow, and Dagre. No Mermaid, no ELK, no validation library, no state-management library.
5. **No committed build output.** `bgexp` runs from source, so the command tracks the checkout.

## Known rough edges

1. `LaidOutGraph` pairs a `VisibleGraph` with a `LayoutResult` but lives in `app/`, so a layout type sits outside `layout/`. It is there because the question it answers — is the layout I hold still current? — belongs to the shell.
2. `react-flow-adapter.ts` scans every edge to find each edge's opposing partner, which is quadratic. Irrelevant at present graph sizes.
3. `canClickInto` and `canExpand` on a node card are both exactly `kind === 'composite'`, so one carries no information.
4. `bin/bgexp.mjs` still moves the document through a fetched route. Inlining the JSON into `index.html` via `transformIndexHtml` would remove the route, the query parameter, the fetch, and its staleness guard.
