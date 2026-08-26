---
name: literal-example
description: Explain a design, error, or code path using a literal, concrete example. Use when the user asks to explain something "with an example", "concretely", or says an explanation is too abstract.
disable-model-invocation: true
---

# Literal example

Use this skill when an explanation of a design, error, or code path needs a concrete example rather than abstract description.

## Workflow

1. Identify the exact thing to explain: a design decision, an error, or a code path.
2. Pick or construct one literal example: real input values, a real stack trace, a real file and line, or a real sequence of calls. Prefer an example already present in the code, logs, or conversation over an invented one.
3. Walk through that example step by step, showing concrete values at each step rather than describing the shape of values in general terms.
4. Only after the concrete walkthrough, add the minimum general statement needed to generalise beyond the example, if the user needs it.

## Guardrails

- Use British spelling.
- Do not replace the concrete example with a restatement in the abstract; the example must carry the explanation.
- If no real example is available, say so and construct a plausible one explicitly labelled as illustrative, rather than presenting it as observed.
