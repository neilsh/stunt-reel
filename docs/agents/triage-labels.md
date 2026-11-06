# Triage Labels

The skills speak in terms of canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

## State roles

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified, ready for an AFK agent  |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation            |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

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

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from these tables.
