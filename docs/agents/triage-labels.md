# Triage Labels

The skills speak in terms of canonical triage roles.
This file maps those roles to the actual label strings used in this repo's issue tracker.
Every name is prefixed — `status:`, `priority:`, `type:`, `env:`, `area:`, `model-tier:` or `model-context:` — and the canonical catalog (names, hex colors, descriptions) lives in [`python/scripts/labels.py`](../../python/scripts/labels.py).
Run `mise run label-sync` (`-- --apply` to write) to synchronize GitHub repository labels with that catalog.

Priority claims the warm urgency arc at high saturation (`#B60205` red, `#D93F0B` orange, `#DBAB09` amber) plus muted gray (`#6E7781`) for low intensity.
Every other prefix carries one muted color in the cool band (`status:` steel blue `#4A7BB5`, `type:` muted violet `#7A63B5`, `env:` muted teal `#3B867C`, `area:` sage green `#4E8A5C`, `model-tier:` slate teal `#4C8A9E`, `model-context:` orchid `#8A5FA8`), so high visual urgency belongs exclusively to `priority:`.

## State roles

| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `needs-triage` | `status:needs-triage` | Not yet evaluated; the maintainer decides its state |
| `needs-info` | `status:needs-info` | Waits on a fact only a person can supply |
| _not in the template_ | `status:needs-plan` | Ready for a planner agent to investigate and post a tentative plan comment |
| _not in the template_ | `status:plan-review` | Tentative plan comment posted; awaiting human approval or decision |
| `ready-for-agent` | `status:ready-for-agent` | Fully specified and unambiguous, ready for an AFK implementer |
| `ready-for-human` | `status:ready-for-human` | Requires human implementation, credentials, or an unresearched design/visual judgment call |
| _not in the template_ | `status:in-progress` | A session has claimed it; its claim comment names the branch or planner |
| `wontfix` | _not used_ | Close the issue as "not planned" instead |

`duplicate` is not a label either: close the issue with GitHub's "duplicate" reason.

A fact an agent can find (a probe, capture, census or static read) labels an issue `status:ready-for-agent`, with the brief saying how to find it, and adds `type:research` only when the deliverable is the note itself, since a `type:research` issue closes on that note (**Category roles**); `status:needs-info` is for what only a person knows, such as what the filer meant.
An agent can run DOSBox and DOSBox-X captures and breakpoint sessions, so needing one does not make an issue `status:ready-for-human`.
Use `status:needs-plan` when an issue needs read-only investigation or decomposition into a tentative plan before implementation; the planner posts a `## Tentative plan` comment, applies the `model-tier:` and any `model-context:` labels it names (**Model roles**), and routes either to `status:plan-review` (when decisions, ambiguity or a multi-PR split remain) or straight to `status:ready-for-agent` (when purely mechanical, after a fresh-context review of the comment).
Use `status:ready-for-human` for an unresearched design or visual judgment call, or a step no agent can do (admin rights, an asset not in the data root); the brief names which.
Work only `local-windows` can do is `env:local-only` (**Environment roles**), not `status:ready-for-human`.

`status:in-progress` is our addition to the template's flow: every session acts as the same GitHub user, so an assignee cannot say which session holds an issue.
A session takes it from `status:ready-for-agent`, `status:needs-plan` or `status:ready-for-human` by **Claim an issue** ([issue-tracker.md](issue-tracker.md#conventions)).

Every open issue without sub-issues carries exactly one state label.
A parent needs none, and any it carries is ignored ([issue-tracker.md § Organizing issues](issue-tracker.md#organizing-issues)).
A `type:tracking` parent (**Category roles**) carries none.
Blocking is a native issue dependency ([issue-tracker.md](issue-tracker.md)), never a label.

## Priority roles

Priority is always explicit once set: an absent `priority:` label means an issue has not been prioritized yet.
When filing an issue, agents leave `priority:` unset so unprioritized items stand out for maintainer triage.

| Label | Meaning |
| --- | --- |
| `priority:p0` | Urgent: broken gate/CI, active blocker, or critical regression |
| `priority:p1` | High: current milestone or high-leverage fidelity, perf, or workflow win |
| `priority:p2` | Normal: standard backlog work |
| `priority:p3` | Low: nice-to-have cleanup, polish, or deferred debt |

`mise run queue` sorts `status:ready-for-agent` and `status:needs-plan` items from `priority:p0` down to `priority:p3`, then unprioritized items (marked `unprioritized`), breaking equal-priority ties with `ready-for-agent` before `needs-plan` and then issue number.

## Category roles

| Label in mattpocock/skills | Label in our tracker | Meaning |
| --- | --- | --- |
| `bug` | _not used_ | Nearly every product issue is "the render differs from the capture", so the label separated nothing |
| `enhancement` | _not used_ | As above |

This repo's `type:` labels instead state the verification or closing contract when it differs from a standard code, tooling or docs change (apply at most one; standard changes carry none).
The older `type:tooling` label is retired in favor of `area:tooling` and `area:agents`.

| Label | Meaning |
| --- | --- |
| `type:research` | Done when a `research/` note answers the question; no code fix required; the closing comment links the note |
| `type:fidelity` | Visual parity change following [`improving-render-parity`](../../.agents/skills/improving-render-parity/SKILL.md); avoid running or merging two repinning PRs concurrently |
| `type:perf` | Performance change requiring A/B timing (`mise run ab`, which refuses concurrent `stuntreel`/`cargo` runs) and output equivalence |
| `type:tracking` | A parent with no work of its own: done when every sub-issue is closed |

A `type:tracking` parent needs no other label: its sub-issues carry the state, `area:`, `env:`, `model-` and contract labels for the work, so it drops any it had, keeping only an optional `priority:` for the dashboard.
A parent that still owns work, such as a design note or a gate the sub-issues do not cover, is not one and keeps the usual labels.
The [Issue Radar](https://github.com/users/neilsh/projects/1) files a `type:tracking` issue under `Goal` even before its sub-issues are linked.

## Environment roles

An environment label says where an issue can run.
It goes beside the state label, so an issue can be `status:ready-for-agent` and `env:local-only`.

| Label | Meaning |
| --- | --- |
| `env:local-only` | Needs a resource a cloud session lacks, so a `local-windows` session does it ([`working-in-an-environment`](../../.agents/skills/working-in-an-environment/SKILL.md)): DOSBox-X or `play` (a cloud session runs dosbox-automation's `capture-ref` and `make-all`: [cloud-sessions.md](../cloud-sessions.md#running-the-emulator)), GPU timing, a GPU render such as the class agreement batch ([`run-the-agreement-batch.md`](../howto/run-the-agreement-batch.md)), the owner's `wrangler login` for archive uploads ([ADR 0039](../adr/0039-cloud-sessions-fetch-pinned-game-archives.md)), or a data-root file the cloud archives do not hold. Rendering, scoring and pixel-level work such as a `background` band are not one, and no rendering PR waits for the GPU: fidelity is judged and pinned on the canonical lavapipe ([ADR 0055](../adr/0055-fidelity-pins-on-lavapipe-and-agreement-is-measured-apart.md)). It goes on a PR as well as an issue. The brief names the resource |

An asset missing from the data root itself still makes an issue `status:ready-for-human`.
A `local-windows` session that finds the resource unavailable (a lapsed login, no GPU adapter) releases its claim ([issue-tracker.md](issue-tracker.md#conventions)) with `Released claim: <resource> unavailable (<error>).`, relabels the issue `status:ready-for-human`, and names the one command a person must run.

## Area roles

Area labels name the primary owned subsystem(s) of an issue; apply one or more when an issue spans subsystems, and use disjoint `area:` sets to pick parallel work without reading issue bodies.
Do not add an `area:` label for incidental updates to cross-cutting index or routing files (`research/MAP.md`, `mise.toml`, `docs/ARCHITECTURE.md`, `docs/architecture-python.md`, `docs/development.md`, `Cargo.toml`), or for `research/parity/` repins and findings attached to a `type:fidelity` or `type:perf` code change (which already carry those concurrency constraints).

| Label | Meaning |
| --- | --- |
| `area:core` | `crates/stunt-core/`: format decoders, VFS, SOD VM, FLM, world and scenery |
| `area:render` | `crates/stunt-render/`, `stunt-gltf/`, `stunt-cli/`: shaders, GPU pipeline, playback, export |
| `area:parity` | `crates/stunt-score/`, `stunt-parity/`, `bench`, `tac`, parity scripts, and `research/parity/`-owned work |
| `area:re` | `research/formats/`, `research/*-exe/`, `.ksy` schemas, and RE scripts (`re_tool`, `debug_x`, `pair_builds`) |
| `area:agents` | `.agents/`, `.claude/agents/`, `docs/agents/`, `docs/harness*`: skills, agent policy, triage workflow |
| `area:tooling` | `gate.py`, CI workflows, `mise.toml`, worktrees, cloud setup, PR and doc scripts |
| `area:docs` | `docs/` (spec, architecture, ADRs, how-tos), `AGENTS.md`, and `GLOSSARY.md` |
| `area:site` | `site/`: research site, Starlight, and guides |
| `area:class-agreement` | A flag in the lavapipe-versus-GPU class agreement (#908), applied by [`parity_agreement.py`](../../python/scripts/parity_agreement.py) |

## Model roles

A model label says what capability an issue's implementation needs, never a model name; [`harness.md`](../harness.md#policy-any-agent) maps the labels to models per harness.

| Label | Meaning |
| --- | --- |
| `model-tier:light` | Nothing to weigh: the plan says exactly what to change |
| `model-tier:medium` | The spec is clear and the main work is doing it |
| `model-tier:heavy` | Working out what to do or why something is broken is the hard part |
| `model-context:wide` | The material will not fit a small context window |

A planned issue carries exactly one `model-tier:` label, and `model-context:wide` is optional beside any tier.
Exactly one is a convention no check enforces, so a writer swaps the tier (removes the old label, adds the new one) and never adds a second.
Later `model-context:` values (such as `visual`, for work that reads frames) join when a routable model lacks the capability.

Both prefixes are set only once a plan or an Agent Brief exists, so they stay unset when filing and on `status:needs-triage`, `status:needs-info` and `status:needs-plan` issues; a tier found on a `status:needs-plan` issue is ignored and the planner confirms or replaces it.
Whoever writes the plan sets them:

- The planner names and applies them with its `## Tentative plan`, on both routes.
- Whoever writes a triage Agent Brief and moves the issue to `status:ready-for-agent` sets them.
- Whoever moves a `status:plan-review` issue to `status:ready-for-agent` swaps them to match if the decision changed the work's shape.
- A coordinator moves the tier up one, or adds `model-context:wide`, when a worker's report or a reviewer's finding shows a lack of capability or context, in the same pass as its claim release.

The labels are advisory: they pick the default worker, and a model the maintainer names overrides them, and evidence of a failed attempt can move the tier up.

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from these tables.
