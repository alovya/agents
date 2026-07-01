---
name: explain-step-by-step-code-path
description: Explain a code path as a high-level, step-by-step story. Use when the user asks to understand how code behaves, asks for a step-by-step code path, or wants PR review help by comparing the code path before and after a change.
---

# Explain step-by-step code path

Use this skill to turn code behaviour into a readable story. It is especially useful when the user wants to understand an existing implementation, or when reviewing a PR by comparing what the code did before and what it does after.

## Workflow

1. Identify the behaviour the user wants explained.
   1. Find the user-facing entrypoint, call site, test, command, or PR comment that exposes the behaviour.
   2. If the request is about a PR, inspect the relevant changed files and comments before explaining.
   3. Prefer local source and tests over guessing from names.

2. Trace the code path from entrypoint to effect.
   1. Follow the actual calls, data transformations, branches, validation, mutation, persistence, rendering, or external calls.
   2. Stop at the lowest level needed for the user to understand the behaviour.
   3. Do not drown the explanation in leaf-helper mechanics unless the leaf helper is the behaviour being questioned.

3. Explain the path as a story.
   1. Use rendered Markdown with ordinary numbered lists.
   2. Use nested numbered lists when a step has substeps.
   3. Name the function, method, file, or module that owns each step.
   4. Explain what data looks like before and after important transformations.
   5. Keep the first pass behavioural: what happens, in what order, and why each step exists.

4. For PR review, explain before and after separately.
   1. Start with the old code path.
   2. Then explain the new code path.
   3. Compare the behavioural effect, exported graph shape, API contract, performance risk, test coverage, or failure mode that changed by framing it in the context of the code path.
   4. Say whether the comment is worth addressing, and whether the right answer is code, test, documentation, or a reply.

5. Call out messy boundaries.
   1. If one function mixes orchestration, parsing, mutation, validation, rendering, or persistence, say that explicitly.
   2. If the explanation requires jumping across too many helpers, identify which helper or orchestrator name is hiding intent.
   3. Suggest the smallest change that would make the path easier for a first-time reader.

## Output shape

Prefer this shape when it fits:

1. `<Entry function or call site>` receives `<input or state>`.
   1. `<Concrete example or important shape>`.
   2. `<Immediate validation or branching>`.

2. `<Next function>` turns `<old shape>` into `<new shape>`.
   1. `<Important transformation>`.
   2. `<Why that transformation matters>`.

3. `<Final owner>` produces `<observable behaviour>`.
   1. `<Return value, mutation, side effect, emitted graph, written file, or user-visible result>`.

For PR comparisons:

## Before

1. ...

## After

1. ...

## What changed

1. ...

## Worth addressing?

1. ...

## Guardrails

- Use British spelling.
- Explain behaviour before implementation structure.
- Do not use historical context unless it prevents a real footgun.
- Do not present speculation as fact; mark inferences clearly.
- Use file links when local files are relevant.
