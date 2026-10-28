# Publish through a fresh, scrubbed repository

The private `neilsh/stunt-reel` was not made public as it was. Its history was rewritten with
`git filter-repo`, which put every author and committer on the GitHub noreply identity and
replaced two machine paths in [ADR 0019](0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md)
with placeholders. The private repository was renamed `stunt-reel-archive`, and only the
rewritten `main` was pushed to a new public `neilsh/stunt-reel`. This amends
[ADR 0015](0015-publication-with-a-documented-palette-exception.md) §1, which planned to flip
the private repository's visibility.

Flipping would have published the address no matter what was done to the branches. Pull
requests #4, #5, #6 and #9 were merged in the web UI under the account's email, and GitHub
keeps merged pull requests and their commits visible after any force-push. A `.mailmap` only
changes how `git log` displays names; the address stays in the objects. A fresh repository
costs the pull-request threads and Actions history, and both remain in the private archive.
Only the 29 commits from the first leak onward changed hash. Every earlier commit kept its
hash, and no document cites one of the 29. Hashes from before the 2026-10-25 rewrite still
resolve nowhere public.

This also amends ADR 0015 §5. The README calls the project reverse engineering because that is
what it does: format analysis of a 1992 program for interoperability and preservation.
Avoiding the term made the description vaguer without changing the legal footing. The
"cleanroom" claim stays retired.

To keep the address out from now on, the account sets *Keep my email addresses private*, which
covers merges in the web UI, and *Block command line pushes that expose my email*. Commit
identity is a maintainer's local setting, not a repository rule, so it is not enforced in CI.
[`CONTRIBUTING.md`](../../CONTRIBUTING.md) tells contributors that their commit email is
published. [`docs/process/plans/public-release-2026-10-28.md`](../process/plans/public-release-2026-10-28.md)
has the steps and their verification.
