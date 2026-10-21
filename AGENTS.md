# User-level instructions

These instructions contain the principles with which you should write code; please follow them closely: you are capable of generating anything these days, but your code frequently fails to look actually good to humans unless you follow principles such as below. Said another way: your code must not just be correct, it must be of high quality, and easily understandable by a human.

## Principles

**1. Read before you write; read to be aware.** Do not write a single line of code until you read every single producer and consumer of a piece of functionality of interest within a codebase. Furthermore, read not because existing code in the codebase is correct or high-quality - it often isn't - but to be aware: what is the verified-not-guessed behaviour, what might break if you change something without considering knock-on effects, what functionality already exists that you can reuse, what patterns are already in place?

**2. Anything you write should be self-documenting and as easy to read as a cookbook recipe.** Code is just logic executed in steps, and the sequence of steps should be as easily understandable as reading a cookbook recipe in linear order: any function you write should be comprised of subfunctions written at exactly the right abstraction levels in the right order using verb-led names (i.e. `do_something()`, not `something()`) such that the high-level logic can be understood just by reading the sequence of subfunctions. The outcome must be that (a) the reader **never, ever** has to read the internals of a subfunction to understand what the function is doing and (b) they **never, ever** have to jump around and (re)read in the codebase to understand a function; if either of (a) or (b) happen, it means you have failed to follow this principle. Please refactor the code if so.

**3. Modularity is unreasonably effective; so is the single-responsbility principle.** Any function, class or module you create should be modular and responsible for a single conceptual behaviour. This makes it easy to reason about, easy to test, and easy to change without breaking something else. As soon as something does multiple things, it is hard to reason about, it is hard to test, and it is hard to change without inadvertently breaking something else.

**4. Follow DRY (don't repeat yourself).** Always reuse functionality. This boils down to: (a) never writing code until you read around in the codebase to see if there's something you can reuse - either outright or by adapting it - and (b) strongly dispreferring repeating large chunks of code: if you find yourself doing so, extract the chunk into a reusable helper. Failing to meet (a) and (b) usually means you have failed to follow principles 1 and 2. Change your approach to satisfy them if so.

**5. YAGNI (you ain't gonna need it) and KISS (keep it simple, stupid) go hand-in-hand.** Only write the smallest piece of code that induces the smallest diff that produces the desired behaviour(s). **Never** write code to handle speculative scenarios: do not write compatibility shims - breaking backwards compatibility is fine and preferred unless explicitly requested otherwise; do not try to handle impossible or "might-happen" errors, or add fallback behaviour - fail fast on any (edge) cases not explicitly discussed.

**6. Test logically meaningful behaviour, not implementation internals.** Prefer writing few end-to-end-like tests of logically meaningful behaviours, not numerous quasi-tautological tests of small helper functions. It is easy - and annoying during code review - to waste many lines of code writing tests of small helper functions that are often "obviously right" or which essentially reimplement internals. **Do not** do this: write the smallest suite of tests that test the behaviour(s) we care about. Furthermore, prefer editing existing end-to-end-like tests when testing behavioural changes instead of adding several new ones that test purely the before-versus-after behavioural delta instead of the holistic behaviour. You should always be able to make an exact and one-to-one mapping of behaviours to individual functions or classes and thereby test them as per this principle; if you are struggling to do so, it means you have failed to follow principle 2: refactor the source and/or tests if so.

**7. Strongly prefer AAA-style (arrange-act-assert) tests, possibly with fixtures; mocks, fakes or stubs are absolute last resorts, and with strong caveats.** AAA-style tests - with fixtures when needed - are very readable and understandable in terms of what behaviour they are testing without the reader having to know about internals (as per principle 2): given some arrangement on which I perform some action, I assert some expected result. Conversely, mocks, fakes or stubs force us to reason about internals which is a gross violation of principle 2, and therefore should be avoided as much as possible. If you are struggling to test a behaviour via an AAA-style test, it means you have failed to follow principle 3; refactor if so.

*Caveat:* mocks, fakes or stubs are nonetheless often the best way to test functionality containing heavy or hard-to-access boundaries (e.g. databases, dev kits, networks, artefacts, etc) - in this case it is fine to use them with the following caveat: in the test docstring, include the function call order so that we know exactly what is being mocked out where and why; follow this template:

```python
def test_deploy_migrates_pre_regime_saved_config_before_loading_wrapper(
    mocker,
    nano_config: DictConfig,
    deploy_input_session: Session,
    tmp_path: Path,
) -> None:
    """Migrate a pre-v10 saved config before passing it to the deployment wrapper.

    Relevant call order:
    deploy
    -> resolve_session_details (mocked: avoid catalogue/session lookup)
    -> load_hydra_config (mocked: provide the legacy config)
    -> migrate_rl_config_to_latest (real: behaviour under test)
    -> load_deployment_config (mocked: isolate config migration)
    -> apply_deployment_config_overrides (mocked: preserve the fixture config)
    -> load_rl_driving_wrapper (mocked: capture the migrated config before model,
       checkpoint, and GPU work)
    -> save_artifacts_and_maybe_upload (mocked: avoid artefact writes and uploads).

    The test therefore checks deploy's ordering while keeping unrelated external
    boundaries out of the regression test.
    """
```

**8. Verify behaviour, don't guess, infer or predict it; use TDD (test-driven development).** When writing code, always prefer physically running commands which let you verify behaviour instead of inferring it. Feel free to generate throwaway scripts when doing this. A specific case of this principle is using TDD: first write failing test(s) that encapsulate the behaviour(s) of interest, watch them fail, then write code until the the test passes. Avoid guessing, inferring or predicting the behaviour of code.

**9. Use docstrings for context, not compensation.** Never use a docstring to explain a vague name — rename to something more meaningful instead. Reserve docstrings for what a name cannot carry: footguns, invariants, edge cases, non-obvious tradeoffs, why a tempting alternative is wrong. Keep them plain prose with no markup, and short unless it is a top-of-file overview.

**10. Avoid historical context by default.** State current behaviour directly; skip old behaviour, past mistakes, and migration history unless it prevents a real footgun or explains why a tempting alternative is wrong.

## Things to always avoid

- Never use American spelling; always use British spelling.
- Never use Capital Case for headings; use Sentence case.
- Never write redundant comments; comment only what the code cannot explain itself.
- Never use section-divider comments to group code; use the language's own structuring features instead.
- Never use abbreviations except obvious ones ( e.g. `i`/`j`, `err`, `ctx`, `config`, etc).
- Never name a path variable or flag without a `_path` suffix (`_dir` is the exception for directories).

## Machine and environment facts

Tool paths, environments, and agent directories are defined entirely by the shell environment. Treat `~/.bashrc` as the single source of truth for `$PATH` and environment variables.