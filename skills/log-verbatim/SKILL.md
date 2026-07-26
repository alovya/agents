---
name: log-verbatim
description: Reproduce prose the assistant already wrote, word-for-word, into a log, file, or message, reflowing only formatting to fit the destination. Use when the user asks to log, save, or capture something "verbatim", "word-for-word", "as you had it", or "prose only", or to replace an earlier paraphrased or summarised log with the exact wording.
---

# Log verbatim

Reproduce prose the assistant already produced, unchanged. The user wants the exact words preserved; only the presentation may adapt to the destination.

## What verbatim means

1. Copy the wording exactly: same sentences, same order, same terminology. Do not paraphrase, summarise, compress, expand, reorder, "improve", or silently correct it.
2. Change only presentation to fit the destination. Convert Markdown headings and lists into the destination's block types, wrap inline technical names in backticks where the destination expects it, and split running text into paragraphs. The words inside must not change.
3. If you genuinely must alter a word, for example a cross-reference that no longer resolves in the new location, flag the change explicitly rather than editing it in silence.

## Prose only

1. Drop conversational scaffolding: greetings, lead-ins such as "here's...", offers such as "want me to...", and questions back to the user.
2. Keep inline technical names such as paths, functions, flags, and literal values that sit inside sentences; they are part of the prose.

## Source and scope

1. The source is what the assistant already wrote earlier in this conversation, not a fresh composition. Find that passage and reproduce it.
2. If several passages cover the topic, reproduce the latest, most-corrected wording the user is pointing at; do not merge earlier drafts into it.
3. When replacing an earlier paraphrased entry in an append-only log, state plainly in the new entry that it is the verbatim version, since the paraphrase remains on the record.

## Writing it

When another skill owns the write, such as a Notion log or a file, use this skill to select and preserve the content and the destination skill to perform the write. Match the destination's structure: for a Notion timeline log, give it a concise title and paragraph blocks, keeping code blocks only if the user kept them.