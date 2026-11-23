# Triage Labels

The skills speak in terms of canonical triage roles.
This file maps those roles to the actual label strings used in this repo's issue tracker.
Every name is prefixed — `status:`, `type:`, `env:` or `area:` — and each prefix carries one color, so a label list reads by group.
The strings the scripts use live once in [`python/scripts/labels.py`](../../python/scripts/labels.py).

## State roles

| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `needs-triage` | `status:needs-triage` | Not yet evaluated; the maintainer decides its state |
| `needs-info` | `status:needs-info` | Waits on a fact only a person can supply |
| `ready-for-agent` | `status:ready-for-agent` | Fully specified, ready for an AFK agent |
| `ready-for-human` | `status:ready-for-human` | Requires human implementation |
| _not in the template_ | `status:in-progress` | A session has claimed it; its claim comment names the branch |
| `wontfix` | _not used_ | Close the issue as "not planned" instead |

`duplicate` is not a label either: close the issue with GitHub's "duplicate" reason.

A fact an agent can find (a probe, capture, census or static read) labels an issue `status:ready-for-agent`, with the brief saying how to find it, and adds `type:research` only when the deliverable is the note itself, since a `type:research` issue closes on that note (**Category roles**); `status:needs-info` is for what only a person knows, such as what the filer meant.
An agent can run DOSBox and DOSBox-X captures and breakpoint sessions, so needing one does not make an issue `status:ready-for-human`.
Use `status:ready-for-human` for a design or visual judgment call, or a step no agent can do (admin rights, an asset not in the data root); the brief names which.
Work only `local-windows` can do is `env:local-only` (**Environment roles**), not `status:ready-for-human`.

`status:in-progress` is our addition to the template's flow: every session acts as the same GitHub user, so an assignee cannot say which session holds an issue.
A session takes it from `status:ready-for-agent` or `status:ready-for-human` by **Claim an issue** ([issue-tracker.md](issue-tracker.md#conventions)).

Every open issue without sub-issues carries exactly one state label.
A parent needs none, and any it carries is ignored ([issue-tracker.md § Organizing issues](issue-tracker.md#organizing-issues)).
Blocking is a native issue dependency ([issue-tracker.md](issue-tracker.md)), never a label.

## Category roles

| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `bug` | _not used_ | Nearly every product issue is "the render differs from the capture", so the label separated nothing |
| `enhancement` | _not used_ | As above |

This repo's category labels instead say what finishing the issue means.
Apply at most one; an issue with neither is a code change to the reconstruction.

| Label | Meaning |
| --- | --- |
| `type:research` | Done when a `research/` note answers the question; the closing comment links the note |
| `type:tooling` | Work on the dev environment (gate, hooks, worktrees, PR tooling), not the reconstruction |

## Environment roles

An environment label says where an issue can run.
It goes beside the state label, so an issue can be `status:ready-for-agent` and `env:local-only`.

| Label | Meaning |
| --- | --- |
| `env:local-only` | Needs a resource a cloud session lacks, so a `local-windows` session does it ([`working-in-an-environment`](../../.agents/skills/working-in-an-environment/SKILL.md)): DOSBox-X or `play` (a cloud session runs dosbox-automation's `capture-ref` and `make-all`: [cloud-sessions.md](../cloud-sessions.md#running-the-emulator)), GPU timing, a GPU render such as the class agreement batch ([`run-the-agreement-batch.md`](../howto/run-the-agreement-batch.md)), the owner's `wrangler login` for archive uploads ([ADR 0039](../adr/0039-cloud-sessions-fetch-pinned-game-archives.md)), or a data-root file the cloud archives do not hold. Rendering, scoring and pixel-level work such as a `background` band are not one, and no rendering PR waits for the GPU: fidelity is judged and pinned on the canonical lavapipe ([ADR 0055](../adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)). It goes on a PR as well as an issue. The brief names the resource |

An asset missing from the data root itself still makes an issue `status:ready-for-human`.
A `local-windows` session that finds the resource unavailable (a lapsed login, no GPU adapter) releases its claim ([issue-tracker.md](issue-tracker.md#conventions)) with `Released claim: <resource> unavailable (<error>).`, relabels the issue `status:ready-for-human`, and names the one command a person must run.

## Area roles

An area label marks a component a script or a recurring search follows; add one only then.

| Label | Meaning |
| --- | --- |
| `area:class-agreement` | A flag in the lavapipe-versus-GPU class agreement (#908), applied by [`parity_agreement.py`](../../python/scripts/parity_agreement.py) |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from these tables.
