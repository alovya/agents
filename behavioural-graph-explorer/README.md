# Behavioural Graph Explorer

A read-only Vite React application for exploring a complete in-code behavioural graph.

## Install

```bash
npm install
```

## Development

```bash
npm run dev
```

Open the local URL printed by Vite.

## Test and build

```bash
npm test
npm run lint
npm run build
```

## Interaction

- The application starts with the root scope collapsed. Composite scopes and leaf behaviours use distinct cards, and each card is 220×96 pixels.
- Select a node or directed edge to inspect the current selection. Click the canvas background to clear selection.
- Use **Open scope** on a composite to enter it. **Back to enclosing scope** returns to the previous navigation entry and is disabled at the root.
- Use **Expand** for one composite, **Expand one level** for all composites currently visible, or **Expand all** for every composite below the current scope.
- The graph is read-only. Use the React Flow controls or pointer gestures to pan and zoom.
