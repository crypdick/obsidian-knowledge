## Red/Green TDD

For behavior changes and bug fixes, use red/green/refactor:

1. Red: add or update a focused failing test that proves the desired behavior or reproduces the bug. Run the targeted test and confirm it fails for the expected reason.
2. Green: implement the smallest change that makes the test pass. Run the targeted test again and confirm it passes.
3. Refactor: clean up the implementation while keeping the targeted test green, then run the relevant broader test set.

Do not skip the red step unless there is no practical test boundary. If you skip it, state why and run the closest meaningful verification instead.
