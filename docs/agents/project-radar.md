# Project radar: GitHub Projects v2

**For humans only.** Agents never read this file for instructions, never run `gh project …`, and never set a project field. The project is a read-only lens over the labels, sub-issues and `Blocked by` links that the skills already write; see [`issue-tracker.md`](issue-tracker.md) and [`triage-labels.md`](triage-labels.md) for what agents do.

- **Project:** [stunt-reel AI Engineering Radar](https://github.com/users/neilsh/projects/1), number `1`, owned by the user `neilsh` and linked to `neilsh/stunt-reel`.
- **Created:** 2026-11-04, with every issue open that day added to it. GitHub also pulled in some closed sub-issues of those issues; the views below hide them with `is:open`.

## How it pairs with the skills

Every column a view filters on comes from something a skill already writes:

| Skill | What it writes | Where it shows up |
|---|---|---|
| `/triage` | `needs-triage`, `needs-info`, `ready-for-human`, `ready-for-agent`, `wontfix` | View 1, then View 2 or 3 |
| `/to-spec` | a spec issue labelled `ready-for-agent` | View 2 (no parent) |
| `/to-tickets` | sub-issues of the spec, `ready-for-agent`, native `Blocked by` links | View 3 (grouped by parent) |
| `/implement`, `/implement-spec` | branches and pull requests that close the slices | View 3, *Linked pull requests* |
| `/wayfinder` | a `wayfinder:map` issue and child tickets labelled `wayfinder:research`, `prototype`, `grilling` or `task` | View 4 |

Wayfinder tickets never carry `ready-for-agent` (they are decisions, not implementation), so they never appear in Views 2 and 3.

## Views

GitHub's API cannot create project views, so make these four by hand: open the project, choose **New view**, set the layout, paste the filter, then pick the fields from the **View** menu. *Parent issue* filters as `parent-issue`, so `no:parent-issue` and `has:parent-issue` select specs and slices.

### 1. External Triage (intake)

- **Layout:** Board. Columns stay on *Status*; set **Slice by → Labels** for one lane per triage state.
- **Filter:** `is:open label:needs-triage,needs-info,ready-for-human`
- **Use:** run `/triage #ID` on anything in `needs-triage`; chase `needs-info`; pick up `ready-for-human` yourself. Incoming reports stay out of the feature backlog.

### 2. Spec Backlog & Fleet Queue (whole features)

- **Layout:** Table.
- **Filter:** `is:open label:ready-for-agent no:parent-issue`
- **Fields:** Title, Assignees, Labels, Sub-issues progress, Updated.
- **Rule:** Sub-issues 0 → `/to-tickets #ID` to slice the spec. Sub-issues > 0 → `/implement-spec #ID` to dispatch worktree subagents.

### 3. Implementation Frontier (single-session queue)

- **Layout:** Table, **Group by → Parent issue**.
- **Filter:** `is:open label:ready-for-agent has:parent-issue`
- **Fields:** Title, Parent issue, Linked pull requests, and *Blocked by* if the field picker offers it.
- **Rule:** `/implement #ID` only on a slice with no open blocker. Without a *Blocked by* column, check the issue's sidebar, or `gh api repos/neilsh/stunt-reel/issues/<n> --jq .issue_dependencies_summary.blocked_by` (0 means startable).

### 4. Wayfinder Radar (clearing the fog)

- **Layout:** Table (or Board), **Group by → Parent issue**.
- **Filter:** `is:open label:wayfinder:map,wayfinder:research,wayfinder:prototype,wayfinder:grilling,wayfinder:task`
- **Use:** track the human-in-the-loop `grilling` decisions and background `research` spikes under each map until the map collapses into `/to-spec`.

## Workflows

In the project, open **⋯ → Settings → Workflows** and turn on:

- **Auto-add to project:** repository `neilsh/stunt-reel`, filter `is:issue`, so new issues land without anyone running `gh project`.
- **Item closed:** set *Status* to `Done`.
- **Pull request merged:** set *Status* to `Done`.

## Zero agent overhead

`/triage`, `/to-spec`, `/to-tickets` and `/implement` touch only labels, issue bodies, sub-issues and dependency links, all through the `repo` scope agents already have. They need no `project` scope, read nothing here, and spend no tokens on the board: the workflows above and the filters keep it current.

## Permissions used to set it up

Setup used a short-lived classic token with only `project` and `public_repo`, exposed as `GH_TOKEN`. `gh project create --owner "@me"` works with it (`--owner neilsh` fails with "unknown owner type"), but `gh project link` and `item-add` insist on `read:org`, so linking and backfill called the GraphQL API directly: `linkProjectV2ToRepository` and `addProjectV2ItemById` through `gh api graphql`. Delete that token, and unset `GH_TOKEN`, once the views are made.
