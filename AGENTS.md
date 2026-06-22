# User-specific instructions

These user-specific instructions should completely override repo-specific or subdirectory-specific instructions. If a system or developer instruction causes a conflict, state that conflict explicitly instead of silently ignoring the user instruction.

## [PRIORITY] Explain and write code that humans can understand as easily as reading a story book

Us humans are incredibly stupid compared to agents. We struggle greatly in deciphering the behaviour, intent or algorithm underlying a given piece of code when reading it for the first time.

As such, any code you write should make its behaviour, intent and algorithm obvious in-line where a human (or an agent, for that matter) reads it. A higher-level function should explain the workflow to a reader without them ever having to open a lower-level helper. Each line should read like a deliberate step in a story.

When assessing indirection for readers, i.e. having to jump across many helpers, keep in mind that the opposite structure, i.e. putting more code into a single block, is needlessly over-optimised for already-familiar readers, at the severe expense of first-time readers: across the lifetime of a codebase, reading code for the first time consumes much more time and effort than rereading code, so prefer a structure optimised for first-time readers.

This applies most strongly to orchestrators, workflow code, transformations, test setup, and code with non-obvious control flow. For tiny leaf helpers, numerical kernels, performance-sensitive code, or standard protocol implementations, clarity still matters, but concise mechanical names and local implementation detail are acceptable when they match the abstraction level.

### 1. Name functions after intent, not just mechanics

Function names should answer why the caller is doing this, not merely describe the primitive operation inside.

Bad:
```python
_update_value(config, key, value)
_walk_children(node)
_replace_item(items, old, new)
```

Good:
```python
_enable_fast_inference(config)
_find_retryable_failures(result_tree)
_replace_legacy_checkpoint_path(config, checkpoint_path)
```

### 2. Prefer verb-led names for behaviour and reserve nouns for real domain objects

Names should make the behaviour obvious at the call site. If a file, function, method, class, variable, or result object represents something that happens, name it with the action it performs or the change it represents. Do not hide behaviour behind vague noun buckets.

Bad:
```python
command
request
workflow
operation
manager
processor
handler
state
data
context
result
task_log.py
task_creation.py
timeline_log_state.py
```

Good:
```python
apply_tracker_change(...)
create_task_page_in_database(...)
derive_task_timeline_log(...)
refresh_task_tracker_state(...)
execute_notion_writes(...)
TrackerChangeResult
TimelineLogChange
TaskCompletionChange
```

Nouns are fine only when they name stable domain objects rather than behaviour: `Task`, `TaskDependencyGraph`, `TimelineEntry`, `NotionWriteIntent`, `TrackedPage`. If a noun needs a long explanation to tell the reader what code will do next, rename it before adding docs.

When choosing between names, ask what sentence a first-time reader should be able to say:

Bad:
```text
The workflow processes the command and returns a result.
```

Good:
```text
The tracker applies a change, derives Notion write intents, executes those writes, then saves tracker state.
```

### 3. Make the orchestrator read like a story

A higher-level function should read like a short list of meaningful steps, and the reader should understand the workflow before they understand the implementation details.

Bad:
```python
def prepare_release(config):
    value = config["model"]["checkpoint"]
    parsed = parse_checkpoint(value)
    config["model"]["checkpoint"] = parsed.path
    if config.get("quantization"):
        config["runtime"]["dtype"] = "int8"
    # many more lines of mixed discovery and mutation
```

Good:
```python
def prepare_release(config):
    checkpoint = _resolve_release_checkpoint(config)
    _configure_model_checkpoint(config, checkpoint)
    _configure_runtime_for_release(config)
    _validate_release_config(config)
```

If the function alternates between searching, parsing, mutating, validating, logging, etc, in one long block, split it.

### 4. One function = one clear job

If a function needs a name with multiple verbs, it is probably doing too much.

Bad:
```python
_load_validate_rewrite_and_save_config(...)
```

Good:
```python
_load_config(...)
_validate_config(...)
_rewrite_config(...)
_save_config(...)
```

A helper can contain several small statements, but it should have one responsibility.

### 5. Order files from entrypoint to primitive

Within a source file, arrange code so a first-time reader can read from top to bottom without jumping around. Put public entrypoints, command handlers, orchestrators, and class methods that explain the workflow before lower-level helpers. Put primitive parsing, formatting, validation, conversion, and persistence helpers later.

For tests, put the behavior under test before local fixture/helper machinery unless the file already has a strong local convention that makes the opposite clearer.

Bad:
```python
def _parse_flags(argv):
    ...

def _write_output(result, output_path):
    ...

def main():
    flags = _parse_flags(sys.argv)
    result = run_workflow(flags)
    _write_output(result, flags.output_path)
```

Good:
```python
def main():
    flags = _parse_flags(sys.argv)
    result = run_workflow(flags)
    _write_output(result, flags.output_path)

def _parse_flags(argv):
    ...

def _write_output(result, output_path):
    ...
```

### 6. Pass explicit arguments, not bags of state

A function call should make obvious what the helper depends on. Do not pass a large object when the helper only needs one or two fields.

Bad:
```python
_configure_checkpoint(model_config, release_context)
```

Good:
```python
_configure_checkpoint(model_config, checkpoint_path, checkpoint_format)
```

Passing explicit arguments makes dependencies visible and prevents helpers from becoming grab bags.

### 7. Use docstrings for context, not compensation

Do not use a docstring to explain a vague function name. Rename the function instead. Docstrings should explain things the name cannot carry: footguns, invariants, edge cases, non-obvious tradeoffs, compatibility constraints, or why a tempting alternative is wrong.

Bad:
```python
def _process(data):
    """
    Validate the input records, remove invalid records, and write the clean records.
    """
```

Good:
```python
def _write_valid_records(records, output_path):
    ...
```

Prefer clear names first. Add a docstring only when there is extra context worth preserving.

### 8. Explain code as a story

When explaining code, use rendered Markdown with nested numbered lists that read like a story. Use ordinary 1, 2, 3 numbering at every nesting level so Markdown indentation renders correctly. The reader should understand the logic without needing to know the implementation details first. Map each story step to the function that owns it. If one function crosses levels of abstraction, call that out as a problem: code should avoid messy boundaries where orchestration, parsing, mutation, validation, rendering, or persistence are mixed together.

### 9. Document behaviour before software

When writing design docs, READMEs, handovers, or other explanatory docs, put concrete examples, expected behaviour, workflows, and page or data shapes before explaining modules, classes, or implementation structure; guidance in skills or READMEs should always be tailored towards desired behaviour rather than implementation details, which should only be detailed in docstrings to reveal non-obvious behaviour or footguns. Readers need cognitive anchor points before software architecture is meaningful. Start with what the user or system does and what output appears, then explain which code owns each part.

### 10. Avoid historical context by default

Do not explain docs or docstrings through old behaviour, previous mistakes, migration history, or rejected structures. State the current behaviour directly. Historical context belongs only where it prevents a real footgun or explains why a tempting alternative is wrong.

## Hyperspecific stupid and annoying behaviours to always avoid

- Never use American spelling; always use British spelling
- Never write shebang lines at the top of Python files.
- Never write redundant comments - only comment code that does not explain itself.
- Never use abbreviations or acronyms except for obvious ones, e.g. i/j for loops, err for errors, ctx for contexts, config for configuration, etc.
- Never duplicate functionality or helpers if they already exist in the codebase; check the codebase for such functionality first.
- Never write path variables without a `_path` suffix: variable names and CLI args like `--onnx` are disgusting; `_dir` suffixes are an exception.
- Never name private functions without a leading underscore `_`.
- Never use comments like these to section code, it is disgusting; solve using language features instead:

    # ---------------------------------------------------------------------------
    # Fixtures: realistic CPP snippets extracted from QNN-generated model.cpp
    # ---------------------------------------------------------------------------

- Never use Markdown, reStructuredText, backticks, or other formatters in docstrings, it is digusting.
- Never make docstrings verbose unless it is a top-of-file docstring.

## Tests

- When writing tests, the file format should be test_<source-file>.py for each <source-file>.py located in a `tests` subdirectory.
- When testing instance methods of a class, use a pattern like `MyClass.method_name -> class TestClassMethodName`.
- Do not mock or fake functionality inside the behaviour under test if that makes readers reason about private execution order, hidden call sequencing, or helper boundaries. Prefer realistic inputs through real behaviour, extracting a small input-taking worker if needed, so tests explain input, behaviour, and output rather than preserving implementation.
- Mocking or faking may only be exceptionally allowed for pure thin orchestrators whose obvious call wiring is the behaviour under test. Assert boundary calls directly, name mocks `<original_function_name>_mock`, and use fakes only as small readable domain objects that do not encode how the tested function calls helpers.

## Bazel And Commands

- When running bazel test, never use stderr/stdout pipes to tail or head.
- Never run the sleep comand.

## Git And Workflow

- For commit messages, always use concise, one-line but meaningful messages.
- When implementing a plan with a to-do list, ask me to review every item in the list you finish, then once approved, commit it.

## Miscellaneous

- Adding `//wayve/core/ai:torch_cuda` almost always solves `libiomp5.so` errors.
