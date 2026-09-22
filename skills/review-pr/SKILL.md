---
name: review-pr
description: Review a pull request.
---

# Review a pull request

Use this skill to review a pull request.

## Principles

**Be friendly, but ultimately adversarial (to the code).** We are friendly with our colleagues, we always speak respectfully and in good faith, but when reviewing a PR, we are adversarial to the code: we are actively and pedantically trying to find problems, regressions and improvements.

**Code diffs are incomprehensible; behaviours actually make sense.** Code diffs, which also often appear in non-linear, non-execution order, make basically zero sense to human readers without understanding the behaviour they are changing: when reviewing a pull request, focus on the behaviour that is being changed, and how the code diff is effecting it.

**Explain as before-and-after behaviour.** Explain the behaviours of interest using the /write-step-by-step-explanation skill: explain what the behaviour was before, then explain what it is after.

**Accompany explanations with code snippets.** When explaining behaviours, include relevant code snippets in your prose/under your bullets; `file:line` references should also be included, but in-line code snippets are preferred, since that way the review can be read on the spot without having to constantly refer back to source code.

**Recommend a good reading order.** On sites like GitHub or GitLab, files are shown in something like the alphabetical order of their filenames, which is a truly awful order for reviewing a PR. Instead, suggest a better reading order, e.g. a spine that follows the logical flow of the code or the main execution path(s).

**Call things out only after you have reasoned about the PR.** Only after you have reasoned about the PR according to the principles above, call things out: bugs, fixes, code quality improvements, better testing, alternative designs, etc - avoid premature judgment. For every thing you call out, give immediately actionable, concrete and specific feedback, not vagueries or mere suggestions.