---
name: log-as-lean-linear-story
description: Turn a conversation, investigation, research trail, or collection of questions into one detailed, lean, linear explanation. Use when the user asks to log, document, consolidate, or rewrite a discussion as a coherent story or lifecycle; to preserve every material question or doubt without following chronological question-and-answer order; or to introduce and explain each concept once without redundancy.
---

# Log as a lean linear story

Produce one canonical explanation that a first-time reader can follow without seeing the source conversation.

## Required result

1. Give the document one organising spine, such as an entity's lifecycle, a request and response, an input becoming an output, or a system boundary crossed in sequence.
2. Start from the concrete state the reader already understands.
3. Move forwards through causes, transformations, boundaries, and outcomes in the order needed to understand them.
4. Introduce every concept at the first point where the story requires it, explain it completely there, and do not explain it again.
5. Preserve exact observations, commands, values, and unresolved uncertainties when they materially support the explanation.
6. End when the lifecycle or explanation is complete. Do not append a recap that repeats it.

## Treat the conversation as source material

Use the user's questions, doubts, corrections, and repeated requests as a private completeness checklist. They must not determine the document's structure.

- Merge all discussion of the same concept into one definitive explanation.
- Preserve the corrected understanding, not the sequence of misunderstandings that produced it.
- Include a historical correction only when it prevents a real footgun or explains why a tempting interpretation is wrong.
- Distinguish what was observed, what was inferred from it, and what remains unknown.
- Retain the level of detail needed to answer every material doubt, but remove repeated framing, repeated definitions, and conversational detours.

Do not produce a transcript, timeline of questions, frequently asked questions list, catalogue of corrections, or sections such as "What we discussed". Those formats make repeated questions become repeated explanations.

## Build the story

1. Inventory the source material silently.

   1. List every material concept, observation, question, correction, and uncertainty.
   2. Group repeated items by the underlying concept they test.
   3. Identify dependencies: what must be understood before each concept makes sense.

2. Choose the single clearest route through those dependencies.

   1. Prefer the real lifecycle of the entity being explained.
   2. If there is no lifecycle, use a cause-to-effect or input-to-output progression.
   3. Use headings only to mark meaningful stages within that same progression.

3. Write each concept once and for all.

   1. Define it in plain language.
   2. Explain why it exists or matters at this point in the story.
   3. Show how it changes or constrains what happens next.
   4. Use a concrete example when abstraction alone would leave the original doubt unresolved.

4. Audit the finished document.

   1. Does it answer every material question or doubt from the source?
   2. Does each concept have exactly one canonical explanation?
   3. Can a new reader proceed from top to bottom without needing a later section to understand an earlier one?
   4. Have chronological residue, false starts, and duplicated summaries been removed?
   5. Are observation, inference, and uncertainty clearly separated?

## Keep detail lean

"Lean" means every included detail earns its place; it does not mean brief.

- Include mechanisms and transitions needed to make the lifecycle intelligible.
- For a transformation, show the relevant state before it, the operation, and the state after it.
- Prefer a concrete worked example over several restatements of the same rule.
- Preserve terminology needed for precision, defining it before use.
- Omit implementation trivia, adjacent concepts, and background that do not resolve a source doubt or connect the story.

When another skill writes the result to Notion, a file, or another system, use this skill to shape the content and the other skill to perform the write.
