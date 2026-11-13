# Triage Labels

The skills speak in terms of canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

## State roles

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| _not in the template_      | `in-progress`        | A session has claimed it; its claim comment names the branch |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

An agent can run DOSBox and DOSBox-X captures and breakpoint sessions, so needing one does not make an issue `ready-for-human`. Use `ready-for-human` for a design or visual judgment call, or a step no agent can do (admin rights, an asset not in the data root); the brief names which. Work only the primary machine can do is `local-only` (**Environment roles**), not `ready-for-human`.

`in-progress` is our addition to the template's flow: every session acts as the same GitHub user, so an assignee cannot say which session holds an issue. A session takes it from `ready-for-agent` or `ready-for-human` by **Claim an issue** ([issue-tracker.md](issue-tracker.md#conventions)).

Every open issue without sub-issues carries exactly one state label. A parent needs none, and any it carries is ignored ([issue-tracker.md § Organizing issues](issue-tracker.md#organizing-issues)); a `wayfinder:*` map or ticket carries none, as `/wayfinder` requires. Blocking is a native issue dependency ([issue-tracker.md](issue-tracker.md)), never a label.

## Category roles

| Label in mattpocock/skills | Label in our tracker | Meaning |
| -------------------------- | -------------------- | ------- |
| `bug`                      | _not used_           | Nearly every product issue is "the render differs from the capture", so the label separated nothing |
| `enhancement`              | _not used_           | As above |

This repo's category labels instead say what finishing the issue means. Apply at most one; an issue with neither is a code change to the reconstruction.

| Label      | Meaning |
| ---------- | ------- |
| `research` | Done when a `research/` note answers the question; the closing comment links the note |
| `tooling`  | Work on the dev environment (gate, hooks, worktrees, PR tooling), not the reconstruction |

## Environment roles

An environment label says where an issue can run. It goes beside the state label, so an issue can be `ready-for-agent` and `local-only`.

| Label        | Meaning |
| ------------ | ------- |
| `local-only` | Needs a resource a cloud session lacks, so a session on the primary machine does it: a real GPU (the cloud renders on lavapipe, [ADR 0039](../adr/0039-cloud-sessions-fetch-pinned-game-archives.md)), DOSBox or DOSBox-X ([cloud-sessions.md](../cloud-sessions.md#the-cloud-setup)), the owner's `wrangler login` for archive uploads (ADR 0039), or a data-root file the cloud archives do not hold. The brief names the resource |

An asset missing from the data root itself still makes an issue `ready-for-human`. A primary-machine session that finds the resource unavailable (a lapsed login, no GPU adapter) releases its claim ([issue-tracker.md](issue-tracker.md#conventions)) with `Released claim: <resource> unavailable (<error>).`, relabels the issue `ready-for-human`, and names the one command a person must run.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from these tables.
