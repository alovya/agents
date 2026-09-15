---
name: describe-nested-behaviourial-dag
description: Describe an orchestration workflow as nested behavioural graphs with one Mermaid chart per composite semantic scope and explicit drill-down paths.
---

# Describe a nested behavioural graph

Use this skill when a workflow needs to be explained as a hierarchy of behavioural flowcharts, especially when a single chart would lose detail or become unreadable.

## Goal

Turn the authoritative workflow description into a set of Mermaid flowcharts that a reader can follow from the outer lifecycle down to the smallest composite operation without losing any behaviour, decision, retry, failure, or loop.

Preserve the user’s terminology. Do not replace a precise domain term with a vague orchestration synonym merely to make the diagram sound uniform.

## Build the semantic hierarchy first

1. Read the complete source procedure before drawing anything. Treat its numbered steps, decisions, invariants, and `go to step X.Y` routes as the behavioural source of truth.
2. Identify the scopes that contain other scopes. Typical scopes are an outer lifecycle, a command boundary, a planning operation, supervision, frontier execution, a task cycle, synthesis, and pause or stop handling.
3. Classify every node in each scope:
   - A composite node contains an internal sequence, decision, retry, recovery path, or loop.
   - A leaf node is one action, outcome, or decision shown completely in its parent.
4. Give every composite scope its own chart. Two semantically different composite scopes must not point to the same drill-down chart.
5. Do not create charts for leaf nodes. If several leaf outcomes share a parent, keep them in that parent. A shared chart is valid only for the single shared parent scope, not for each of its children.

## Arrange the charts progressively

Create the charts in containment order:

1. Command composition: show the nested command boundaries.
2. Outer lifecycle: show how the system enters, resumes, advances, synthesises, completes, pauses, or stops.
3. One chart for each composite child scope, in the same order in which it is encountered.
4. Put the full detail of each scope in its own chart. Do not compress a branch into a vague node just to keep a chart small; split the scope instead.

Each higher-level composite block must identify its one matching drill-down chart, for example:

```text
ralph supervise
open chart 5
```

Use a short legend stating that blocks labelled `open chart N` are intermediate nodes and unlabelled blocks are leaves. If a container owns several child scopes, label each child separately; do not make the container ambiguously point at a mixed chart.

## Preserve control flow exactly

Keep all of the following visible in the appropriate chart or in the accompanying numbered procedure:

- normal forward transitions;
- every readable conclusion and every unparsable or missing result;
- retries and their limits;
- recovery, repair, split, abort, pause, and resume paths;
- the exact return step for every loop;
- state and repository invariants, including when a candidate is dirty, when `HEAD` may move, and when a worker must not edit;
- the distinction between a parsed conclusion and a supervisor-inferred conclusion;
- the distinction between a repair action and an inference action.

Use the numbered procedure for detailed evidence and action text, and make the chart’s edges show where each case goes. A chart may refer to another chart when control enters that composite scope, but it must not use the reference to hide a branch.

When the workflow loops, retain the back edge. A workflow with loops is a directed behavioural graph even if the user calls it a DAG; never remove a required loop to force mathematical acyclicity.

## Audit the result

Before finishing, inspect the whole document rather than checking only the chart that was most recently edited.

1. Build a scope map: every `open chart N` label must name the chart for that node’s own composite scope.
2. Check that no leaf outcome says `open chart N`.
3. Check that semantically different composite nodes do not share a chart.
4. Check that every composite node has a chart, every chart has one semantic scope, and every chart number is unique and reachable.
5. Check that parent charts point to child charts in containment order.
6. Check that every numbered source step appears in exactly one appropriate detailed chart or is explicitly represented as a transition between charts.
7. Check every loop by following it from its decision edge to its named return step.
8. Check that no status such as `blocked`, `needs supervision`, or `synthesis failed` has been made to look like a parent merely because it shares a recovery destination. Route it through an explicitly named parent scope when one exists; otherwise leave it as a leaf.

The finished document should let a first-time reader answer, at every node:

- Is this a leaf or a composite scope?
- If it is composite, which one chart expands it?
- If it is a decision, where does each outcome go?
- If it loops or pauses, which exact numbered step resumes it?
