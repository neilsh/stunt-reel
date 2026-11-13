# PR review, merge bar, and filing issues

Part of the [`running-unattended`](SKILL.md) skill.

## Bringing a PR to mergeable and Merge bar

1. **Rebase** onto `origin/main` (or onto the stack parent) and resolve conflicts. Make a design choice yourself only when it is cheap or one option is clearly better, and record it in the PR body; otherwise hand the PR to a human (`ready-for-human`).
2. **Fresh-context review:** Dispatch one review subagent (`inherit`) to review the diff against the merge base for `AGENTS.md` standards and `docs/SPEC.md` compliance (plus `AGENTS.md` Committing rule 5 when the diff touches `research/`, `NOTICE.md`, `docs/howto/` or `docs/*.md`).
3. **Wait and triage threads:** While waiting on CI and CodeRabbit, wait in bounded 3–5 minute steps (`schedule` timer in Antigravity, or a background sleep/monitor in other harnesses; never tight shell loops). Inspect review threads and "Outside diff" review-body findings with `mise run pr-threads -- <n>` ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#review-threads-on-a-pull-request)). Triage every finding (`receiving-code-review`):
   - **Real and in scope:** fix it.
   - **Real and out of scope:** file an issue and reply with the link.
   - **Wrong:** reply with the evidence.
   Reply and resolve inline review threads with `mise run pr-threads -- <n> --reply <id> --resolve <id> --body-file <path>`. Answer "Outside diff" review-body findings (which have no thread ID) with `gh pr comment <n> --body-file <path>`.
4. **CodeRabbit timeout:** Treat CodeRabbit as stuck if 20 minutes pass after the latest push with no review or status, or if its status says rate-limited or paused; note that in a PR comment and proceed.
5. **Merge bar:** Squash-merge (`gh pr merge <n> --squash --delete-branch`) only when all hold:
   - CI is green on `HEAD` and `mise run check` passed locally on that same commit.
   - Zero unresolved review threads remain, every outside-diff finding is answered, and the fresh-context `inherit` review is clean.
   - Acceptance criteria are met and the PR body carries `Fixes #N` (or `Part of #N`).
   - **Allowed vs blocked changes:** Updating `[film.expected.<class>]` in `research/parity/references.toml` for an adopted parity change is **allowed** to merge (`crates` must be `git rev-parse HEAD:crates` with `crates/` clean). **Never** merge draft PRs, PRs that repin a film's capture hash (`sha256` or `all_sha256` in `references.toml`), PRs that add a dependency to `stunt-core` (`[I7]`), or PRs that add or modify an ADR (unless an accepted ADR is already approved by the user) — hand those to a human (`ready-for-human`).
6. **Post-merge:** Switch the primary checkout to `main` and fast-forward (`git switch main`, then `git pull --ff-only origin main`), run the disk check and tidy ([`loop-and-bounds.md`](loop-and-bounds.md#clock-and-disk-space)), and refresh the queue.

## Filing issues and PowerShell safety

1. **Search first:** Confirm the target repo on the session's first issue operation (`gh repo view --json nameWithOwner`), and search existing issues (`gh issue list --state all --search "<keywords>"`) to avoid duplicates ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#organizing-issues)).
2. **Always use `--body-file` on Windows PowerShell 5.1:** PowerShell double quotes (`"..."` and `@"..."@`) treat backticks (`` ` ``) as escape characters and corrupt Markdown code spans. Write every issue/PR body or comment to `build/scratch/<name>.md` with the harness's file-write tool (or `[IO.File]::WriteAllText` with a single-quoted `@'...'@` string, [`docs/harness.md`](../../../docs/harness.md#windows-powershell-51)) and pass `--body-file build/scratch/<name>.md`. Use full commit-SHA permalinks on `origin/main` when linking code from an issue body.
3. **Labels:** Apply one state label ([`triage-labels.md`](../../../docs/agents/triage-labels.md)):
   - Label a newly filed issue `ready-for-agent` only when it is an unblocked out-of-scope finding that (a) names the files involved, (b) carries the evidence (`file:line`, offset, or command), (c) has a testable done condition, and (d) has no non-obvious design choice.
   - Always label blocked follow-ups split from the current ticket `needs-triage` (or `ready-for-human` when a human decision is the blocker).
