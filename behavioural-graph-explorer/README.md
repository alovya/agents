# Behavioural graph explorer

`bgexp` shows one behavioural graph — a workflow's steps, branches, retries, and loops — as a diagram you can explore scope by scope.

It is a viewer only. You bring a JSON document describing the workflow, usually written by an agent, and `bgexp` validates it and draws it. It never calls an agent, runs prompts, or edits your graph.

## Install

You need Node 22 or later. Run both commands from this directory, `agents/behavioural-graph-explorer`, since that is where `package.json` lives:

```bash
cd agents/behavioural-graph-explorer
npm install
npm link
```

`npm link` makes the `bgexp` command available from **any** directory afterwards. It points back at this checkout, so pulling changes updates the command with no rebuild. Every other `npm` command below must still be run from here.

## Open a graph

```bash
bgexp /tmp/ralph-loops.json
```

This starts a local server and opens the graph in your browser. Stop it with `Ctrl-C`.

Run `bgexp` with no argument to open the built-in sample graph instead, then load your own document from inside the app in either of two ways:

1. Paste JSON into **Behavioural graph JSON** and choose **Load JSON**.
2. Choose **Choose JSON file** and pick a `.json` file.

A valid document replaces what is on screen and resets the view to the top scope. An invalid one changes nothing and prints the reason underneath the textarea, so you can fix the JSON and retry without losing your place.

## Explore the graph

The graph opens at its top scope with everything collapsed, so you see a handful of high-level behaviours rather than all fifty. Purple cards are composites, which contain more behaviour; green cards are leaves.

On a composite card:

1. **Expand** replaces that card with its contents, in place.
2. **Open scope** zooms into that card so it fills the view on its own.

In the toolbar:

1. **Expand one level** expands every composite currently visible.
2. **Expand all** expands everything below the current scope at once.
3. **Undo last view change** steps back through expansions and scope changes, including leaving a scope you opened.
4. **Clear selected arrows** removes the emphasis from every arrow currently visible.
5. **Clear selected nodes** removes the current node highlighting without changing arrow emphasis.

Click an arrow to bold it, so you can trace one path through a busy diagram; click it again to unbold. Bolding several arrows at once is fine. Click cards to toggle multiple node highlights, and click empty space to clear the node and edge selection. Drag to pan, scroll to zoom, and use the on-screen controls to fit the graph to the window. Nothing you do here changes the document.

The status line above the graph tells you how many composites are visible and how many more are still hidden below the current scope.

## Write a graph document

A document is flat: every node names its parent, and every arrow names the two leaves it joins. A minimal complete example, ready to paste in:

```json
{
  "rootId": "workflow",
  "nodes": [
    { "id": "workflow", "label": "Release workflow", "kind": "composite", "parentId": null },
    { "id": "prepare", "label": "Prepare release", "kind": "composite", "parentId": "workflow" },
    { "id": "receive-input", "label": "Receive release input", "kind": "leaf", "parentId": "prepare" },
    { "id": "validate-input", "label": "Validate release input", "kind": "leaf", "parentId": "prepare" },
    { "id": "execute", "label": "Execute release", "kind": "composite", "parentId": "workflow" },
    { "id": "run-release", "label": "Run release", "kind": "leaf", "parentId": "execute" },
    { "id": "recover-release", "label": "Recover failed release", "kind": "leaf", "parentId": "execute" }
  ],
  "edges": [
    { "id": "input-to-validation", "from": "receive-input", "to": "validate-input", "label": "received" },
    { "id": "validation-to-run", "from": "validate-input", "to": "run-release", "label": "valid" },
    { "id": "run-to-recovery", "from": "run-release", "to": "recover-release", "label": "retry" },
    { "id": "recovery-to-input", "from": "recover-release", "to": "receive-input", "label": "try again" }
  ]
}
```

Those four arrows form a loop back to the start, which is exactly what you want when the workflow really does retry. Loops are valid and are drawn as loops.

Three rules catch most mistakes:

1. **Arrows join leaves, never composites.** When a composite is collapsed, `bgexp` draws the summary arrow for you, so do not write one yourself.
2. **Every composite needs at least two children.** A composite with one child adds a level without adding information.
3. **Every node must reach `rootId` through its parents.** The root is the only node with `parentId: null`, and it must be a composite.

The full field-by-field shape, the complete validation rules, and guidance for agents generating documents are in [ARCHITECTURE.md](ARCHITECTURE.md#graph-document-format).

## When something goes wrong

**"Invalid graph document: …" under the textarea.** The message names the exact field, for example `nodes[7].parentId must name an existing composite node`. The graph on screen is untouched, so fix that field and load again.

**`bgexp` exits immediately with an ENOENT error.** The path does not exist. If you are working over VS Code Remote or a cloud VM, remember the path is read on the *remote* machine, not your laptop. Use **Choose JSON file** instead to load a file from your laptop.

**The browser did not open.** `bgexp` prints the local URL; open it by hand. Over VS Code Remote the port is forwarded automatically, so the same URL works on your laptop.

**The page says "Calculating graph layout…" and stays there.** Layout runs in the browser tab. For a very large document give it a moment; if it never settles, the console will carry the error.

## Develop

From `agents/behavioural-graph-explorer`:

```bash
npm run dev     # dev server, no graph argument
npm test        # Vitest, no browser needed
npm run lint    # oxlint
npm run build   # type-check and bundle into dist/
```

`bgexp` runs straight from source and never needs `npm run build`; no `dist/` directory is committed. To run the launcher without linking, use `npm run bgexp` from the project directory.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how the viewer is put together and why `bgexp` works the way it does.
