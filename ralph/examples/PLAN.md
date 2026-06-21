# Example Ralph Plan

<!-- ralph-shared:start -->
Build the smallest useful version of the feature. Preserve existing public behaviour unless a task says otherwise.
<!-- ralph-shared:end -->

<!-- ralph-task:start R1 -->
## R1 Add parser

Add a parser that accepts valid input and produces useful errors for invalid input.

<!-- ralph-allowed-bash:start -->
- rg *
- sed -n *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_parser.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R1 -->

<!-- ralph-task:start R2 -->
## R2 Add command line entrypoint

Add a command line entrypoint that uses the parser.

<!-- ralph-allowed-bash:start -->
- rg *
- sed -n *
<!-- ralph-allowed-bash:end -->

<!-- ralph-verification:start -->
- python -m pytest tests/test_cli.py
<!-- ralph-verification:end -->
<!-- ralph-task:end R2 -->
