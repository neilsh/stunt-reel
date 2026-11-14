# Split `memory-map.md` by Segment: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Follow every step literally. Do not edit any note by hand, and do not change `split_473.py`. When a step's output differs from what it expects, stop and report the step number and the full output.**

**Goal:** Split [`research/playone-exe/memory-map.md`](../../../research/playone-exe/memory-map.md) (52,053 bytes; budget 20,480) into five files under budget, with every `[MEM-*]` anchor registered in its new home and every inbound link rewritten.

**Architecture:** One checked script, [`split_473.py`](split_473.py) in this folder, does the whole edit: it refuses to run unless `memory-map.md` is the blob this plan was cut from, cuts the file by line range into five files, rewrites the cross-references between them, and applies a fixed list of (file, old text, new text, expected count) edits to the inbound links and to `doc_anchors.py`, writing nothing if any count differs. `mise run fix` then regenerates `research/MAP.md`. The script was dry-run on a `git archive` copy of `54bdacf1`: `pytest -m docs` passed (99 passed, 6 skipped) with the regenerated map.

**Tech Stack:** Markdown notes, Python 3 (`uv`), `mise` tasks.

**Spec:** [issue #473](https://github.com/neilsh/stunt-reel/issues/473) and [`307_docs-streamline/plan.md` Task 16](../307_docs-streamline/plan.md#task-16-distill-the-four-worst-files-independent-prs-off-main-one-session-each).

## Decisions (made here; the executor makes none)

- **Five files, split by segment, all in `research/playone-exe/`.** Section numbers are kept as they were, so every heading slug is unchanged and an inbound link changes only its file name:

  | File | Original lines | Holds | Anchors (home headings) | Size after |
  |---|---|---|---|---|
  | `memory-map.md` | 1–57, intro rewritten | Index of the five files, shared conventions, § 1 `DGROUP` table | none | 11,706 B |
  | `memory-map-patch3.md` (new) | 59–148 | § 1.1 Patch #3 build (heading raised to `##`): counterparts of the other files' rows, with the unmapped ones marked | none | 13,559 B |
  | `memory-map-runtime.md` (new) | 152–200 | § 2 Runtime Dynamic Capture Anchors | `[MEM-VSYNC-03DA]`, `[MEM-FLM-TICK]`, `[MEM-CAMERA-RIG]`, `[MEM-ACTOR-TABLE]` | 7,741 B |
  | `memory-map-vm.md` (new) | 204–259 | § 3 SOD VM work segment, its code anchors, § 3.1 | `[MEM-SOD-VM]`, `[MEM-SOD-ANCHOR-TABLE]` | 11,380 B |
  | `memory-map-main.md` (new) | 261–309 | `DS` data and code of the main program and the resident PCM mixer (`0x1DEA:0x05B1`) (headings raised to `##`) | `[MEM-FLM-VARS]`, `[MEM-PALETTE]` | 11,147 B |

  The `summary:` frontmatter line of each file is fixed in the script (each at most 200 characters).
- **`memory-map.md` keeps its path** and becomes the index, because AGENTS.md, SPEC.md, the skills and about 20 notes link it without a fragment, and frozen `work/` records link it too (the link test checks only that their target file exists).
- **Names are not 8.3.** `[I8]` ([`SPEC.md` § 2](../../../docs/SPEC.md#i8-dos-83-uppercase-path-normalization)) governs game-file paths in the VFS and corpus tools, not repository docs; `research/playone-exe/` already holds `capture-dosbox-automation.md`. The `memory-map-` prefix keeps the five files together in a listing.
- **`move-docs` is not used.** It runs `git mv` on whole files and rewrites links to a moved path. Here `memory-map.md` stays and its sections leave, so each link's new file depends on its fragment, which a moves file cannot express. `split_473.py` does that rewrite, with an expected count on every edit, and stays in this folder as the record, as [`plan_moves.py`](../307_docs-streamline/plan_moves.py) did for #307.
- **`doc_anchors.py`:** `MEMORY_MAP` is replaced by `MEMORY_MAP_RUNTIME`, `MEMORY_MAP_VM` and `MEMORY_MAP_MAIN`; no other module imports it. Heading texts are unchanged.
- **Inbound links rewritten** (20 files, plus `doc_anchors.py`): `docs/ARCHITECTURE.md` (17 links by fragment), `docs/SPEC.md` § 3 row, `AGENTS.md` sources row, `research/README.md`, `distilling-notes` `SKILL.md` and `routine.md` (`memory-map*.md`), `anchorpt.md`, `timeline-and-ticks.md`, `actor_record.ksy`, `pair_builds.py` docstring, and in `research/playone-exe/`: `angle-bank.md`, `capture.md`, `capture-dosbox-automation.md`, `lod.md`, `memory.md`, `patch3.md`, `sod-vm.md`, `static-tooling.md`, `terrain-shade.md`, `world-scene.md`. A link without a fragment was pointed at the file holding the row its sentence cites; one whose sentence cites § 1 or the file as a whole stays on `memory-map.md`. In particular: `sod-vm.md`'s rotation-builder citation (`0824:04E5`, roll, pitch, yaw) goes to `memory-map-main.md`; `memory.md`'s "The structures themselves are specified in" (the tick, camera and actor structures) goes to `memory-map-runtime.md`; `patch3.md`'s "It maps every row of" now reads `every row of the [memory-map files](memory-map.md)`.
- **Not changed:** `.agents/skills/recording-findings/SKILL.md` keeps its link to `memory-map.md` (now the index), because one more word puts it at its 500-word budget (`test_skills_fit_their_budget`). Files under `work/` are dated records and are not edited. No `Ruled out` / `Open questions` headings are added: the original registry had none, and nothing checks for them.

## Global Constraints

- Stage files by name; never `git add -A` or `git commit -a`; never stage anything under `corpus/` ([AGENTS.md § Committing](../../../AGENTS.md#committing)).
- Only `mise run` tasks exist; the one-off script runs as `mise exec -- uv run python …`.
- Run commands from the repository root, in the Bash tool (Git Bash), not PowerShell.
- Every evergreen file stays at or under 20,480 bytes.

## Review Focus

1. **A row or sentence lost in the cut.** Every non-blank line of the old file must appear unchanged in one of the five files, except the 20 lines the script rewrites (intro, three `(see § 2)` rows, the § 1.1 cross-references, two `###` headings, two `[§ 1.1](#11-patch-3-build)` links). The four `---` rules of the old file (lines 58, 150, 202, 260) are dropped on purpose; `---` survives elsewhere, so the count does not show them. Task 1 Step 5 checks this.
2. **A link to a fragment that moved.** After the split no evergreen file may link `memory-map.md#` with any fragment but `#1-dgroup-memory-reference-table`. Task 1 Step 6 checks this.
3. **A relinked sentence that now points at the wrong file** (for example a `0x8108` citation sent to `memory-map-main.md`). The reviewer in Task 2 checks each rewritten link against the row its sentence cites.
4. **The new intro claiming more than the files hold** ("split by segment": the main-program file is the code segment plus its `DS` rows and the resident mixer's setter; the Patch #3 file has `unmapped` rows). The reviewer checks the index table and each `summary:` against the file it describes.
5. **The script run on a changed `memory-map.md`.** If `main` changed the file since `54bdacf1`, the script exits with `is blob …, not f60aa45…` and writes nothing; the plan then needs re-cutting, not a hand fix.

---

### Task 1: Split, relink, verify, commit

**Files:**
- Create: `research/playone-exe/memory-map-patch3.md`, `memory-map-runtime.md`, `memory-map-vm.md`, `memory-map-main.md`
- Modify: `research/playone-exe/memory-map.md`, `research/MAP.md` (generated), `python/stunt_reel/doc_anchors.py`, and the 20 other inbound-link files listed under Decisions
- Record: `work/2026-11/473_memory-map-split/split_473.py`
- Never stage: `work/2026-11/473_memory-map-split/plan.md` and `README.md` (the coordinator commits them before this task, with a `Fresh-review:` trailer)

- [ ] **Step 1: Check the starting point**

Run: `git status --short && git rev-parse --abbrev-ref HEAD && git hash-object research/playone-exe/memory-map.md`
Expected: no modified or staged tracked file. `plan.md` and `README.md` of this folder are already committed. `split_473.py` is either committed too or listed as `?? work/2026-11/473_memory-map-split/split_473.py`; other untracked `work/` folders of other issues may be listed and are left alone. The branch is not `main` and contains `54bdacf1` (`git merge-base --is-ancestor 54bdacf1 HEAD` exits 0). The hash is `f60aa453e72dd8f6776c0a700fcf04cd610a912a`. If the hash differs, stop and report: the plan must be re-cut.

- [ ] **Step 2: Run the split**

Run: `mise exec -- uv run python work/2026-11/473_memory-map-split/split_473.py`
Expected output, exactly:
```
research/playone-exe/memory-map.md: 11706 bytes
research/playone-exe/memory-map-patch3.md: 13559 bytes
research/playone-exe/memory-map-runtime.md: 7741 bytes
research/playone-exe/memory-map-vm.md: 11380 bytes
research/playone-exe/memory-map-main.md: 11147 bytes
split_473: wrote 26 files
```
Run it once only. A second run exits 1 with `is blob …` and writes nothing; that is expected and harmless.

- [ ] **Step 3: Regenerate the knowledge map**

Run: `mise run fix`
Then: `git diff --stat research/MAP.md`
Expected: `research/MAP.md` changed, 1 line removed and 5 added: the five `playone-exe/memory-map*.md` entries, in the order `memory-map-main.md`, `memory-map-patch3.md`, `memory-map-runtime.md`, `memory-map-vm.md`, `memory-map.md`.

- [ ] **Step 4: Check the changed paths**

Run: `git status --short -- . ':!work'`
Expected, exactly these 27 entries (order may differ):
```
 M .agents/skills/distilling-notes/SKILL.md
 M .agents/skills/distilling-notes/routine.md
 M AGENTS.md
 M docs/ARCHITECTURE.md
 M docs/SPEC.md
 M python/scripts/pair_builds.py
 M python/stunt_reel/doc_anchors.py
 M research/MAP.md
 M research/README.md
 M research/formats/auxiliary/anchorpt.md
 M research/formats/concepts/timeline-and-ticks.md
 M research/formats/memory/actor_record.ksy
 M research/playone-exe/angle-bank.md
 M research/playone-exe/capture-dosbox-automation.md
 M research/playone-exe/capture.md
 M research/playone-exe/lod.md
 M research/playone-exe/memory-map.md
 M research/playone-exe/memory.md
 M research/playone-exe/patch3.md
 M research/playone-exe/sod-vm.md
 M research/playone-exe/static-tooling.md
 M research/playone-exe/terrain-shade.md
 M research/playone-exe/world-scene.md
?? research/playone-exe/memory-map-main.md
?? research/playone-exe/memory-map-patch3.md
?? research/playone-exe/memory-map-runtime.md
?? research/playone-exe/memory-map-vm.md
```
If `mise run fix` also reformatted an unrelated file, stop and report it.

- [ ] **Step 5: Check that no line of the old file was lost**

Run:
```bash
mkdir -p target
git show HEAD:research/playone-exe/memory-map.md | grep -v '^$' | sort -u > target/473_old.txt
cat research/playone-exe/memory-map*.md | sort -u > target/473_new.txt
comm -23 target/473_old.txt target/473_new.txt | wc -l
```
Expected: `20` (the 20 lines the script rewrites, listed in Review Focus 1).

- [ ] **Step 6: Check that no evergreen link targets a moved fragment**

Run: `git grep -n -o --untracked 'memory-map\.md#[a-z0-9-]*' -- . ':!work'`
(`--untracked` is required: the four new files are not tracked yet.)
Expected: exactly 6 lines, each ending `memory-map.md#1-dgroup-memory-reference-table`: `memory-map-patch3.md` lines 10, 69 and 97, `memory-map-runtime.md` line 25, one in `memory.md`, one in `patch3.md`.

- [ ] **Step 7: Run the documentation tests**

Run: `mise run test-docs`
Expected: all pass, no failures.

- [ ] **Step 8: Check the size budget**

Run: `mise run doc-health | grep memory-map`
Expected: no output (grep exits 1). Any line naming a `memory-map` file is a failure: stop and report.

- [ ] **Step 9: Run the gate**

Run: `mise run check`
Expected: the final line is `PASS` and no step prints a warning. A review run classified `split_473.py` as Python, so the gate runs the Python and docs steps (scope `py`, 4 of 4 steps), not the full gate.

- [ ] **Step 10: Commit**

```bash
git add research/playone-exe/memory-map.md research/playone-exe/memory-map-patch3.md \
  research/playone-exe/memory-map-runtime.md research/playone-exe/memory-map-vm.md \
  research/playone-exe/memory-map-main.md research/MAP.md python/stunt_reel/doc_anchors.py \
  python/scripts/pair_builds.py docs/ARCHITECTURE.md docs/SPEC.md AGENTS.md research/README.md \
  .agents/skills/distilling-notes/SKILL.md .agents/skills/distilling-notes/routine.md \
  research/formats/auxiliary/anchorpt.md research/formats/concepts/timeline-and-ticks.md \
  research/formats/memory/actor_record.ksy research/playone-exe/angle-bank.md \
  research/playone-exe/capture.md research/playone-exe/capture-dosbox-automation.md \
  research/playone-exe/lod.md research/playone-exe/memory.md research/playone-exe/patch3.md \
  research/playone-exe/sod-vm.md research/playone-exe/static-tooling.md \
  research/playone-exe/terrain-shade.md research/playone-exe/world-scene.md \
  work/2026-11/473_memory-map-split/split_473.py
git status --short
git commit -F - <<'EOF'
docs(research): split memory-map.md by segment (#473)

memory-map.md was 52 KB against the 20 KB budget. It keeps its path as the index and the
DGROUP table; the Patch #3 table, the runtime capture anchors, the VM work segment and the
main-program table move to four files beside it, with section numbers and heading slugs
unchanged so each inbound link changes only its file name. move-docs moves whole files, so
work/2026-11/473_memory-map-split/split_473.py made the cut and the relinking instead, with
an expected count on every edit; doc_anchors.py names each [MEM-*] anchor's new home.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Expected: `git status --short` before the commit shows 28 staged paths (`M ` or `A `): the 27 of Step 4 plus `split_473.py` (27 if `split_473.py` was already committed, in which case `git add` of it is a no-op). Nothing in this folder besides `split_473.py` is staged; never stage `plan.md` or `README.md`. The commit-msg hook passes.

---

### Task 2: Fresh review, then land (the review is done by a different model from Task 1's)

AGENTS.md § Committing rule 5: before a push that changes `research/` or `docs/*.md`, a fresh reviewer reads the diff and the notes it cites. Run the reviewer as a Claude subagent (Sonnet or Opus), not as the model that executed Task 1.

- [ ] **Step 1: Brief the reviewer** with this prompt, verbatim:

> Review commit `HEAD` in this repository (`git show HEAD`, and `git show HEAD~1:research/playone-exe/memory-map.md` for the old file). It splits `research/playone-exe/memory-map.md` into five files by segment and rewrites inbound links; `work/2026-11/473_memory-map-split/plan.md` says why each choice was made and `split_473.py` there made the edit. Report, each with `file:line`: (1) any row or sentence of the old file missing from the five new files, or changed other than in the 20 lines the plan's Review Focus 1 lists; (2) each rewritten inbound link whose sentence cites a row that is not in the file it now points to (open the target and find the offset the sentence names); (3) any claim in the new `memory-map.md` intro, its file table, or any of the five `summary:` lines broader than the file's content (`only`, `all`, `every`, "split by segment"); (4) any `[MEM-*]` anchor whose `doc_anchors.py` home is not the file holding its heading. Do not edit files. Say "none" for an empty list.

- [ ] **Step 2: Fix each finding** in a follow-up commit (`docs(research): <what> (#473)`), editing the named line by hand, then rerun `mise run test-docs` and `mise run check` (expect `PASS`). A finding you disagree with gets a one-line answer for the PR body instead.

- [ ] **Step 3: Write the outcome**

Edit `work/2026-11/473_memory-map-split/README.md`: set `outcome: "memory-map.md split by segment into five files, each under 20 KB, with every [MEM-*] anchor re-homed and inbound links rewritten."` and change the `**Status.**` line to `**Status.** Landed in one PR.` Do not touch `plan.md` (committed before Task 1).

```bash
git add work/2026-11/473_memory-map-split/README.md
git commit -F - <<'EOF'
docs(work): record the memory-map split outcome (#473)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```
Expected: the commit-msg hook passes.

- [ ] **Step 4: Push and open the PR**

Run `git push -u origin HEAD`, then open the PR with the `pr` skill: title `docs(research): split memory-map.md by segment (#473)`, body naming the five files and sizes from the Decisions table, `Closes #473`, and any reviewer finding answered rather than fixed.
