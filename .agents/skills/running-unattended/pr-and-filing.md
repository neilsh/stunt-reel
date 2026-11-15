# PR review, merge bar, and filing issues

Part of the [`running-unattended`](SKILL.md) skill.

## Bringing a PR to mergeable and Merge bar

1. **Rebase** onto `origin/main` (or onto the stack parent) and resolve conflicts. Make a design choice yourself only when it is cheap or one option is clearly better, and record it in the PR body; otherwise hand the PR to a human (`ready-for-human`). Push the branch and confirm local `HEAD` matches `origin/<branch>` before starting step 2.
2. **Fresh-context review:** a PR built by Sonnet or dsh gets its first review from Opus or Antigravity, requested explicitly ([`docs/harness.md`](../../../docs/harness.md#policy-any-agent)); on #160 a Sonnet review missed four bugs. Have it review the diff against the merge base for `AGENTS.md` standards and `docs/SPEC.md` compliance (plus `AGENTS.md` Committing rule 5 when the diff touches `research/`, `NOTICE.md`, `docs/howto/` or `docs/*.md`). Before asking, the implementer scans its own diff for those rule 5 words and checks every quoted figure against its source. Every reviewer brief, whatever the reviewer (Claude subagent, Orca worker or Antigravity), ends with this instruction, copied into the brief word for word:

   > Post your verdict as a PR comment with `gh pr comment <n> --body-file build/scratch/review-<n>.md` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -F body=@build/scratch/review-<n>.md`), clean included. Its first line is exactly `<Reviewer> review at <7-char head SHA>: clean` or `<Reviewer> review at <7-char head SHA>: needs changes`, with no `:` in `<Reviewer>`; then your findings (`file:line — problem — fix`, marked `blocking` or `nit`), or "no findings" plus what you checked (files read, gates and commands run) and what you could not verify. Reply with the comment's URL.

   **Review-comment template.** The comment's first line is exactly `<Reviewer> review at <head SHA>: <verdict>`, then your findings or verification summary:
   - `<Reviewer>` is the reviewer's own name, with no `:` in it: `Sonnet`, `Opus`, `Antigravity`, or the worker's agent name.
   - `<head SHA>` is the 7-character short SHA printed by `gh pr view <n> --json headRefOid --jq '.headRefOid[0:7]'` (cloud: `gh api repos/{owner}/{repo}/pulls/<n> --jq '.head.sha[0:7]'`), read when you start reviewing and again before you post; confirm local `HEAD` matches it and review the diff of that commit against `origin/main` (or the stack parent). If it changed, review the new head.
   - `<verdict>` is `clean` (no finding left to fix) or `needs changes`.
   - **Body lines:** each finding gives `file:line — problem — fix` with severity (`blocking` or `nit`); a `clean` verdict states `No findings`, what was checked (files, gates, commands), and anything you could not verify.

   ```
   Sonnet review at 0123456: needs changes
   - crates/x/src/y.rs:42 — doc says "all", but the test covers one case — test both variants (blocking).
   ```

   ```
   Sonnet review at 0123456: clean
   No findings. Checked diff against origin/main and `mise run check` (4/4); could not verify capture offsets (no data root).
   ```

   A reviewer that cannot post returns this text as its reply, and you post it unchanged. A re-review covers only what changed since the last reviewed commit, runs once after every finding is fixed, and uses [`reviewer`](../../../.claude/agents/reviewer.md) (Sonnet), or Antigravity when Gemini quota allows; a wording-only fix gets no re-review, so reply to the finding with the new text. After you push a fix, the re-review posts a new comment at the new head; the merge bar reads only comments at the current head.
3. **Wait and triage threads:** While waiting on CodeRabbit, wait in bounded 3–5 minute steps (`schedule` timer in Antigravity, or a background sleep/monitor in other harnesses; never tight shell loops). Inspect review threads and review-body findings ("Outside diff" and "Additional comments") with `mise run pr-threads -- <n>` ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#review-threads-on-a-pull-request)). Triage every finding (`receiving-code-review`):
   - **Real and in scope:** fix it.
   - **Real and out of scope:** file an issue and reply with the link.
   - **Wrong:** reply with the evidence.
   Reply and resolve inline review threads with `mise run pr-threads -- <n> --reply <id> --resolve <id> --body-file <path>`. Answer review-body findings — "Outside diff" and "Additional comments" (which have no thread ID) — with `gh pr comment <n> --body-file <path>` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -F body=@<path>`).
4. **CodeRabbit timeout:** Treat CodeRabbit as stuck if 20 minutes pass after the latest push without a completed review on `HEAD` (including when its check status stays pending), or if its status says rate-limited or paused; note that in a PR comment and proceed.
5. **Merge bar:** Arm squash auto-merge (`gh pr merge <n> --squash --auto --delete-branch`) on a PR based on `main` only when all of these hold. GitHub then merges once the `main` ruleset's required checks pass, without waiting on threads, so arm last, and disarm (`gh pr merge <n> --disable-auto`) before pushing a fix. A stacked PR's base has no ruleset, so arming it would merge it into its parent without CI: arm it only once its parent has merged and GitHub has retargeted it to `main`. `gh pr merge --auto` uses GraphQL, which a cloud session's proxy refuses: there, arm and disarm through its REST route `/repos/{owner}/{repo}/pulls/<n>/ccr/auto_merge` ([`cloud-sessions.md`](../../../docs/cloud-sessions.md)).
   - No check has failed on `HEAD`, `mise run check` passed locally on that same commit, and CodeRabbit has either completed its review of `HEAD` or hit the step 4 timeout for the latest push.
   - Zero unresolved review threads remain, every review-body finding is answered, and the dispatched review's comment at `HEAD` says `clean`: confirm its URL came from the review you dispatched at `HEAD` and run the local (GraphQL) or cloud (REST) command below, whichever your shell can run (both accept only `OWNER`/`MEMBER`/`COLLABORATOR` comments). The bar is met only when it prints `true`. On `false` (no comment at `HEAD`, a comment only at an older SHA, or the newest comment at `HEAD` says `needs changes`), dispatch a re-review at `HEAD` (step 2).

     ```
     # local (GraphQL):
     gh pr view <n> --json headRefOid,comments --jq '.headRefOid[0:7] as $h | [.comments[] | select(.authorAssociation | IN("OWNER","MEMBER","COLLABORATOR")) | .body | split("\n")[0] | rtrimstr("\r") | select(test("^[^:]+ review at " + $h + ": "))] | last | (. // "") | test(": clean$")'

     # cloud (REST), the same boolean; --paginate walks every page, so a long history is never cut short:
     H=$(gh api repos/{owner}/{repo}/pulls/<n> --jq '.head.sha[0:7]')
     gh api --paginate "repos/{owner}/{repo}/issues/<n>/comments?per_page=100" --jq ".[] | select(.author_association | IN(\"OWNER\",\"MEMBER\",\"COLLABORATOR\")) | .body | split(\"\\n\")[0] | rtrimstr(\"\\r\") | select(test(\"^[^:]+ review at $H: \"))" | tail -n 1 | grep -q ': clean$' && echo true || echo false
     ```
   - Acceptance criteria are met and the PR body carries `Fixes #N` (or `Part of #N`).
   - **Allowed vs blocked changes:** Updating `[film.expected.<class>]` in `research/parity/references.toml` for an adopted parity change is **allowed** to merge (`crates` must be `git rev-parse HEAD:crates` with `crates/` clean). **Never** arm or merge draft PRs, PRs that repin a film's capture hash (`sha256` or `all_sha256` in `references.toml`), PRs that add a dependency to `stunt-core` (`[I7]`), or PRs that add or modify an ADR (unless an accepted ADR is already approved by the user) — hand those to a human (`ready-for-human`).
6. **After arming:** Fast-forward the `main` ref without switching any checkout (`git fetch origin main:main`; skip it when git refuses because a checkout has `main` checked out), run the disk check and tidy ([`loop-and-bounds.md`](loop-and-bounds.md#clock-and-disk-space)), and refresh the queue.

## Filing issues and PowerShell safety

1. **Search first:** Confirm the target repo on the session's first issue operation (`gh repo view --json nameWithOwner`; cloud: `gh api repos/{owner}/{repo} --jq .full_name`), and search existing issues (`gh issue list --state all --search "<keywords>"`; cloud: `gh api 'search/issues?q=repo:{owner}/{repo}+type:issue+<keywords>'`) to avoid duplicates ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#organizing-issues)).
2. **Always use `--body-file` on Windows PowerShell 5.1:** PowerShell double quotes (`"..."` and `@"..."@`) treat backticks (`` ` ``) as escape characters and corrupt Markdown code spans. Write every issue/PR body or comment to `build/scratch/<name>.md` with the harness's file-write tool (or `[IO.File]::WriteAllText` with a single-quoted `@'...'@` string, [`docs/harness.md`](../../../docs/harness.md#windows-powershell-51)) and pass `--body-file build/scratch/<name>.md`. Use full commit-SHA permalinks on `origin/main` when linking code from an issue body.
3. **Labels:** Apply one state label ([`triage-labels.md`](../../../docs/agents/triage-labels.md)):
   - Label a newly filed issue `ready-for-agent` only when it is an unblocked out-of-scope finding that (a) names the files involved, (b) carries the evidence (`file:line`, offset, or command), (c) has a testable done condition, and (d) has no non-obvious design choice.
   - Always label blocked follow-ups split from the current ticket `needs-triage` (or `ready-for-human` when a human decision is the blocker).
   - Add `local-only` ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles)) when the issue needs a GPU, DOSBox or `wrangler login`.
