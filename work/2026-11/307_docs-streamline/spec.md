# Docs streamline: design

Status: design agreed in conversation 2026-11-07, section by section, then revised after four rounds of review questions the same day; awaiting review. Work item [#307](https://github.com/neilsh/stunt-reel/issues/307). The implementation plan will be `plan.md` beside this file.

## 1. Why

Markdown in the repo totals about 2.2 MB. The 2026-10-23 reorganization split the 102 KB `parity-findings.md` and set a 20 KB note guideline, yet two weeks later fifteen research notes exceed it again, led by (`capture-dosbox-automation.md` 64 KB, `parity/method.md` 57 KB, `framing-and-actors.md` 43 KB, `world-scene.md` 40 KB, `memory-map.md` 37 KB). The cause is how notes are written: investigations append dated "rounds" to the subject note, and nothing makes a writer replace superseded text. Moving files again would only reset the clock, so this design changes where dated material goes and adds a standing report and a routine that keep notes distilled.

Other costs found while surveying:

* `docs/process/plans/` is 790 KB (45 files), a third of all docs, mostly landed spec and implementation pairs; every grep from the root returns them.
* `research/parity/log.md` (72 KB, 126 rows) has become a general lab journal: its Notes cells hold paragraphs, notes in `playone-exe/` and `makeone-exe/` cite it for findings with no score, about 35 provenance lines link the whole file rather than a row, and its `merge=union` attribute does not apply to merges on GitHub, so parallel PRs conflict on it.
* No index says what `research/` knows; an agent guesses a file or greps 970 KB.

## 2. Intent

* **Readers.** Agents on this repo and outside readers (reverse engineers, preservationists) equally. `research/` is CC BY 4.0 and the repo is public; `docs/process/` was cleared to ship as it is, so its contents may move into `work/` and stay public.
* **Success.** A cold agent finds the note for a subject in one read of an index; a note fits in one read; a writer knows where each kind of text goes without judgment calls; git and GitHub history survive the moves; notes stay distilled without a person policing them.
* **Constraints.** `mise run check` passes with no warnings at every commit (AGENTS.md), so size and shape findings are a report, not part of the gate. `main` requires the `Quality gate (ubuntu)` check and linear history, and allows squash and rebase merges only.

## 3. The one rule: evergreen or dated

**A current fact goes in `research/` or `docs/` and is rewritten in place. A dated record goes in `work/` and is frozen once its work lands.**

ADRs are dated but immutable decisions; they stay in `docs/adr/`. `research/**/*.ksy` and `research/parity/*.toml` are evergreen.

### 3.1 Work items and work folders

A **work item** is a GitHub issue. Its status is the issue's: open is active, closed as completed is landed, closed as not planned is abandoned. A work item gets a **work folder** only when it has a file to keep (a spec, plan, journal or image); otherwise the issue alone is the record.

```
work/
  README.md                       license, layout, lifecycle (this section, condensed)
  2026-11/
    307_docs-streamline/
      README.md                   frontmatter + question, outcome, links to what it changed
      spec.md, plan.md            superpowers output
      journal.md                  dated entries
      images/                     comparison images
    distill-method/               a folder with no issue (section 3.2)
```

* **Path.** `work/<YYYY-MM>/<issue>_<slug>/`: the month the work started, the issue number as GitHub shows it, unpadded, and a lowercase kebab-case slug. A folder never moves. There is no committed index: the month directories are the index, and `mise run work -- list [--status active]` prints a table with each issue's status.
* **README frontmatter.** `title`, `started` (ISO date), `issue` (number), `outcome` (one line; empty until the work lands). There is no hand-written status field.
* **Folders without an issue.** Landed migrated plans and the gardening routine's distillations have no issue. They are named `work/<YYYY-MM>/<slug>/` (letters sort after the numbered folders) and carry a fixed `status: landed` instead of `issue`. The frontmatter check accepts exactly one of `issue` and `status`, and `status` only with the value `landed`.
* **File names.** `spec.md` and `plan.md` for superpowers output (`spec-<topic>.md` when a folder needs a second); `journal.md` for entries; `images/` for pictures. Migrated files that are neither spec nor plan keep their basename.
* **Journal entries.** A `##` heading `YYYY-MM-DD: <title>`, then **Question**, **Method**, **Result** (scores stated in the text), **Verdict** (adopted, rejected or control) and **Lives in** (the evergreen note or ADR that now holds the fact). Dated and session-style headings are allowed in `work/` only.
* **Lifecycle.** Anything goes while the issue is open. The PR that finishes the work lifts durable facts into research notes, ADRs or `docs/`, writes the README `outcome`, and closes the issue (by `Fixes #N`, or by hand for a stacked PR as `docs/agents/issue-tracker.md` says). Afterwards the folder changes only for link fixes. A frozen entry later found wrong is not edited: the correction is a new entry in a new work item, and the evergreen note's **Ruled out** records it.
* **Images.** `NOTICE.md`'s limits on comparison images apply unchanged; `research/images/README.md`'s naming rules move to `work/README.md`.
* **Search.** A root `.ignore` containing `/work/` keeps the folder out of default ripgrep and Grep tool searches. Tested 2026-11-07: a search from the root skips it; `path: work/` or `rg <term> work/` searches it; `rg --no-ignore-dot` searches everything; `git grep` and the Glob tool ignore `.ignore`.
* **License.** `work/README.md` licenses the folder CC BY 4.0, as `research/README.md` does for `research/`.

### 3.2 What moves into `work/`

* Every file under `docs/process/plans/`, including `architecture-deepening/` (one folder), `docs/process/research/`, and `docs/process/TEAM_SHEET.md` (frozen history), each dated by its filename date, else its first commit. A spec and its implementation plan with the same date and topic share a folder. A landed plan becomes an issue-less folder. A plan still in flight (today `vault-parity-films`, `retro-2026-11-07`, `capture-store-deepening`, `debugger-breakpoints`, `scoring-failures`) becomes an issue folder: the issue it names (`vault-parity-films` names #242), else one filed during the migration. Many implementation plans have no Status line, so the migration script prints every plan's inferred state (from its Status line, else "unknown") as a table in the PR body for a person to confirm before merge. `docs/process/` is then removed.
* The image sets `research/images/<date>-<commit>/` and `research/parity/aircraft/`, each into the folder of the investigation that produced it (for example `parity/aircraft/` into the aircraft-render folder), or a new issue-less folder when none exists.
* `research/parity/log.md`, moved verbatim (section 4.4).
* **Stays:** `research/parity/error-examples/` (current reference data indexed by `error-categories.toml`), every ADR, `docs/` guides, `research/` notes, schemas and TOML files.

## 4. Evergreen notes

### 4.1 What belongs in `research/`, and where how-to goes

`research/` holds facts about how the original works, or about where our render differs from it: Diataxis *reference* and *explanation*. Facts about the quality of the evidence (DAC lag, torn pages, recapture noise) stay, since they decide which captures count.

Procedures for running our tools are *how-to* and go to `docs/howto/<task>.md`, one task per file under the same size budget (for example the loop in `parity/method.md` section 1, the Lua driver and capture recipes in `capture-dosbox-automation.md`, and the Workflows section of `docs/development.md`). A skill keeps when it fires, its checklist and what done means, and links the how-to for commands, flags and troubleshooting rather than repeating them. The routing table in `docs/ARCHITECTURE.md` may link how-tos.

### 4.2 Shape of a research note

* **Frontmatter.** A YAML block with one required key, `summary:`, one sentence of at most 200 characters saying what the note establishes.
* **Body.** Current truth organized by subject. A section's evidentiary tier goes in its first line, never its heading (unchanged). Each finding ends with a provenance line in italics, `Source:` followed by a link to the journal entry's heading under `work/`, replacing the `Found <date>; see the parity log` lines.
* **Ending.** **Ruled out** (one line each: what was tried, the verdict, a journal link), then **Open questions** in priority order (unchanged).
* **Size.** About 20 KB. Generated tables (`formats/sod-opcode-coverage.md`) are exempt.

### 4.3 Link rules

`tests/test_doc_invariants.py` keeps doing the checking; no new link checker is adopted for internal links. Code cites documents 202 times by path (75 files) and 287 times by anchor token, which lychee cannot see. lat.md was compared and not adopted: it requires a `lat.md/` vault, its wiki links render as raw text on GitHub, and its heading-path section ids break on every heading rename, which distillation does often.

* **Into `work/`.** `work/` is not a source of truth, so an evergreen file links into it only from a provenance line or a **Ruled out** item, with the anchor checked (frozen headings never change). Any other link from an evergreen file into `work/` fails, so a fact is never stated only in a dated record. Two exceptions: ADRs cite the spec and plan they came from freely, and `PROCESS_POINTERS` carries over as `WORK_POINTERS`, the existing pointer links (the architecture-deepening README, `TEAM_SHEET.md`, three plans) rewritten to their new paths, a list that may only shrink. This replaces `test_sources_of_truth_do_not_link_into_process_docs`.
* **Out of `work/`.** Links from `work/` into evergreen files are checked for the file only, not the heading, so distilling a note does not break dozens of frozen records. Links within `work/` are checked in full.
* **From code.** Code cites a document by a registered anchor token (`[MEM-*]`, `[FMT-*]`, `[I*]`) or by its path, never by a heading fragment, so distillation never breaks a citation in code. Paths into `work/` are allowed (17 code citations point at plans today). No code citation uses a fragment today; the rule goes in AGENTS.md's docstring guidance and the existing path check.
* **Default locations.** `check` fails if `docs/superpowers/` exists, and, once the moves land, if `docs/process/` does, so a spec written to a skill's default location is caught.

### 4.4 Retiring the parity log

How agents used `log.md`, and where each use goes:

| Use | New home |
|---|---|
| "Was this already tried?" before a parity attempt | The residual's **Ruled out** section, then `rg <term> work/` |
| Grep for a term | Journal entries |
| Provenance | Provenance lines link a journal entry's heading |
| The current baseline | Expected scores in `references.toml`, checked by `mise run parity` |
| Appending a row per attempt | A journal entry in the attempt's own work folder; no shared file |

* **Expected scores.** Each film table in `research/parity/references.toml` gains `[<film>.expected]` keyed by renderer class, `gpu` or `lavapipe`, each `{ ssim, iou, commit, adapter }` (headline `mean_ssim_scored`, its IoU, and the adapter name it was measured on). The classes stay separate because lavapipe still differs from a GPU by 0.0003 to 0.0008 after its NaN guard (`research/parity/lavapipe.md`), beyond the 0.0003 noise floor. The parity report gains the adapter's name and class (hardware or CPU, as `renderer.rs` already distinguishes), versioned as ADR 0011 requires for the parity artifacts.
* **The check.** `mise run parity` prints each film's score beside the expected one for its class. It flags drift, a difference beyond the noise rule `stuntreel parity --noise-sigma` applies, only when the adapter name matches and nothing under `crates/` and no reference pin in `references.toml` changed since the expected `commit`; otherwise it prints the delta and says why it is not comparable (older commit, other adapter).
* **Adopting a change** updates the expected line for the class the PR measured; the other class keeps its older commit until someone measures it. The diff shows before and after; two PRs that both adopt conflict on that line, correctly, because the second must re-measure. `git log -p research/parity/references.toml` is the history of adopted scores.
* **The legacy log.** `log.md` moves verbatim with `git mv` to `work/2026-10/parity-log/log.md` (an issue-less folder, `status: landed`), a 100% rename that keeps every row's history. Its provenance lines and code comments are repointed at the moved file; the rows are not converted. The `.gitattributes` `merge=union` line and `docs/harness.md`'s paragraph on the file go.

### 4.5 Routing rule changes in `research/README.md`

* Rule 3 ("every experiment leaves one row in `parity/log.md`") becomes: every experiment leaves a journal entry in its work folder, and the finding's provenance line links it.
* Rule 4 ("tooling lives with what it studies") is replaced by the reference-versus-how-to test of section 4.1.
* Rule 5 ("a handoff is not a file") becomes: a handoff lives in the work folder's README, or on the issue when there is no folder.
* The Size section points at `mise run doc-health`, and the README links the knowledge map.

## 5. Finding things, checks and agent instructions

### 5.1 The knowledge map

`research/MAP.md` lists every research note by folder: its path as a link, then its summary. It is generated by `mise run fix` from the notes' `summary:` keys (a note without one is listed as "no summary yet", and doc-health warns), and `mise run check` fails when it is stale, as it does for unformatted code. It is committed so outside readers have it; it changes only when a summary or note changes. It is a file of its own because the roughly 55 entries would push `research/README.md` from 11 KB past its own budget.

### 5.2 `mise run work`

* `mise run work -- new <slug> --issue <n>` creates `work/<this month>/<n>_<slug>/` with its README frontmatter filled in. Without `--issue` it files the issue with `gh issue create`, the slug as title, after checking the target repository as `docs/agents/issue-tracker.md` requires.
* `mise run work -- list [--status active|landed|abandoned]` prints month, folder, title, status and outcome, reading status through `gh`.
* When `gh` is unavailable, both say so and leave status out rather than fail.

### 5.3 `mise run doc-health`

A report, not part of `check`, ranked worst first, with `--json` for the routine. It warns on:

* an evergreen markdown file over 20 KB: `research/**/*.md`, `docs/*.md`, `docs/agents/*.md`, `docs/howto/*.md`, `AGENTS.md`; not ADRs, not generated tables;
* a research note without `summary:`;
* a heading in an evergreen file that contains an ISO date or an ordinal round ("Second round"), or starts with Update, Follow-up, Handoff or Session (the patterns live in the script, so a heading such as "Dependency updates" does not match);
* a work folder whose issue is open with no commit touching the folder in 14 days, or closed with an empty `outcome` (skipped, with a note, when `gh` is unavailable).

### 5.4 The `distilling-notes` skill and the gardening routine

A new skill, `.agents/skills/distilling-notes/SKILL.md`, holds the procedure both the post-migration distillations and the routine follow: move narrative verbatim into an issue-less `work/<month>/distill-<note>/journal.md` (suffixed `-2` for a second distillation of the same note in a month), each entry linking the work folder that produced it when there is one, since frozen folders are not appended to; rewrite the note as current truth with provenance lines; move how-to text to `docs/howto/`; keep every claim no broader than its evidence. Moving text verbatim keeps it findable with `git log -S`.

A weekly scheduled cloud agent runs `mise run doc-health -- --json`, distills the top offender (one file per run), has a fresh reviewer subagent check the diff for broadened claims (AGENTS.md working rule 7), runs `lychee` over the repository's external URLs, and opens a draft PR whose body lists dead external links and stale work folders. A routine PR never auto-merges; a person reviews and merges it.

### 5.5 Agent instructions

* **AGENTS.md.** Directive 4 states the one rule. The section 2 table gains "Knowledge map" (`research/MAP.md`), "Work items" (GitHub issues and `work/`) and "How-to guides" (`docs/howto/`) rows, and its `docs/process/` paragraph becomes "`work/` is not a source of truth: never cite it for a fact about the system". Working rule 4 becomes "write the handoff into the work folder's README, or on the issue". Rule 6's log row becomes a journal entry. New lines: before superpowers brainstorming or writing-plans writes a file, run `mise run work -- new`, and write `spec.md` and `plan.md` into that folder, overriding the skill default; the finishing PR writes the README `outcome`; search `work/` with `path: work/` or `--no-ignore-dot`. `test_agents_md_fits_its_budget` still passes.
* **`recording-findings` skill.** A journal entry and provenance line replace the log row; adds the `summary:` and knowledge-map steps.
* **`improving-render-parity` skill.** "Read `log.md`" becomes "read the residual's **Ruled out**, then `rg <term> work/`"; "add a row" becomes "write a journal entry; adopting updates the expected scores in `references.toml`"; procedures it repeats move to `docs/howto/` and are linked.

## 6. Migration

Expected scores ship first as their own PR off `main`, in parallel with the stack: the `references.toml` schema, the renderer-class field, the `mise run parity` comparison, and seeding by a GPU run on the primary machine and a lavapipe run in a cloud session, both on `main`.

The rest is a `gh stack` of four PRs (the plan folds the parity log into the moves and relink PRs, so its own link rewrite never shares a squashed commit with its move); each passes `mise run check` at its own head, and the stack squash-merges as one commit per PR. Before pushing a PR that changes `research/` or `NOTICE.md` (moves, rules), a fresh reviewer reads its diff (AGENTS.md working rule 7).

1. **Tooling.** `.ignore`, `work/README.md`, `mise run work`, the frontmatter reader, the knowledge-map generator wired into `fix` and `check`, `mise run doc-health`, the link rules of section 4.3, the `docs/superpowers/` guard, and `mise run move-docs`, the reusable tool the next two layers run.
2. **Moves.** A script runs `git mv` for everything in section 3.2, the parity log included, and rewrites links in files that did not move: ADR citations, code comments, `tests/test_skill_eval.py`, `.coderabbit.yaml`, `manifests/cloud-assets.toml`, `docs/harness.md`, `docs/ARCHITECTURE.md`, `docs/SPEC.md`, skills, and `NOTICE.md`'s note of where comparison images go. It adds the `docs/process/` guard and `WORK_POINTERS`. The link check skips sources under `work/` for this PR only. Every moved file is a 100% rename; each migrated folder's README is a new file. The PR body carries the old-to-new path map and the table of inferred plan states (section 3.2).
3. **Links inside moved files.** Rewrites the relative links inside the moved files and removes the skip.
4. **Rules**, merged after the expected-scores PR, since it tells agents to update expected scores instead of appending log rows. AGENTS.md, `research/README.md`, the two skills, the new `distilling-notes` skill, `GLOSSARY.md` terms (work item, work folder, journal entry, evergreen note), an ADR (the next free number, 0041 today) recording the one rule and the work-item layout, the parity wording that named the log, and `summary:` on all research notes (drafted by subagents, reviewed before commit), which fills in the knowledge map that layer 1 generates with every summary missing.

**After the stack:**

* A one-line PR adds the squashed moves and links commits to `.git-blame-ignore-revs`, and `mise run init` sets `blame.ignoreRevsFile`.
* Independent distillation PRs off `main`, one per file, worst first, each following `distilling-notes`: `capture-dosbox-automation.md`, `parity/method.md` (its loop to `docs/howto/`), `framing-and-actors.md`, and `docs/development.md` (setup and conventions stay; Workflows go to `docs/howto/`). `memory-map.md` is split by segment, not distilled, since it is an offset registry.
* The weekly gardening routine is scheduled last and takes the remaining files over budget.

## 7. Out of scope

* Slimming the prose cells of `docs/ARCHITECTURE.md`'s routing table, beyond what doc-health later flags.
* The content of existing ADRs, `.ksy` schemas, and glossary terms other than the four section 6 adds.
* Links from docs to code symbols, and other lat.md features.
* Raw session transcripts in work folders.

## 8. Done when

* A Grep tool search from the root returns nothing under `work/`, and `docs/process/` and `research/parity/log.md` no longer exist.
* `mise run check` passes with the link rules of section 4.3 in force and the guard on default locations.
* Every research note has `summary:`, and `research/MAP.md` lists them all.
* An ADR records the one rule, and every plan that was in flight at the migration has an open issue and an issue folder.
* `mise run parity` prints each film's expected score for its renderer class and flags drift.
* `git log --follow` on a migrated spec and on the legacy parity log reaches their commits from before the move.
* After the four post-stack distillations, `mise run doc-health` lists no evergreen file over 40 KB, and the gardening routine is scheduled.
