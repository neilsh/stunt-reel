# Take a commit from another session's branch

A commit taken from another session's branch (a cloud session's) keeps that session's author, which the pre-push hook rejects. Re-commit it:

1. Start from a clean checkout: `git status --porcelain` prints nothing, since the gate tests untracked and unstaged files too.
2. `git cherry-pick --no-commit <sha>`.
3. `mise run check -- --full` on the picked tree.
4. `git commit -F <message>` with `<sha>`'s message, its gate line replaced by the one the gate printed.

`--no-commit` carries no author over, so the author is you, the commit hooks check the picked changes, and the gate line states this run.
