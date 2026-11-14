# Reviewer PR comments (#507) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every reviewer verdict in an unattended run lands as a SHA-stamped PR comment, and the merge bar requires a `clean` comment at the PR's current head.

**Architecture:** Two edits to `running-unattended/pr-and-filing.md` (review step, merge bar) and one to `SKILL.md` (checklist line). The agent checks by running one `gh` command; no script, no `mise` task.

**Tech Stack:** Markdown skill text, `gh`, `mise run check`.

**Spec:** GitHub issue #507 (`gh issue view 507 --comments`). Retro items 1-3 are #508 and out of scope. No mechanical check in `mise run queue` or `pr-threads`.

## Global Constraints

- Edit only `.agents/skills/running-unattended/pr-and-filing.md` and `.agents/skills/running-unattended/SKILL.md`. Do not touch any other file, and do not edit `loop-and-bounds.md`.
- Keep the existing step numbers 1-6 in `pr-and-filing.md`.
- Use the old text exactly as quoted when locating an edit; use the Edit tool, one edit per step.
- No `docs/*.md`, `research/`, `NOTICE.md` or `docs/howto/` file changes, so `AGENTS.md` §3 rule 5 (fresh review before push) is not triggered by your commit. If you changed any of those, stop and ask. This `plan.md` and its README are already committed on the plans branch; do not stage them.
- Commit with a Conventional Commit subject; stage files by name.

## Review Focus

- A `clean` comment at an older SHA must not satisfy the bar (the `gh` command matches the current head's 7-character short SHA).
- A `needs changes` comment at the current head, posted after a `clean` one, blocks the bar (the command takes the newest matching comment).
- A comment whose first line is not `<Reviewer> review at <7-char SHA>: <verdict>` does not count (the command matches the first line only).

### Task 1: Comment contract and merge bar

- [ ] **Step 0: Branch.** In Git Bash run `git status --porcelain` (expected: no output; any line: STOP), then `git fetch origin && git switch -c docs/507-reviewer-pr-comments origin/neilsh/open-tasks-dsh` (the plans branch, PR #514; it need not be merged). Expected: `Switched to a new branch 'docs/507-reviewer-pr-comments'`.

**Files:**
- Modify: `.agents/skills/running-unattended/pr-and-filing.md` (step 2 at line 8, step 5 second bullet at line 17)
- Modify: `.agents/skills/running-unattended/SKILL.md` (checklist item 4 at line 25)

**Interfaces:**
- Produces: the review-comment first line `<Reviewer> review at <head SHA>: <verdict>` and the check command; both are quoted below and must be copied verbatim.

- [ ] **Step 1: Replace step 2 of `pr-and-filing.md`.** Old text (the whole line, starting `2. **Fresh-context review:**`):

```
2. **Fresh-context review:** Dispatch one review subagent (`inherit`) to review the diff against the merge base for `AGENTS.md` standards and `docs/SPEC.md` compliance (plus `AGENTS.md` Committing rule 5 when the diff touches `research/`, `NOTICE.md`, `docs/howto/` or `docs/*.md`).
```

New text (replace the line with all of this, including the indented block):

````
2. **Fresh-context review:** Dispatch one review subagent (`inherit`) to review the diff against the merge base for `AGENTS.md` standards and `docs/SPEC.md` compliance (plus `AGENTS.md` Committing rule 5 when the diff touches `research/`, `NOTICE.md`, `docs/howto/` or `docs/*.md`). Every reviewer brief, whatever the reviewer (Claude subagent, Orca worker or Antigravity), ends with this instruction, copied into the brief word for word:

   > Post your verdict as a PR comment with `gh pr comment <n> --body-file build/scratch/review-<n>.md`, clean included, Its first line is exactly `<Reviewer> review at <7-char head SHA>: clean` or `<Reviewer> review at <7-char head SHA>: needs changes`, with no `:` in `<Reviewer>`; then your findings, or one line saying what you checked. Reply with the comment's URL.

   **Review-comment template.** The comment's first line is exactly `<Reviewer> review at <head SHA>: <verdict>`, then your findings or one summary line:
   - `<Reviewer>` is the reviewer's own name, with no `:` in it: `Sonnet`, `Opus`, `Antigravity`, or the worker's agent name.
   - `<head SHA>` is the 7-character short SHA printed by `gh pr view <n> --json headRefOid --jq '.headRefOid[0:7]'` , read when you start reviewing and again before you post. If it changed, review the new head.
   - `<verdict>` is `clean` (no finding left to fix) or `needs changes`.

   ```
   Sonnet review at 0123456: needs changes
   - crates/x/src/y.rs:42 the doc says "all"; the test covers one case.
   ```

   ```
   Sonnet review at 0123456: clean
   Read the diff against origin/main; no findings.
   ```

   A reviewer that cannot post returns this text as its reply, and you post it unchanged. After you push a fix, the next review posts a new comment at the new head; the merge bar reads only comments at the current head.
````

- [ ] **Step 2: Replace the second bullet of step 5 in `pr-and-filing.md`.** Old text:

```
   - Zero unresolved review threads remain, every outside-diff finding is answered, and the fresh-context `inherit` review is clean.
```

New text:

````
   - Zero unresolved review threads remain, every outside-diff finding is answered, and a review comment at `HEAD` says `clean`: run the command below and read its output. The bar is met only when it prints `true`. On `false` (no comment at `HEAD`, a comment only at an older SHA, or the newest comment at `HEAD` says `needs changes`), dispatch a new review at `HEAD`.

     ```
     gh pr view <n> --json headRefOid,comments --jq '.headRefOid[0:7] as $h | [.comments[].body | split("\n")[0] | rtrimstr("\r") | select(test("^[^:]+ review at " + $h + ": "))] | last | (. // "") | test(": clean$")'
     ```
````

- [ ] **Step 3: Update checklist item 4 in `SKILL.md`.** Old text:

```
- [ ] 4. Run fresh-context inherit review, triage CI and CodeRabbit threads, and arm squash auto-merge under the merge bar (pr-and-filing.md)
```

New text:

```
- [ ] 4. Run fresh-context inherit review (its verdict comment on the PR at HEAD), triage CI and CodeRabbit threads, and arm squash auto-merge under the merge bar (pr-and-filing.md)
```

- [ ] **Step 4: Test the `gh` command read-only.** The command only reads. Run it with `<n>` replaced by `498` from Git Bash (not PowerShell, whose 5.1 splits `--jq` quotes). Expected output: `true`, because the newest #498 comment stamped with its head's short SHA is `Sonnet review at 327733c: clean` (checked 2026-11-14). If it prints `false`, report that instead of changing the command.

- [ ] **Step 5: Run the gate.** Run `mise run check`. Expected: exits 0 with no warnings. If a doc-health or markdown lint error names the edited files, fix that line and rerun; do not run any task other than `mise run` tasks.

- [ ] **Step 6: Commit.** Run `git status`; stage by name:

```bash
git add .agents/skills/running-unattended/pr-and-filing.md .agents/skills/running-unattended/SKILL.md
git commit -F - <<'EOF'
docs(skills): require SHA-stamped reviewer PR comments and a clean one at HEAD (#507)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 7: Push and open the PR.** `git push -u origin HEAD`, then open the PR against `main` with the `pr` skill: title as the commit subject, `Closes #507`, and one line saying it carries the plans commit from PR #514.

## Self-Review

- Issue criterion 1 (format, who posts, Antigravity briefs require it): Step 1 (brief instruction covers every reviewer type).
- Criterion 2 (merge bar needs clean at current head): Step 2.
- Criterion 3 (`mise run check` passes): Step 5.
- Proportion: three edits for a three-criterion issue.

- [ ] **Step 8: Sync with `main` before merging.** This branch and its sibling PRs (#514 and the other plans' PRs) each carry the same plans commit, and a sibling's squash merge does not make that commit an ancestor here. So after any sibling has merged, and before this PR merges, run in Git Bash: `git fetch origin && git merge origin/main`. An add/add conflict under `work/2026-11/` is expected: for each conflicted path under `work/2026-11/507_reviewer-pr-comments/`, run `git checkout --ours -- <path>`; for each other conflicted path under `work/2026-11/`, run `git checkout --theirs -- <path>`. Then `git add` those paths, `git commit --no-edit`, run `mise run check` (expect `PASS`), and push. Any conflict outside `work/2026-11/`: STOP and report.
