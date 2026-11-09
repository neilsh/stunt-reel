# Re-gate a branch after a rebase

A rebase gives every commit a new tree, so the commit-msg hook can no longer match its gate line to a passing run ([the gate line is checked](../development.md#the-gate-line-is-checked)). In a clean checkout:

```powershell
mise run regate -- <base>
```

[regate.py](../../python/scripts/regate.py) gates each commit of `<base>..HEAD` detached, each in its own scope (`-- --full` after the base reaches every run), without the variables `git rev-parse --local-env-vars` lists: `git rebase --exec "mise run check"` exports `GIT_DIR`, and the tests that run git then act on the real repository. Only when every run passes does it rewrite each gate line, keeping trees, authors and dates, and move the branch; the old tip goes to `refs/backup/regate/<branch>`, whose reflog keeps earlier ones. It never pushes.
