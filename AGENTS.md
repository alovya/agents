# User-specific instructions

These instructions override any repo- or subdirectory-specific instructions. If a system or developer instruction conflicts, state the conflict explicitly instead of silently ignoring the user instruction.

## Principles

Two commitments sit above the rest: please think carefully about how you work and reason, and please write code that a human can read as easily as reading a story. The rules split into how you should work and what the code should read like; within each, they run from the most general habit to the most specific choice.

### How you should work and reason

1. **Read before you write.** The biggest source of bad code is writing before reading. Read the files you are about to touch — read, not skim — copy the patterns that already exist, and check the imports to see what the project actually depends on, so you do not reach for a new library where the project already has one. When you cannot find a pattern, ask instead of guessing.

2. **Think before you code.** State your assumptions explicitly ("add authentication" is five different things, so name the one you picked) and name the tradeoffs. If something is genuinely confusing, stop and ask rather than filling the gap with plausible-looking code — that is exactly the code that passes a casual review and fails when it matters.

3. **Define the goal before coding.** Every task needs a success criterion first. "Add validation" becomes "reject a missing or malformed email, return 400 with a clear message, and test both cases." For anything multi-step, state the plan first so I can catch a wrong approach before you spend an hour building it.

4. **Keep it simple.** Write the minimum code that solves the problem in front of you now, not the minimum that could solve every future version of it. Resist premature abstraction, skip error handling for errors that cannot occur, and hardcode values until there is a real reason to configure them. If the only reason something is abstracted is "in case we need to", it is over-built. Do not add fallback behaviour, backwards-compatibility shims, or speculative input formats without a proven caller; fail fast with a clear error and let the default stack trace surface, rather than catching and repackaging, unless recovery is genuinely required.

5. **Make changes surgical.** Your diff should be as small as the task allows. Do not touch what you were not asked to touch, match the existing style, and do not reformat — a formatter pass buries the three lines that matter inside three hundred that do not. If a line is there because "while I was in there", revert it.

6. **Verify by testing.** The gap between code that works and code you think works is testing. When fixing a bug, write the failing test first, watch it fail, then fix it — that is the only proof you fixed the cause and not the symptom. Test behaviour that can actually break, not that a constructor sets a field. If something is hard to test, that is information about the design, not permission to skip it.

7. **Debug by investigation, not guessing.** Read the whole error and the stack trace, reproduce the problem before you change anything, and change one thing at a time. Do not paper over an unexpected null with a null check; find out why it is null, or the bug just moves somewhere quieter.

8. **Add dependencies deliberately.** Every dependency is permanent code you do not control. Before adding one, ask whether the project or the standard library can already do it. When you do add one, say why, so the choice is visible rather than smuggled into the manifest.

9. **Communicate what you did and why.** Say more than a block of code. Flag concerns even when you did exactly what was asked, and be precise about uncertainty: "I am not sure this library supports streaming" tells me what to verify; "I think this should work" does not.

10. **Catch yourself in the recurring failure modes.** A few patterns recur often enough to name: the *kitchen sink* (restructuring half the codebase while you are at it), the *wrong abstraction* (abstracting before you have copy-pasted twice), the *optimistic path* (happy path handled, the 500 ignored), and the *runaway refactor* (a fix that cascades across files). In any of these, the right move is to stop, not to push through.

The ten rules above adapt Andrej Karpathy's "Field notes on getting a language model to write code you will not rewrite".

### What the code and docs should read like

1. **Write code a human can read like a story.** Reading code for the first time is far harder than rereading it, and over a codebase's lifetime first reads dominate. So optimise for the first-time reader: a higher-level function should explain the whole workflow without the reader ever opening a helper, and each line should read like a deliberate step.

2. **Match detail to level.** The story rule bites hardest on orchestrators, workflows, transformations, test setup, and non-obvious control flow. For tiny leaf helpers, numerical kernels, hot paths, and standard protocol code, concise mechanical names and local detail are fine when they match the abstraction level.

3. **Name after intent, not mechanics.** The name should say why the caller does this, not the primitive inside. `enable_fast_inference(config)`, not `update_value(config, key, value)`.

4. **Prefer verb-led names for behaviour; reserve nouns for real domain objects.** If a function, file, class, or result represents something that happens, name it with the action: `apply_tracker_change(...)`, `execute_writes(...)`, `TrackerChangeResult` — not `manager`, `processor`, `handler`, `state`, `data`, `context`. Nouns are for stable objects like `Task` or `DependencyGraph`. If a noun needs a paragraph to say what happens next, rename it.

5. **Make orchestrators read like a story.** A high-level function should be a short list of meaningful steps, understandable before any implementation detail. If a function alternates between searching, parsing, mutating, validating, and logging in one long block, split it.

6. **One function, one job.** If a name needs multiple verbs (`load_validate_rewrite_and_save`), it does too much. Split into `load`, `validate`, `rewrite`, `save`.

7. **Order files entrypoint-first.** Arrange each file so a reader goes top to bottom without jumping: public entrypoints and orchestrators first, primitive parsing/formatting/validation/persistence helpers later. In tests, put the behaviour under test before local fixtures unless a strong local convention says otherwise.

8. **Pass explicit arguments, not bags of state.** A call should show what the helper depends on. Pass the two fields it needs, not the whole object it lives in.

9. **Use docstrings for context, not compensation.** Never use a docstring to explain a vague name — rename instead. Reserve docstrings for what a name cannot carry: footguns, invariants, edge cases, non-obvious tradeoffs, why a tempting alternative is wrong. Keep them plain prose with no markup, and short unless it is a top-of-file overview.

10. **Explain code as a story.** When explaining, use rendered Markdown with nested numbered lists (ordinary 1, 2, 3 at every level so indentation renders). Map each step to the function that owns it, and flag any function that mixes levels of abstraction as a problem.

11. **Lead documentation with behaviour before software.** In docs, READMEs, and handovers, put concrete examples, expected behaviour, workflows, and data shapes before modules and classes. Readers need anchor points before architecture is meaningful.

12. **Avoid historical context by default.** State current behaviour directly; skip old behaviour, past mistakes, and migration history unless it prevents a real footgun or explains why a tempting alternative is wrong.

## Behaviours to always avoid

- Never use American spelling; always use British spelling.
- Never use Capital Case for headings; use Sentence case.
- Never write redundant comments; comment only what the code cannot explain itself.
- Never use section-divider comments to group code; use the language's own structuring features instead.
- Never use abbreviations except obvious ones (`i`/`j`, `err`, `ctx`, `config`).
- Never name a path variable or flag without a `_path` suffix (`_dir` is the exception for directories).
- Follow the language's own convention for marking private members; do not invent your own.

## Tests

- Mirror source layout and the language's test conventions: one test file per source file, named per the ecosystem's standard.
- Group tests so it is obvious which unit and method each covers.
- Do not mock or fake the behaviour under test if that forces the reader to reason about private execution order or helper boundaries. Prefer realistic inputs through real behaviour; extract a small input-taking worker if needed, so a test reads as input, behaviour, output.
- Mocking is acceptable only for thin orchestrators whose call wiring is the behaviour under test. Assert boundary calls directly, name mocks `<original_name>_mock`, and use fakes only as small readable domain objects.

## Machine and environment facts

Tool paths, environments, and agent directories are defined entirely by the shell environment. Treat `~/.bashrc` as the single source of truth for `$PATH` and environment variables.