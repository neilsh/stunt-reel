# Issue tracker: GitHub

Issues for this repo live as GitHub issues; an issue's spec and plan live in its work folder as `spec.md` and `plan.md` ([`work/README.md`](../../work/README.md)).
Use the `gh` CLI for all issue operations.
A cloud session's proxy refuses GraphQL, so `gh issue`, `gh repo view` and `gh pr view` fail there; each bullet below names the REST form (`gh api repos/{owner}/{repo}/...`, which resolves the placeholders from the clone) or the repo helper.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body-file build/scratch/<name>.md` (cloud: `gh api -X POST repos/{owner}/{repo}/issues -F title="..." -F body=@build/scratch/<name>.md`).
  Write every multi-line body to `build/scratch/<name>.md`; never a heredoc.
- **Read an issue**: `gh issue view <number> --json number,title,body,labels,comments` (cloud: `gh api repos/{owner}/{repo}/issues/<number>`, and `.../issues/<number>/comments` for its comments; labels are `.labels[].name`).
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
  Cloud: `gh api 'repos/{owner}/{repo}/issues?state=open&per_page=100&labels=<label>' --jq '[.[] | select(.pull_request | not)]'` (REST lists pull requests as issues too), or `mise run queue` for the unattended queue.
- **Make an issue a sub-issue of a parent**: `gh issue create --parent <parent> ...`, or `gh issue edit <parent> --add-sub-issue <child>` afterwards (`gh` 2.94+).
  Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<parent>/sub_issues -F sub_issue_id=<child-db-id>` (database id, as in **Blocking** below).
  Without sub-issues, put `Part of #<parent>` at the top of the child body.
- **Blocking**: GitHub's **native issue dependencies**, the canonical, UI-visible representation.
  Add an edge with `gh issue create --blocked-by <n>,<n> ...` or `gh issue edit <child> --add-blocked-by <blocker>` (`gh` 2.94+).
  Older `gh`: `gh api --method POST repos/<owner>/<repo>/issues/<child>/dependencies/blocked_by -F issue_id=<blocker-db-id>`, where `<blocker-db-id>` is the blocker's numeric **database id** (`gh api repos/<owner>/<repo>/issues/<n> --jq .id`, _not_ the `#number` or `node_id`).
  Where dependencies aren't available, fall back to a `Blocked by: #<n>, #<n>` line at the top of the child body.
  A ticket is unblocked when every blocker is closed.
- **Count open blockers**: `gh api repos/<owner>/<repo>/issues/<n> --jq .issue_dependencies_summary.blocked_by` (open blockers only; 0 means unblocked, and startable once it also has no open sub-issue: `--jq .sub_issues_summary` total minus completed, or an open issue whose body says `Part of #<n>`).
  `gh issue view <n> --json blockedBy` also lists closed blockers, so filter it: `--jq '[.blockedBy.nodes[] | select(.state == "OPEN")] | length'` (cloud: `gh api repos/{owner}/{repo}/issues/<n>/dependencies/blocked_by --jq '[.[] | select(.state == "open")] | length'`, since that endpoint returns closed blockers too).
- **Comment on an issue**: `gh issue comment <number> --body "..."` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<number>/comments -F body=@build/scratch/<name>.md`)
- **Attach an image**: `gh issue edit <n> --body-file body.md --attach './img.png#Alt text'` (also `gh issue create`; `gh` 2.103 or newer).
  `gh` uploads the file and rewrites each `![alt](./img.png)` in the body to the hosted attachment URL, resolving paths against the body file's directory; an attachment the body does not reference is appended.
  Use this, not the browser.
  Cloud: update the body with `gh api -X PATCH repos/{owner}/{repo}/issues/<n> -F body=@body.md`; `--attach` has no REST form, so an upload needs the local `gh`.
- **Link code from an issue body**: use a permalink at a full commit SHA on `origin/main` (`https://github.com/<owner>/<repo>/blob/<sha>/<path>#L<line>`, SHA from `git fetch origin` then `git rev-parse origin/main`).
  A relative path resolves against the issue URL and 404s, and a branch link points at different lines as the file changes.
  A file only on an unmerged branch gets a permalink at that branch's pushed commit SHA, not the branch name, which 404s once the branch is deleted on merge.
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<number>/labels -f labels[]=<label>` adds, `gh api -X DELETE repos/{owner}/{repo}/issues/<number>/labels/<label>` removes)
- **Claim an issue**: a session's first write on an issue it will work, before any branch commit or planner read.
  Re-read its labels; if it already carries `status:in-progress`, it is taken: pick another or ask the user.
  Otherwise `gh issue edit <n> --remove-label status:ready-for-agent --add-label status:in-progress` (or `status:needs-plan` / `status:ready-for-human`), then `gh issue comment <n> --body "Claimed by branch <branch>."` (for a planner on `status:needs-plan`, `Claimed by planner <id>.`), then re-read the comments: the earliest `Claimed by branch` or `Claimed by planner` since the latest `Released claim:` holds the issue, and a later claimant comments `Lost claim to <holder>.`, leaves the labels alone and picks another.
  The holder re-reads the labels and adds `status:in-progress` if it is missing.
  A session that stops without a PR or tentative plan comments `Released claim: <why>.`, then swaps the label back.
  Cloud: the label and comment REST forms above, re-reading them with `gh api repos/{owner}/{repo}/issues/<n> --jq '[.labels[].name]'`.
  An issue carrying `status:in-progress` whose named branch is gone (or whose planner claim is stale), with no open PR or tentative plan, is a dropped claim: ask the user before taking it over, then comment `Released claim: <holder> dropped it.` before your own claim.
  When choosing work, skip issues carrying `status:in-progress`.
- **Close**: post the explanation with `gh issue comment <number> --body "..."`, then `gh issue close <number>` (cloud: the comment form above, then `gh api -X PATCH repos/{owner}/{repo}/issues/<number> -f state=closed`).
  On an already-closed issue, `gh issue close --comment` drops the comment and still exits 0.
  Closing, by `gh` or a merged `Fixes #N`, removes every `status:*` label: the `project-sync` workflow's `clear-status` job does it, and no status label survives a close.
- **Cite what you read**: before posting a comment or issue body that cites a file:line or a figure, read each cited line once (`rg -n`, `sed -n`) and drop any it does not bear out; a subagent's report is a lead, not a citation.
- **Close an issue fixed by a stacked PR**: a closing keyword (`Fixes #N`) fires only when the PR merges into the default branch, so an issue whose PR merges into another PR's branch stays open.
  Once `gh stack merge` lands the stack on `main`, close it by hand as in **Close**, naming the PR.

Infer the repo from `git remote -v`; `gh` does this automatically when run inside a clone.

File issues only into the user's own repo.
Never file into `mattpocock/skills` (the repo these skills come from) unless the user owns it.
In a fork, `gh` can default to the upstream parent, so before a session's first issue search, comment or `gh issue create`, check the target with `gh repo view --json nameWithOwner` (cloud: `gh api repos/{owner}/{repo} --jq .full_name`) and confirm it with the user if it is not their repo.

## Organizing issues

These rules cover every issue, except that the map and tickets `/wayfinder` chooses, resolves and closes follow **Wayfinding operations** below for parents, claiming and closing; they still take a `status:` label.

- **Parents are goals.**
  A parent issue names an outcome and ends with a `Done when every sub-issue is closed.` line, e.g. #85 (terrain loss), #97 (actors and props).
  Every parent can close; there is no standing bucket parent.
  An issue has no parent by default: give it one when a goal fits, and file a short-lived parent only for a batch that has its own `Done when` (as #169 did for lints).
- **An issue with open sub-issues is never startable**, whatever its labels: a spec that `/to-tickets` split keeps its `status:ready-for-agent` label.
  Skip it when choosing work.
- **Closing the last child closes the parent.**
  Whoever closes a parent's last open sub-issue closes the parent too, as in **Close**.
  Triage lists any parent this missed: `gh api 'repos/{owner}/{repo}/issues?state=open&per_page=100' --jq '.[] | select(.sub_issues_summary.total > 0 and .sub_issues_summary.completed == .sub_issues_summary.total) | .number'`.
- **A prototype lives on a branch.**
  Push a prototype or spike diff to a branch and name the branch and commit in the body.
  A diff pasted into the body goes stale as `main` moves, cannot be rebased, and makes every read of the issue tens of KB.
- **Title the problem, not the fix.**
  State the observed problem or the open question in present tense: "Props shade with a guessed light, not PLAYONE's world light", "Which 20 active MAP.BIN polygons have no ground leaf in PLAYONE's image?".
  The fix goes in the body.
- **Search before filing.**
  Before `gh issue create`, run `gh issue list --state open --search "<key terms>"` (cloud: `gh api 'search/issues?q=repo:{owner}/{repo}+type:issue+<terms>'`) with the symptom's distinctive words (the error, the file, the film).
  On a clear match, add the new sighting as a comment there instead of filing a duplicate.
- **The filer labels the issue.**
  On `gh issue create`, apply one state label (`status:needs-triage` when unsure, or `status:needs-plan` when it needs read-only planning before coding), one or more primary-subsystem `area:` labels, a `type:` contract label (`type:research`, `type:fidelity` or `type:perf`) where applicable, `env:local-only` where only `local-windows` can do it ([triage-labels.md](triage-labels.md)), and a parent where a goal fits; leave `priority:` unset so unprioritized issues stand out for maintainer prioritization.
  Cloud: the create and label forms above.
- No milestones; parents show progress.
  The owner's [Issue Radar](https://github.com/users/neilsh/projects/1) project is a dashboard the `project-sync` workflow derives (`Status` and `Priority`) from labels and issue state ([`project_sync.py`](../../python/scripts/project_sync.py)); agents never read or write it, and a cloud session cannot, since Projects is GraphQL-only.

## Review threads on a pull request

- **List open threads**: `mise run pr-threads -- <number>` prints one line per unresolved thread (path, line, severity, title) and the comment id to reply to; `--all` keeps resolved ones.
  After the threads it lists the findings a bot put in a review body instead of a thread ("Outside diff" and "Additional comments"), from reviews submitted since the head commit (`--all`: every review); those have no thread, so answer them with `gh pr comment` (cloud: `gh api -X POST repos/{owner}/{repo}/issues/<number>/comments -F body=@<file>`).
  Reach for it before `gh pr view --comments` or `gh api .../reviews`, whose CodeRabbit bodies run to tens of KB (cloud: `gh api repos/{owner}/{repo}/issues/<number>/comments`).
- **Reply in a thread**: `mise run pr-threads -- <number> --reply <id> --body "..."`, with the id `pr-threads` printed; `--body-file <path>` (`-` for stdin) takes a longer reply.
- **Resolve a thread**: `mise run pr-threads -- <number> --resolve <id>` resolves the thread that comment starts.
  Give it with `--reply` to answer and resolve in one call; the reply goes first.

## Pull requests as a triage surface

**PRs as a request surface: no.**
_(Set to `yes` if this repo treats external PRs as feature requests; `/triage` reads this flag.)_

When set to `yes`, PRs run through the same labels and states as issues, using the `gh pr` equivalents:

- **Read a PR**: `gh pr view <number>`, then `gh pr view <number> --comments` (off a TTY, `--comments` prints only the comments, not the body), and `gh pr diff <number>` for the diff.
  Cloud: `gh api repos/{owner}/{repo}/pulls/<number>`, `.../issues/<number>/comments`, and `gh api repos/{owner}/{repo}/pulls/<number> -H "Accept: application/vnd.github.diff"`.
- **List external PRs for triage**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`.
- **Comment / label / close**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`.
  Cloud: `gh api -X POST repos/{owner}/{repo}/issues/<number>/comments -F body=@<file>`, the label routes above, and `gh api -X PATCH repos/{owner}/{repo}/pulls/<number> -f state=closed`.

GitHub shares one number space across issues and PRs, so a bare `#42` may be either: resolve with `gh pr view 42` and fall back to `gh issue view 42` (cloud: `gh api repos/{owner}/{repo}/pulls/42`, falling back to `.../issues/42`).

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Read it as in **Read an issue** above.

## Wayfinding operations

Used by `/wayfinder`.
A map and its tickets carry a `status:` label like any other issue; there are no `wayfinder:*` labels.
The **map** is a single issue with **child** issues as tickets.

- **Map**: a single issue holding the Notes / Decisions-so-far / Fog body.
- **Child ticket**: an issue linked to the map as a GitHub sub-issue (see **Make an issue a sub-issue of a parent**).
  Where sub-issues aren't enabled, add the child to a task list in the map body and put `Part of #<map>` at the top of the child body.
  Once claimed, the ticket is assigned to the driving dev.
- **Blocking**: see **Blocking** under Conventions.
- **Frontier query**: list the map's open children (`gh issue list --state open`, scoped to the map's sub-issues / task list; cloud: `gh api 'repos/{owner}/{repo}/issues?state=open&per_page=100' --jq '[.[] | select(.pull_request | not)]'`), drop any with an open blocker (see **Count open blockers**, or an open issue in the `Blocked by` line) or an assignee; first in map order wins.
- **Claim**: `gh issue edit <n> --add-assignee @me`, the session's first write.
  Cloud: `gh api -X POST repos/{owner}/{repo}/issues/<n>/assignees -f assignees[]=<login>`, with `<login>` from `gh api user --jq .login`.
- **Resolve**: `gh issue comment <n> --body "<answer>"`, then `gh issue close <n>` (cloud: the comment and close forms above), then append a context pointer (gist + link) to the map's Decisions-so-far.
