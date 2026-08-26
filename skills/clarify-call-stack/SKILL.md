---
name: clarify-call-stack
description: Explain a module, command, program, function or error to the user by clarifying its call stack.
disable-model-invocation: true
---

# Clarify the call stack

Use this skill to explain a module, command, program, function or error to the user by clarifying its call stack and understanding its execution path.

## Principles

**Initial state matters a lot.** Lay out the initial program, environment and/or machine state clearly and sensibly: reasoning about execution paths is impossible without knowing where we start from.

**Think carefully about when your explanation should step into or step over the stack.** Make judgement calls on whether your explanation should step into or step over a function. For example, if the user is asking about a specific function, gradually stepping into it from the entrypoint at the top probably makes more sense, whereas if the user is asking about a module or program, stepping over functions to clarify the higher-level execution path is probably more useful.