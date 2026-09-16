---
name: construct-behavioural-graph
description: Explain a concept, behaviour, problem, or error as a behavioural graph, expressed as a schema-compliant JSON.
---

# Explain behaviour as a graph

Use this skill to explain behaviour as a flowchart, i.e. a graph. At heart, this skill is the graphical counterpart of the /write-step-by-step-explanation skill, so please do use the latter skill.

## Policies

**Construct a schema-compliant JSON.** Please return your explanation entirely in the JSON format shown below, otherwise it will not pass the graph explorer's validation; it has the following schema:

```json
{
  "rootId": "root",
  "nodes": [
    {
      "id": "root",
      "label": "Behavioural workflow",
      "kind": "composite",
      "parentId": null
    },
    {
      "id": "preparation",
      "label": "Prepare input",
      "kind": "composite",
      "parentId": "root",
      "metadata": {
        "role": "preparation scope"
      }
    },
    {
      "id": "receive-input",
      "label": "Receive input",
      "kind": "leaf",
      "parentId": "preparation"
    },
    {
      "id": "checks",
      "label": "Check input",
      "kind": "composite",
      "parentId": "preparation"
    },
    {
      "id": "validate-input",
      "label": "Validate input",
      "kind": "leaf",
      "parentId": "checks"
    },
    {
      "id": "inspect-input",
      "label": "Inspect input",
      "kind": "leaf",
      "parentId": "checks"
    },
    {
      "id": "normalise-input",
      "label": "Normalise input",
      "kind": "leaf",
      "parentId": "preparation"
    },
    {
      "id": "execution",
      "label": "Execute workflow",
      "kind": "composite",
      "parentId": "root"
    },
    {
      "id": "select-action",
      "label": "Select action",
      "kind": "leaf",
      "parentId": "execution"
    },
    {
      "id": "apply-action",
      "label": "Apply action",
      "kind": "leaf",
      "parentId": "execution"
    },
    {
      "id": "report",
      "label": "Report result",
      "kind": "leaf",
      "parentId": "root"
    }
  ],
  "edges": [
    {
      "id": "receive-to-validate",
      "from": "receive-input",
      "to": "validate-input",
      "label": "check received input"
    },
    {
      "id": "validate-to-inspect",
      "from": "validate-input",
      "to": "inspect-input"
    },
    {
      "id": "inspect-to-normalise",
      "from": "inspect-input",
      "to": "normalise-input"
    },
    {
      "id": "normalise-to-select",
      "from": "normalise-input",
      "to": "select-action"
    },
    {
      "id": "select-to-apply",
      "from": "select-action",
      "to": "apply-action"
    },
    {
      "id": "apply-to-select",
      "from": "apply-action",
      "to": "select-action",
      "label": "continue or retry"
    },
    {
      "id": "apply-to-report",
      "from": "apply-action",
      "to": "report"
    },
    {
      "id": "select-to-receive",
      "from": "select-action",
      "to": "receive-input",
      "label": "restart preparation"
    }
  ]
}
```

The JSON must satisfy every rule below:

- The top level is an object containing `rootId` (a non-empty string), `nodes` (an array), and `edges` (an array).
- Every node has a unique, non-empty string `id`, a non-empty string `label`, `kind` equal to `leaf` or `composite`, and `parentId` equal to a string or `null`.
- Node IDs are unique. Edge IDs are also unique, non-empty strings; node and edge IDs have separate namespaces.
- `rootId` names exactly one node. The root is composite and has `parentId: null`; every other node has a non-null parent.
- Every non-root parent ID names an existing composite. Every node is reachable from the root, and containment has no cycles.
- Every composite has at least two direct children. A leaf has no children. Nested composites count as children.
- Every edge has a unique, non-empty string `id` and non-empty string `from` and `to` fields. `from` and `to` name existing leaf nodes. An optional edge `label` is a string.
- An optional node `metadata` value is a non-null JSON object. Its contents are opaque.
- Canonical edges describe control flow only; they do not describe containment or authored composite summaries.
- Directed control-flow cycles are valid and must be retained; containment cycles are invalid.
- The document is complete canonical graph data, not a collapsed projection or a partial visible graph.

Emit nodes in parent-first source order. Emit the complete canonical graph, not a collapsed view, partial summary, Mermaid chart, or SVG.

Before returning the JSON, check that every source behaviour has an appropriate node or transition, every branch and loop is represented, every edge endpoint is a leaf, and no behaviour has been invented or lost.

**Leaf nodes in the JSON need not be the genuinely lowest-level behaviours.** The JSON uses leaf nodes merely as its chosen behavioural units: a composite node contains two or more nodes (leaf or composite), but a leaf may still contain finer behaviour conceptually. In other words, leaf nodes need not be the semantically or code-syntactically lowest-level behaviours or implementation details: go only as low as the user asks, and only go deeper if requested.