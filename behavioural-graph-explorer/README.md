# Behavioural Graph Explorer

Behavioural Graph Explorer (BGE) is a read-only viewer for one complete behavioural graph document. It starts with a trusted in-code sample, then lets you replace that sample with a document emitted by an external skill or agent. BGE does not call an agent, run prompts, or provide an agent runtime: the external skill or agent emits the complete JSON document, and BGE validates and displays it.

## Use BGE

Paste one complete graph document into **Graph document JSON** and choose **Load JSON**, or choose a `.json` file. A successful load replaces the current document, resets exploration to its root scope, and calculates a fresh layout. A rejected document leaves the displayed graph and its current exploration unchanged while reporting the validation error in the live status region.

The viewer starts with the root scope collapsed. Use **Open scope** to enter a composite, **Back to enclosing scope** to return, and **Expand**, **Expand one level**, or **Expand all** to reveal nested scopes. Select nodes or directed edges to inspect them. The graph cannot be edited; React Flow controls and pointer gestures provide pan and zoom.

## Graph JSON contract

The accepted JSON has this exact flat shape:

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

BGE validates these rules:

1. The document, every node, and every edge is a closed object. Unknown top-level, node, and edge properties are rejected. `metadata` is the exception to closed contents: its own contents are opaque JSON.
2. `rootId`, node IDs, node labels, edge IDs, and edge endpoints are strings as required by the shape. IDs, node labels, and a present edge `label` must be non-empty. Node IDs are unique among nodes, edge IDs are unique among edges, and `kind` is only `leaf` or `composite`.
3. `rootId` must resolve to a composite node whose `parentId` is `null`. Every other node must resolve through existing composite parents to that root. Containment cycles and orphaned nodes are invalid.
4. Every composite must have at least two direct children, and every leaf must have no children. This is a deliberate BGE domain tightening beyond the frozen prototype specification.
5. Every canonical edge endpoint must be an existing leaf. Zero edges are allowed. Leaf-level directed cycles, retries, and opposite edges are allowed.
6. `metadata` is optional. When present, it must be a JSON object; its contents may be any JSON values and are treated as opaque. An edge `label` is optional, but it must be a non-empty string when present.
7. Canonical leaf edges are authored in the document. Visible composite-to-composite summary arrows are derived during projection, so do not add duplicate authored edges for those summaries.

Here is a complete valid document that can be pasted directly into the viewer:

```json
{
  "rootId": "workflow",
  "nodes": [
    {
      "id": "workflow",
      "label": "Release workflow",
      "kind": "composite",
      "parentId": null,
      "metadata": {
        "owner": "delivery",
        "readOnly": true,
        "tags": ["example", "cycle"]
      }
    },
    {
      "id": "prepare",
      "label": "Prepare release",
      "kind": "composite",
      "parentId": "workflow",
      "metadata": {
        "purpose": "check and normalise the release input"
      }
    },
    {
      "id": "receive-input",
      "label": "Receive release input",
      "kind": "leaf",
      "parentId": "prepare"
    },
    {
      "id": "prepare-checks",
      "label": "Run preparation checks",
      "kind": "composite",
      "parentId": "prepare"
    },
    {
      "id": "validate-input",
      "label": "Validate release input",
      "kind": "leaf",
      "parentId": "prepare-checks"
    },
    {
      "id": "normalise-input",
      "label": "Normalise release input",
      "kind": "leaf",
      "parentId": "prepare-checks"
    },
    {
      "id": "execute",
      "label": "Execute release",
      "kind": "composite",
      "parentId": "workflow",
      "metadata": {
        "retryLimit": 2,
        "pauseAllowed": true
      }
    },
    {
      "id": "run-release",
      "label": "Run release",
      "kind": "leaf",
      "parentId": "execute"
    },
    {
      "id": "recover-release",
      "label": "Recover failed release",
      "kind": "leaf",
      "parentId": "execute"
    }
  ],
  "edges": [
    {
      "id": "input-to-validation",
      "from": "receive-input",
      "to": "validate-input",
      "label": "received"
    },
    {
      "id": "validation-to-normalisation",
      "from": "validate-input",
      "to": "normalise-input",
      "label": "valid"
    },
    {
      "id": "normalisation-to-run",
      "from": "normalise-input",
      "to": "run-release"
    },
    {
      "id": "run-to-recovery",
      "from": "run-release",
      "to": "recover-release",
      "label": "retry"
    },
    {
      "id": "recovery-to-input",
      "from": "recover-release",
      "to": "receive-input",
      "label": "try again"
    }
  ]
}
```

`workflow` contains the two composite scopes `prepare` and `execute`; `prepare` contains the nested composite `prepare-checks`. The edges form a leaf-level directed cycle from `receive-input` through `validate-input`, `normalise-input`, `run-release`, and `recover-release` back to `receive-input`.

## Agent generation guidance

Before emitting a document, read the complete source procedure, including its decisions, invariants, retries, recovery paths, pauses, and loops. Treat that procedure as the behavioural source of truth:

1. Identify every composite semantic scope in the procedure.
2. Classify each action as a leaf or a composite. A composite contains an internal sequence, decision, retry, recovery path, or loop; a leaf is one action, outcome, or decision shown completely in its parent.
3. Give each composite a meaningful scope label and a stable unique ID.
4. Preserve normal flow, decisions, retries, recovery, pauses, and loops. Retain every required cycle and its return path.
5. Encode control flow only as directed edges between leaf nodes.
6. Emit the complete canonical graph, not only the projection currently visible at one scope or expansion level. Composite-to-composite arrows will be derived by BGE when it projects the document.

## Development

### Install

```bash
npm install
```

### Development server

```bash
npm run dev
```

Open the local URL printed by Vite.

### Launch from the command line

After installing dependencies, link the checked-out app once:

```bash
npm link
```

Then launch it from any directory with:

```bash
bgexp
```

Pass a graph document path to load it when the app opens:

```bash
bgexp path/to/graph.json
```

The file is served through a short local route rather than embedded in the browser URL, so large graph documents do not trigger HTTP 431 errors. `bgexp` starts Vite in source mode and opens the app in the default browser. It does not require a production build or a committed `dist/` directory. You can also run it without linking from the project directory:

```bash
npm run bgexp
```

### Test, lint, and build

```bash
npm test
npm run lint
npm run build
```

## Architecture

BGE keeps the accepted flat `GraphDocument` as the source of truth. It projects the nodes and canonical leaf edges visible in the current scope, derives summary edges for collapsed descendants, lays out that projection with Dagre, carries Dagre's computed edge routes into a custom React Flow edge, and renders it with React Flow. Exploration state remains separate from the document, so loading a document can reset scope, expansion, and selection without making the graph editable.
