# Issue tracker: GitHub

Issues and specs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments`.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Make an issue a sub-issue of a parent**: `gh issue create --parent <parent> ...`, or `gh issue edit <parent> --add-sub-issue <child>` afterwards (`gh` 2.94+). Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below). Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation. Add an edge with `gh issue create --blocked-by <n>,<n> ...` or `gh issue edit <child> --add-blocked-by <blocker>` (`gh` 2.94+). Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`). Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- **Count open blockers**: `gh api repos/<owner>/<repo>/issues/<n> --jq .issue_dependencies_summary.blocked_by` (open blockers only; 0 means unblocked, and startable once it also has no open sub-issue: `--jq .sub_issues_summary` total minus completed, or an open issue whose body says `Part of #<n>`). `gh issue view <n> --json blockedBy` also lists closed blockers, so filter it: `--jq '[.blockedBy.nodes[] | select(.state == "OPEN")] | length'`.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Attach an image**: `gh issue edit <n> --body-file body.md --attach './img.png#Alt text'` (also `gh issue create`; `gh` 2.103 or newer). `gh` uploads the file and rewrites each `![alt](./img.png)` in the body to the hosted attachment URL, resolving paths against the body file's directory; an attachment the body does not reference is appended. Use this, not the browser.
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: post the explanation with `gh issue comment <number> --body "..."`, then `gh issue close <number>`. On an already-closed issue, `gh issue close --comment` drops the comment and still exits 0.
- **Close an issue fixed by a stacked PR**: a closing keyword (`Fixes #N`) fires only when the PR merges into the default branch, so an issue whose PR merges into another PR's branch stays open. Once `gh stack merge` lands the stack on `main`, close it by hand as in **Close**, naming the PR.

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

File issues only into the user's own repo. Never file into `mattpocock/skills` (the repo these skills come from) unless the user owns it. In a fork, `gh` can default to the upstream parent, so before the first `gh issue create` of a session, check the target with `gh repo view --json nameWithOwner` and confirm it with the user if it is not their repo.

## Organizing issues

These rules cover every issue except a `wayfinder:*` map or ticket, which `/wayfinder` labels, chooses, resolves and closes by **Wayfinding operations** below.

- **Parents are goals.** A parent issue names an outcome and ends with a `Done when every sub-issue is closed.` line, e.g. #85 (terrain loss), #97 (actors and props). Every parent can close; there is no standing bucket parent. An issue has no parent by default: give it one when a goal fits, and file a short-lived parent only for a batch that has its own `Done when` (as #169 did for lints).
- **An issue with open sub-issues is never startable**, whatever its labels: a spec that `/to-tickets` split keeps its `ready-for-agent` label. Skip it when choosing work.
- **Closing the last child closes the parent.** Whoever closes a parent's last open sub-issue closes the parent too, as in **Close**.
- **Title the problem, not the fix.** State the observed problem or the open question in present tense: "Props shade with a guessed light, not PLAYONE's world light", "Which 20 active MAP.BIN polygons have no ground leaf in PLAYONE's image?". The fix goes in the body.
- **The filer labels the issue.** On `gh issue create`, apply one state label (`needs-triage` when unsure), `research` or `tooling` where either applies ([triage-labels.md](triage-labels.md)), and a parent where a goal fits.
- No milestones or Project board: parents show progress.

## Review threads on a pull request

- **List open threads**: `mise run pr-threads -- <number>` prints one line per unresolved thread (path, line, severity, title) and the comment id to reply to; `--all` keeps resolved ones. After the threads it lists the findings a bot put in a review body instead of a thread ("Outside diff"), from reviews submitted since the head commit (`--all`: every review); those have no thread, so answer them with `gh pr comment`. Reach for it before `gh pr view --comments` or `gh api .../reviews`, whose CodeRabbit bodies run to tens of KB.
- **Reply in a thread**: `gh api -X POST repos/<owner>/<repo>/pulls/<n>/comments/<id>/replies -f body="..."`, with the id `pr-threads` printed.

## Pull requests as a triage surface

**PRs as a request surface: no.** _(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number>`, then `gh pr view <number> --comments` (off a TTY, `--comments` prints only the comments, not the body), and `gh pr diff <number>` for the diff.
- **List external PRs for triage**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42`.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue labelled `wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. `gh issue create --label wayfinder:map`.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**). Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body. Labels: `wayfinder:<type>` (`research`/`prototype`/`grilling`/`task`). Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list), drop any with an open blocker (see **Count open blockers**, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>`, then append a context pointer (gist + link) to the map's Decisions-so-far.
