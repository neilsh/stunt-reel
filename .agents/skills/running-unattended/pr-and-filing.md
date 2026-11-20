# PR review, merge bar, and filing issues

Part of the [`running-unattended`](SKILL.md) skill.

## Bringing a PR to mergeable and Merge bar

1. **Rebase** an unpushed branch onto `origin/main` (or onto the stack parent) and resolve conflicts; for a branch already pushed, merge `origin/main` into its head instead, since a force-push may be refused in auto mode and the squash merge keeps `main` linear anyway: a worker does it, since the coordinator reads no diff.
   The worker makes a design choice only when it is cheap or one option is clearly better, and records it in the PR body; otherwise it reports, and the coordinator hands the PR to a human (`ready-for-human`).
   Then push, with one exception.
   A *rule 5 PR* is one whose diff touches a path [`AGENTS.md` § Committing](../../../AGENTS.md#committing) rule 5 names.
   Its first commit and every later fix, rebase or merge is committed locally and not pushed until step 2 has reviewed it at its local SHA; you then push it unchanged and, for the first push, open the PR.
   A rebase or merge changes the SHA, so it needs a fresh `clean` comment at the new head; for a merge commit whose tree equals an already-reviewed tree, the re-review only confirms that identity (`git diff <reviewed> <merge>` is empty).
   Bring the branch up to date with `origin/main` (rebase or merge, as above) just before dispatching step 2's review, and push as soon as it is `clean`.
   A conflict only in `research/MAP.md` takes either side, then `mise run knowledge-map -- --write`; the re-review at the new head then only confirms that `mise run knowledge-map -- --check` passes and that the diff against the reviewed commit shows only `main`'s files, and posts its `clean` comment (an owner-approved relaxation of rule 5 for that generated file alone).
   Any other PR pushes now: confirm local `HEAD` matches `origin/<branch>` before starting step 2.
   A work `spec.md` or `plan.md` is different: its fresh review reads the uncommitted diff, in the implementer's own worktree, by a subagent the implementer dispatches there; the commit carries the `Fresh-review:` trailer ([`development.md`](../../../docs/development.md#commit-messages)), and rule 5 does not hold it back from a push.
2. **Fresh-context review:** dispatch the Sonnet [`reviewer`](../../../.claude/agents/reviewer.md) agent by default, for the first review and re-reviews.
   The first review of a PR built by Sonnet or dsh is the exception: dispatch it to Opus or Antigravity, as a general-purpose subagent with `model: opus`, given the reviewer instruction below with `Opus` as `<Reviewer>`, or as an Antigravity worker; do not run the `reviewer` agent with a model override, because it names `Sonnet` in the verdict.
   On #160 a Sonnet review missed four bugs.
   Have the reviewer review the diff against the merge base for `AGENTS.md` standards and `docs/SPEC.md` compliance (plus `AGENTS.md` Committing rule 5 when the diff touches a path it names).
   Each review gets its own detached worktree, `.claude/worktrees/review-<PR or SHA>` in the primary checkout, made with `git worktree add --detach <path> origin/<branch>` (on a single-branch clone where `origin/<branch>` is absent, `git fetch origin <branch> && git worktree add --detach <path> FETCH_HEAD`), or, for a commit not yet pushed, `<SHA>` of the commit the implementer reported; settings deny `git worktree remove` and `mise run reap` skips detached worktrees, so it outlives the run and the owner removes it.
   Never run `git checkout` or `git switch` in the implementer's checkout; if your working directory is not a `review-*` worktree, create one first.
   In a cloud session every reviewer brief starts by telling the reviewer to read [`cloud.md`](../working-in-an-environment/cloud.md).
   Before asking, the implementer scans its own diff for rule 5's over-broad words and checks every quoted figure against its source.
   Every reviewer brief, whatever the reviewer (Claude subagent, Orca worker or Antigravity), ends with this instruction, copied into the brief word for word:

   > Post your verdict as a PR comment with `gh pr comment <n> --body-file build/scratch/review-<n>.md` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -F body=@build/scratch/review-<n>.md`), clean included; if the reviewed commit is not the PR's head (no PR yet, or an unpushed rule 5 fix, rebase or merge), post nothing and reply with the comment text, first line included.
   > Its first line is exactly `<Reviewer> review at <7-char head SHA>: clean` or `<Reviewer> review at <7-char head SHA>: needs changes`, with no `:` in `<Reviewer>`; then your findings (`file:line — problem — fix`, marked `blocking` or `nit`), or "no findings" plus what you checked (files read, gates and commands run) and what you could not verify.
   > The verdict is `needs changes` when any finding is `blocking` or a `nit` that must be fixed before merge, else `clean`.
   > Reply with the comment's URL.

   **Review-comment template.**
   The comment's first line is exactly `<Reviewer> review at <head SHA>: <verdict>`, then your findings or verification summary:
   - `<Reviewer>` is the reviewer's own name, with no `:` in it: `Sonnet`, `Opus`, `Antigravity`, or the worker's agent name.
   - `<head SHA>` is the 7-character short SHA printed by `gh pr view <n> --json headRefOid --jq '.headRefOid[0:7]'` (cloud: `gh api repos/{owner}/{repo}/pulls/<n> --jq '.head.sha[0:7]'`), read when you start reviewing and again before you post; confirm local `HEAD` matches it and review the diff of that commit against `origin/main` (or the stack parent).
     If it changed, review the new head.
     When the reviewed commit is not the PR's head (no PR yet, or an unpushed rule 5 fix, rebase or merge), there is no head to match: it is the reviewed commit's `git rev-parse --short=7 HEAD`.
   - `<verdict>` is `clean` or `needs changes`, by the verdict rule in the instruction above.
   - **Body lines:** each finding gives `file:line — problem — fix` with severity (`blocking` or `nit`); a `clean` verdict states `No findings`, what was checked (files, gates, commands), and anything you could not verify.

   ```
   Sonnet review at 0123456: needs changes
   - crates/x/src/y.rs:42 — doc says "all", but the test covers one case — test both variants (blocking).
   ```

   ```
   Sonnet review at 0123456: clean
   No findings. Checked diff against origin/main and `mise run check` (4/4); could not verify capture offsets (no data root).
   ```

   A reviewer that cannot post (the reviewed commit is not the PR's head: no PR yet, or an unpushed rule 5 fix, rebase or merge) returns this text as its reply.
   Push the commit as reviewed (step 1), with no amend and no rebase (if one is needed, review again), open the PR if it is the first push, then post the text unchanged: the pushed head is the reviewed SHA, so the comment's first line stays true.
   A re-review covers only what changed since the last reviewed commit, runs once after every finding is fixed, and prefers Antigravity when Gemini quota allows, otherwise the Sonnet [`reviewer`](../../../.claude/agents/reviewer.md) agent; a wording-only fix gets no re-review, so reply to the finding with the new text, except on a rule 5 PR, where it is re-reviewed like any other fix.
   A fix to any other PR is pushed first and its re-review posts a comment at the new head; the merge bar reads only comments at the current head.
3. **Triage threads:** CodeRabbit no longer reviews automatically, so do not wait for it.
   The coordinator runs `mise run pr-threads -- <n>` ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#review-threads-on-a-pull-request)) for the count of open threads and review-body findings ("Outside diff" and "Additional comments"); when any exist, a worker reads them and triages every finding (`receiving-code-review`):
   - **Real and in scope:** fix it.
   - **Real and out of scope:** file an issue and reply with the link.
   - **Wrong:** reply with the evidence.
     Reply and resolve inline review threads with `mise run pr-threads -- <n> --reply <id> --resolve <id> --body-file <path>`.
     Answer review-body findings — "Outside diff" and "Additional comments" (which have no thread ID) — with `gh pr comment <n> --body-file <path>` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<n>/comments -F body=@<path>`).
4. **CodeRabbit on request:** If a person's `@coderabbitai review` was posted after the latest push, schedule one check for 20 minutes after the request ([`coordinator.md`](coordinator.md#coderabbit-one-scheduled-check)); do not poll or `sleep`.
   At the check, a completed review goes to step 3; if there is none, or its status says rate-limited or paused, note that in a PR comment and proceed.
   A push after a review does not get a new one unless a person asks again; do not wait for it.
5. **Merge bar:** Arm squash auto-merge (`gh pr merge <n> --squash --auto`) on a PR based on `main` only when all of these hold.
   Leave out `--delete-branch`: on a PR that merges at once it also deletes the local worktree holding the branch, and the repo deletes the remote branch on merge anyway.
   GitHub then merges once the `main` ruleset's required checks pass and every review thread is resolved, but it reads neither the review comment nor review-body findings, so arm last, and disarm (`gh pr merge <n> --disable-auto`) before pushing a fix.
   A stacked PR's base has no ruleset, so arming it would merge it into its parent without CI: arm it only once its parent has merged and GitHub has retargeted it to `main`.
   `gh pr merge --auto` uses GraphQL, which a cloud session's proxy refuses: there, arm with the MCP tool `enable_pr_auto_merge` while checks are pending, and when the PR's merge state is `clean`, merge it with `merge_pull_request`, as [`cloud.md`](../working-in-an-environment/cloud.md#github-rest-only) says.
   - No check has failed on `HEAD`, `mise run check` passed locally on that same commit, and any CodeRabbit review a person requested since the latest push has completed or had its step 4 check.
   - Every review-body finding is answered (the ruleset enforces resolved threads), and the dispatched review's comment at `HEAD` (a child session's self-review included) says `clean` (for a rule 5 PR, the comment you posted from its pre-push review): confirm its URL came from the review you dispatched at `HEAD` and run the local (GraphQL) or cloud (REST) command below, whichever your shell can run (both accept only `OWNER`/`MEMBER`/`COLLABORATOR` comments).
     The bar is met only when it prints `true`.
     On `false` (no comment at `HEAD`, a comment only at an older SHA, or the newest comment at `HEAD` says `needs changes`), dispatch a re-review at `HEAD` (step 2).

     ```
     # local (GraphQL):
     gh pr view <n> --json headRefOid,comments --jq '.headRefOid[0:7] as $h | [.comments[] | select(.authorAssociation | IN("OWNER","MEMBER","COLLABORATOR")) | .body | split("\n")[0] | rtrimstr("\r") | select(test("^[^:]+ review at " + $h + ": "))] | last | (. // "") | test(": clean$")'

     # cloud (REST), the same boolean; pages go by number, since the proxy refuses --paginate's next links:
     H=$(gh api repos/{owner}/{repo}/pulls/<n> --jq '.head.sha[0:7]')
     F=".[] | select(.author_association | IN(\"OWNER\",\"MEMBER\",\"COLLABORATOR\")) | .body | split(\"\n\")[0] | rtrimstr(\"\r\") | select(test(\"^[^:]+ review at $H: \"))"
     p=1; while :; do
       gh api "repos/{owner}/{repo}/issues/<n>/comments?per_page=100&page=$p" --jq "$F"
       [ "$(gh api "repos/{owner}/{repo}/issues/<n>/comments?per_page=100&page=$p" --jq length)" -lt 100 ] && break
       p=$((p+1))
     done | tail -n 1 | grep -q ': clean$' && echo true || echo false
     ```
   - The worker's report says each acceptance item is met, and the PR body carries `Fixes #N`, `Closes #N`, or `Part of #N`, read as a boolean (`gh api repos/{owner}/{repo}/pulls/<n> --jq '.body | test("(Fixes|Closes|Part of) #<N>([^0-9]|$)")'`, with no backslash, which Git Bash would mangle), not by opening the body.
   - **Environment:** in a cloud session, a rendering PR that [`cloud.md` § Rendering](../working-in-an-environment/cloud.md#rendering) sends to the GPU takes `local-only` and stays unarmed.
     A local-windows run takes such a PR from the queue, runs `mise run judge` on the GPU as the PR body asks, and, when the GPU's verdict matches lavapipe's, removes `local-only` and arms it under this bar; otherwise it fixes the PR as for a failed check.
   - **Allowed vs blocked changes:** the coordinator lists the PR's changed file names (`gh api "repos/{owner}/{repo}/pulls/<n>/files?per_page=100&page=1" --jq '.[].filename'`, next page by number), never the diff; a path under `docs/adr/`, `crates/stunt-core/Cargo.toml` or `research/parity/references.toml` sends a worker or the reviewer to say whether it is a blocked change before arming.
     A draft (`gh api repos/{owner}/{repo}/pulls/<n> --jq .draft` prints `true`) goes to a human without a worker, per the **Never** rule that follows.
     Updating `research/parity/expected/<class>.toml` for an adopted parity change is **allowed** to merge (`crates` must be `git rev-parse HEAD:crates` with `crates/` clean).
     **Never** arm or merge draft PRs, PRs that repin a film's capture hash (`sha256` or `all_sha256` in `references.toml`), PRs that add a dependency to `stunt-core` (`[I7]`), or PRs that add or modify an ADR (unless an accepted ADR is already approved by the user, or its ADR changes only retarget links to follow a move, which the reviewer confirms; link text that spells the old path counts as prose, and prose naming an old path goes to a human) — hand those to a human (`ready-for-human`).
6. **After arming:** Fast-forward the `main` ref without switching any checkout (`git fetch origin main:main`; skip it when git refuses because a checkout has `main` checked out), on local-windows run the disk check and tidy ([`loop-and-bounds.md`](loop-and-bounds.md#clock-and-disk-space)), and refresh the queue.

## Filing issues and PowerShell safety

1. **Search first:** Confirm the target repo on the session's first issue operation (`gh repo view --json nameWithOwner`; cloud: `gh api repos/{owner}/{repo} --jq .full_name`), and search existing issues (`gh issue list --state all --search "<keywords>"`; cloud: `gh api 'search/issues?q=repo:{owner}/{repo}+type:issue+<keywords>'`) to avoid duplicates ([`issue-tracker.md`](../../../docs/agents/issue-tracker.md#organizing-issues)).
2. **Always use `--body-file` on Windows PowerShell 5.1:** PowerShell double quotes (`"..."` and `@"..."@`) treat backticks (`` ` ``) as escape characters and corrupt Markdown code spans.
   Write every issue/PR body or comment to `build/scratch/<name>.md` with the harness's file-write tool (or `[IO.File]::WriteAllText` with a single-quoted `@'...'@` string, [`docs/harness.md`](../../../docs/harness.md#windows-powershell-51)) and pass `--body-file build/scratch/<name>.md`.
   Use full commit-SHA permalinks on `origin/main` when linking code from an issue body.
3. **Labels:** Apply one state label ([`triage-labels.md`](../../../docs/agents/triage-labels.md)):
   - Label a newly filed issue `ready-for-agent` only when it is an unblocked out-of-scope finding that (a) names the files involved, (b) carries the evidence (`file:line`, offset, or command), (c) has a testable done condition, and (d) has no non-obvious design choice.
   - Always label blocked follow-ups split from the current ticket `needs-triage` (or `ready-for-human` when a human decision is the blocker).
   - Add `local-only` when the issue needs a resource only local-windows has ([`triage-labels.md`](../../../docs/agents/triage-labels.md#environment-roles)).
