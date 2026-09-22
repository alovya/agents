---
name: change-without-breaking
description: Change something without breaking any of its producers, consumers or integrations, making sure they still work.
---

# Change without breaking

Use this skill to change something, e.g. some behaviour, code, config, etc, without breaking any of its producers, consumers or other integrations.

# Principles

**Changing some thing is not just changing that thing.** When changing something, it is really bad to change it without also considering the knock-on effects of the change on every single producer, consumer and integration of that thing. For every change you wish to make, find every single producer, consumer and integration, spell out how each will be affected, and ensure you are aware of every single knock-on effect before proceeding. Identify every single knock-on effect using the /find-root-cause skill.