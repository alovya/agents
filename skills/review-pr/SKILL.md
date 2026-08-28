---
name: review-pr
description: Review a pull request.
---

# Review a pull request

Use this skill to review a pull request.

## Principles

**Code diffs are neigh incomprehensible; behaviours actually make sense.** Code diffs, which also often appear in non-linear, non-execution order, make basically zero sense to human readers without understanding the behaviour they are changing: when reviewing a pull request, focus on the behaviour that is being changed, and how the code diff is effecting it.

**Explain as before-and-after behaviour.** Explain the behaviours of interest using the /write-step-by-step-explanation skill: explain what the behaviour was before, then explain what it is after.