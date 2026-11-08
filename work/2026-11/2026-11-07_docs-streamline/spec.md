# Docs streamline: design

Status: design agreed in conversation 2026-11-07, section by section; this spec awaits review. The implementation plan will be `plan.md` beside it.

## 1. Why

Markdown in the repo totals about 2.2 MB. The 2026-10-23 reorganization split the 102 KB `parity-findings.md` and set a 20 KB note guideline, yet two weeks later ten research notes exceed it again (`capture-dosbox-automation.md` 64 KB, `parity/method.md` 57 KB, `framing-and-actors.md` 43 KB, `world-scene.md` 40 KB, `memory-map.md` 37 KB). The cause is how notes are written: investigations append dated "rounds" to the subject note, and nothing makes a writer replace superseded text. Moving files again would only reset the clock, so this design changes where dated material goes and adds a standing check and a routine that keep notes distilled.

Other costs found while surveying:

* `docs/process/plans/` is 790 KB (45 files), a third of all docs, mostly landed spec and implementation pairs; every grep from the root returns them.
* `research/parity/log.md` (72 KB, 126 rows) has become a general lab journal: its Notes cells hold paragraphs, notes in `playone-exe/` and `makeone-exe/` cite it for findings with no score, about 35 provenance lines link the whole file rather than a row, and its `merge=union` attribute does not apply to merges on GitHub, so parallel PRs conflict on it.
* No index says what `research/` knows; an agent guesses a file or greps 970 KB.

## 2. Intent

* **Readers.** Agents on this repo and outside readers (reverse engineers, preservationists) equally. `research/` is CC BY 4.0 and the repo is going public.
* **Success.** A cold agent finds the note for a subject in one read of an index; a note fits in one read; a writer knows where each kind of text goes without judgment calls; history and provenance survive; notes stay distilled without a person policing them.
* **Constraints.** `mise run check` passes with no warnings at every commit (AGENTS.md), so the size and shape checks are a report, not part of the gate. Git history of moved files must stay followable.

## 3. The one rule: evergreen or dated

**A current fact goes in `research/` or `docs/` and is rewritten in place. A dated record goes in `work/` and is frozen once its work lands.**

ADRs are dated but immutable decisions; they stay in `docs/adr/`. `research/**/*.ksy` and `research/parity/*.toml` are evergreen.

### 3.1 Work folders

```
work/
  README.md                       license, layout, lifecycle (this section, condensed)
  INDEX.md                        generated: month -> folder, status, one-line outcome
  2026-11/
    2026-11-07_docs-streamline/
      README.md                   frontmatter + question, outcome, links to what it changed
      spec.md, plan.md            superpowers output
      journal.md                  dated entries
      images/                     comparison images
```

* **Path.** `work/<YYYY-MM>/<YYYY-MM-DD>_<slug>/`, dated by the day the work started; the slug is lowercase kebab case. A folder never moves.
* **Granularity.** One folder per work item (an issue, investigation or feature), not per session. A session that continues an item writes into its folder.
* **README frontmatter.** Required: `title`, `status` (`active`, `landed` or `abandoned`), `started` (ISO date), `links` (issue and PR URLs, may be empty), `outcome` (one line; may be empty while `active`).
* **File names.** `spec.md` and `plan.md` for superpowers output (`spec-<topic>.md` when a folder needs a second); `journal.md` for entries; `images/` for pictures. Migrated files that are neither spec nor plan keep their basename.
* **Journal entries.** A `##` heading `YYYY-MM-DD: <title>`, then **Question**, **Method**, **Result** (scores stated in the text), **Verdict** (adopted, rejected or control) and **Lives in** (the evergreen note or ADR that now holds the fact). Dated and session-style headings are allowed in `work/` only.
* **Lifecycle.** Anything goes while `active`. On landing, durable facts are lifted into research notes, ADRs or `docs/`; the README records the outcome and `status: landed`; afterwards the folder changes only for link fixes.
* **Images.** `NOTICE.md`'s limits on comparison images apply unchanged; `research/images/README.md`'s naming rules move to `work/README.md`.
* **Search.** A root `.ignore` containing `/work/` keeps the folder out of default ripgrep and Grep tool searches. Tested 2026-11-07: a search from the root skips it; `path: work/` or `rg <term> work/` searches it; `rg --no-ignore-dot` searches everything; `git grep` and the Glob tool ignore `.ignore`.
* **License.** `work/README.md` licenses the folder CC BY 4.0, as `research/README.md` does for `research/`.

### 3.2 What moves into `work/`

* Every file under `docs/process/plans/`, including `architecture-deepening/` (one folder), `docs/process/research/`, and `docs/process/TEAM_SHEET.md` (frozen history). `docs/process/` is then removed.
* The image sets `research/images/<date>-<commit>/` and `research/parity/aircraft/`, each into the folder of the investigation that produced it (for example `parity/aircraft/` into `2026-11-01_aircraft-render/`), or a new folder dated by the set when none exists.
* `research/parity/log.md`, converted (section 4.4).
* **Stays:** `research/parity/error-examples/` (current reference data indexed by `error-categories.toml`), every ADR, `docs/` guides, `research/` notes, schemas and TOML files.

## 4. Evergreen research notes

### 4.1 What belongs in `research/`

Facts about how the original works, or about where our render differs from it: Diataxis *reference* and *explanation*. Procedures for running our tools are *how-to* and go to `docs/` or a skill (for example the loop in `parity/method.md` section 1, and the Lua driver and capture recipes in `capture-dosbox-automation.md`). Facts about the quality of the evidence (DAC lag, torn pages, recapture noise) stay, since they decide which captures count.

### 4.2 Shape

* **Frontmatter.** A YAML block with one required key, `summary:`, one sentence of at most 200 characters saying what the note establishes.
* **Body.** Current truth organized by subject. A section's evidentiary tier goes in its first line, never its heading (unchanged). Each finding ends with a provenance line in italics, `Source:` followed by a link to the journal entry's heading under `work/`, replacing `_Found <date>; see the parity log._`.
* **Ending.** **Ruled out** (one line each: what was tried, the verdict, a journal link), then **Open questions** in priority order (unchanged).
* **Size.** About 20 KB. Generated tables (`formats/sod-opcode-coverage.md`) are exempt.

### 4.3 Links from evergreen files into `work/`

`tests/test_doc_invariants.py::test_sources_of_truth_do_not_link_into_process_docs` today forbids `research/`, `SPEC.md` and `ARCHITECTURE.md` from linking into `docs/process/`. It becomes: an evergreen file links into `work/` only from a provenance line (`_Source: ..._`) or a **Ruled out** item; any other link into `work/` fails, so a fact is never stated only in a dated record. ADRs keep their spec and plan citations (they move with the plans). Existing `PROCESS_POINTERS` entries are rewritten or removed.

### 4.4 Retiring the parity log

How agents used `log.md`, and where each use goes:

| Use | New home |
|---|---|
| "Was this already tried?" before a parity attempt | The residual's **Ruled out** section, then `rg <term> work/` |
| Grep for a term | Journal entries |
| Provenance | Provenance lines link a journal entry's heading |
| The current baseline | Expected scores in `references.toml`, checked by `mise run parity` |
| Appending a row per attempt | A journal entry in the attempt's own work folder; no shared file |

* **Expected scores.** Each film table in `research/parity/references.toml` gains `[<film>.expected]` keyed by renderer class, `gpu` or `lavapipe`, each `{ ssim, iou, commit }` (headline `mean_ssim_scored` and its IoU). `mise run parity` prints each film's score beside the expected one for the class it rendered on and flags a difference larger than the noise rule `stuntreel parity --noise-sigma` already applies. The render records its class (hardware or CPU adapter, as `renderer.rs` already distinguishes) in its report; layer 1 adds the field if the report lacks it.
* **Adopting a change** updates the expected line in the same PR, so the diff shows before and after; two PRs that both adopt conflict on that line, correctly, because the second must re-measure. `git log -p research/parity/references.toml` is the history of adopted scores.
* **Conversion.** The 126 rows become one entry each in `work/2026-10/2026-10-21_parity-log-legacy/journal.md`, heading `YYYY-MM-DD: <commit or label>`, Notes kept verbatim. A script repoints each "see the parity log" line and code comment at the entry matching its date and commit, and at the journal's top where no single row matches. `log.md` and its `.gitattributes` line are deleted.
* There is no generated history table.

### 4.5 Routing rule changes in `research/README.md`

* Rule 3 ("every experiment leaves one row in `parity/log.md`") becomes: every experiment leaves a journal entry in its work folder, and the finding's provenance line links it.
* Rule 4 ("tooling lives with what it studies") is replaced by the reference-versus-how-to test of section 4.1.
* Rule 5 ("a handoff is not a file") becomes: a handoff lives in the work folder's README.
* The Size section points at `mise run doc-health`.

## 5. Finding things, checks and agent instructions

### 5.1 Generated indexes

`mise run fix` regenerates both; `mise run check` fails when either is stale, as it does for unformatted code.

* **Knowledge map.** A block in `research/README.md` between `<!-- knowledge-map:start -->` and `<!-- knowledge-map:end -->`, listing every research note by folder: its path as a link, then its summary.
* **`work/INDEX.md`.** One table per month, newest month first, a row per folder: date, title (linked), status, outcome. Built from README frontmatter; a README with missing or invalid frontmatter fails the generator.

### 5.2 `mise run doc-health`

A report, not part of `check`, ranked worst first, with `--json` for the routine. It warns on:

* an evergreen markdown file over 20 KB: `research/**/*.md`, `docs/*.md`, `docs/agents/*.md`, `AGENTS.md`; not ADRs, not generated tables;
* a research note without `summary:`;
* a heading in an evergreen file that contains an ISO date or an ordinal round ("Second round"), or starts with Update, Follow-up, Handoff or Session (the patterns live in the script, so a heading such as "Dependency updates" does not match);
* a work folder with `status: active` and no commit touching it in 14 days.

### 5.3 The `distilling-notes` skill and the gardening routine

A new skill, `.agents/skills/distilling-notes/SKILL.md`, holds the procedure both the migration's distillations and the routine follow: move narrative verbatim into the journal of the work folder that produced it, or into `work/<month>/<date>_distill-<note>/journal.md` when none did; rewrite the note as current truth with provenance lines; move how-to text to `docs/` or a skill; keep every claim no broader than its evidence. Moving text verbatim keeps it findable with `git log -S`.

A weekly scheduled cloud agent runs `mise run doc-health -- --json`, distills the top offender (one file per run), has a fresh reviewer subagent check the diff for broadened claims (AGENTS.md working rule 7), and opens a PR whose body also lists stale `active` work folders.

### 5.4 Agent instructions

* **AGENTS.md.** Directive 4 states the one rule. The section 2 table gains "Knowledge map" (`research/README.md`) and "Work items" (`work/INDEX.md`) rows and loses the `docs/process/` paragraph. Working rule 4 becomes "write the handoff into the work folder's README". Rule 6's log row becomes a journal entry. New lines: superpowers brainstorming and writing-plans write `spec.md` and `plan.md` into the active work folder, overriding the skill default; search `work/` with `path: work/` or `--no-ignore-dot`. `test_agents_md_fits_its_budget` still passes.
* **`mise run work-new -- <slug>`** creates today's folder with a README whose frontmatter is filled in (`status: active`, `started` today).
* **`recording-findings` skill.** A journal entry and provenance line replace the log row; adds the `summary:` and knowledge-map steps.
* **`improving-render-parity` skill.** "Read `log.md`" becomes "read the residual's **Ruled out**, then `rg <term> work/`"; "add a row" becomes "write a journal entry; adopting updates the expected scores in `references.toml`".
* **`docs/harness.md`.** Its `log.md` line-ending and append-only paragraph goes.

## 6. Migration

A `gh stack` of four layers; each passes `mise run check` on its own. No distillation happens inside the stack.

1. **Tooling.** `.ignore`, `work/README.md`, `mise run work-new`, the frontmatter reader, both index generators wired into `fix` and `check`, `mise run doc-health`, the link-rule change of section 4.3 (with `work/` walked by the link check), the renderer-class field, and expected scores in `references.toml` with `mise run parity` comparing against them. Seeding the scores needs a GPU run on the primary machine and a lavapipe run in a cloud session, both on `main`.
2. **Moves.** A script runs `git mv` and rewrites every link: ADR citations, `tests/test_skill_eval.py`, `.coderabbit.yaml`, `manifests/cloud-assets.toml`, `docs/harness.md`, `docs/ARCHITECTURE.md`. Start dates come from the filename date, else the file's first commit. A spec and its implementation plan with the same date and topic share a folder. Each migrated folder gets a README whose `status` and `outcome` come from the plan's Status line (`landed` for implemented, landed, closed or done; `active` otherwise). Moves and link rewrites only, so every file stays a rename above git's 50% similarity threshold; the PR body carries the old-to-new path map.
3. **Parity log.** The conversion of section 4.4.
4. **Rules.** AGENTS.md, `research/README.md`, the two skills, the new `distilling-notes` skill, and `summary:` on all research notes (drafted by subagents, reviewed before commit). The knowledge map is generated for the first time.

**After the stack:**

* A one-line PR adds the squashed layer-2 commit to `.git-blame-ignore-revs`, and `mise run init` sets `blame.ignoreRevsFile`.
* Independent distillation PRs off `main`, one per file, worst first, each following `distilling-notes`: `capture-dosbox-automation.md`, `parity/method.md` (its loop to the parity skill or `docs/`), `framing-and-actors.md`, and `docs/development.md` (split into setup, workflows and conventions). `memory-map.md` is split by segment, not distilled, since it is an offset registry.
* The weekly gardening routine is scheduled last and takes the remaining files over budget.

## 7. Out of scope

* Slimming the prose cells of `docs/ARCHITECTURE.md`'s routing table, beyond what doc-health later flags.
* ADR content, `.ksy` schemas, `GLOSSARY.md`.
* Raw session transcripts in work folders.

## 8. Done when

* A Grep tool search from the root returns nothing under `work/`, and `docs/process/` and `research/parity/log.md` no longer exist.
* `mise run check` passes with the link check walking `work/` and the section 4.3 rule in force.
* Every research note has `summary:`, and `research/README.md` carries the generated knowledge map.
* `mise run parity` prints each film's expected score and flags drift.
* `git log --follow` on a migrated spec reaches its commits from before the move.
* After the four post-stack distillations, `mise run doc-health` lists no evergreen file over 40 KB, and the gardening routine is scheduled.
