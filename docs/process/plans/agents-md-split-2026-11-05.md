# AGENTS.md split into project skills (2026-11-05)

Status: **implemented 2026-11-05**. Tasks: [`agents-md-split-implementation-2026-11-05.md`](agents-md-split-implementation-2026-11-05.md), on branch
`claude/agents-md-refactor-72199a`. Source: a brainstorming session of 2026-11-05 that started
from "AGENTS.md and the other agent files are getting unwieldy; suggest splitting into project
skills"; the same session added a disk-space gate on `mise run reap` (D7, 4.6). This note owns
the design; the task list will be a sibling
`agents-md-split-implementation-2026-11-05.md`.

## 1. Goal

Cut the guidance every turn pays for without hiding a rule every task needs:

- `AGENTS.md` drops from 19,320 bytes to about 8 KB and keeps only the rules every task needs.
- Each meaning has one home. A procedure only some tasks need lives in a skill under
  `.agents/skills/`, reached by its description, or in an existing doc, reached by one pointer line.
- `mise run check` passes, and every new skill passes its own evaluation (section 6).

## 2. What forced it

- `AGENTS.md` is loaded on every turn of every Claude Code session (through `CLAUDE.md`), about
  5k tokens. SOP 1 (contracts), SOP 2 and SOP 4 (binary findings and tier promotion) and most of
  SOP 6 (data root, captures, reaping) each serve one kind of task.
- It caches material that lives elsewhere: the `[I1]`–`[I8]` bullets restate
  [`docs/SPEC.md` § 2](../../SPEC.md); the "Binary Disassembly" and "Parity" rows of its table
  index files that [`research/README.md`](../../../research/README.md) and the
  `improving-render-parity` skill already route to; the gate details restate ADRs 0014 and 0016.
- [`docs/harness.md`](../../harness.md) Policy restates SOP 5.5 and SOP 6 (one writer per
  checkout), so the two drift.
- `.claude/skills/improving-render-parity/SKILL.md` copies the real skill's description by hand
  and nothing checks the copy.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Only Claude Code needs to discover skills; other harnesses (DeepSeek, Orca/Codex) stay in use but read `AGENTS.md` only. | The session's answer; `AGENTS.md` needs no skill index. |
| D2 | Skills live only in `.agents/skills/`; `.claude/skills/` is deleted, and `AGENTS.md` points at each skill under `### Skills` with its trigger. | Revised 2026-11-05 after the first evaluation: Claude Code does not list `.agents/skills/` (every run's `init` skill list lacked the new skills). A `.claude/skills` symlink works where git checks out symlinks, but fails silently where it does not; pointers work in every harness, at about 700 bytes of `AGENTS.md`. |
| D3 | Keep the rules every task needs in `AGENTS.md`, move procedures only some tasks need into skills, and remove the repeats. | Rejected: trim-only (pointers to docs carry no description to trigger on) and a pure router (every-task rules would depend on a trigger firing). |
| D4 | SOP numbers become named headings; live citations name the heading or the skill. | A number breaks when a section moves; a name survives. |
| D5 | Skill descriptions state only when to use the skill ("Use when …", one clause per distinct case), never the workflow. | superpowers:writing-skills: an agent follows a workflow summary in the description instead of reading the body. |
| D6 | Each skill names the models expected to use it, and is evaluated on each. | A skill Haiku will use must be shown to work with Haiku. |
| D7 | `mise run reap` removes nothing while the drive holding the primary checkout has 20 GB or more free; `--min-free-gb N` changes the bar and `--force` skips it. | The session's request: reaping only earns its risk when space is short. Gating the tool holds for every agent and harness, which wording in a skill would not. |

## 4. Design

### 4.1 What AGENTS.md keeps

1. **One-line description of the project.**
2. **Non-negotiables.** Asset isolation and the gate as today. The invariants become one line of
   names (`[I1]` coordinates … `[I8]` 8.3 paths) linking to SPEC § 2; thresholds and detail stay
   in SPEC.
3. **Where things live**, a shorter routing table:
   - "Binary Disassembly" becomes one line: `research/playone-exe/` holds the `PLAYONE.EXE`
     evidence, and `research/README.md` routes to it.
   - "Parity" points at `research/parity/`.
   - "Project Setup" loses its gate details.
   - "Agent Skills" is removed.
   - "Skill Configuration" and the closing "Agent skills" section merge into one row.
   - The "process docs are not sources of truth" line stays; `tests/test_doc_invariants.py`
     enforces it.
4. **Working rules**, under named headings:
   - **Committing** (from SOP 3 and Commit Messages): stage files by name, Conventional Commit
     subject, a body that answers why, the gate line. Handoffs go in the note that owns the work,
     never only in agent memory, and append-only files such as `research/parity/log.md` take rows
     only at the end (from SOP 6.4). A pull request that changes rendered output carries a
     capture-beside-render picture, one line linking the `improving-render-parity` section. That
     line stays loaded because an agent changing the renderer outside parity work would never
     trigger the skill.
   - **Working economically** (SOP 5, same substance): fewer and fuller turns, scoped checks,
     scripts before subagents, everything through `mise run`.
   - **Worktrees**: one writer per checkout path, with worktrees under `.claude/worktrees/` or
     `.agents/worktrees/`; a worktree the tool that made it cannot remove is reaped with
     `mise run reap -- --yes` from the primary checkout. This stays loaded every turn because a
     wrong removal of an old linked worktree can delete shared data.

SOP 1, SOP 2 and SOP 4 leave `AGENTS.md` entirely. Three lines go with nothing in their place:
SOP 3.3 (link modified symbols in markdown, which Claude Code already does), SOP 5.4 (parity
work follows its skill, which the skill's description already triggers), and SOP 6.1's note
that `tests/test_worktree_layout.py` requires the worktree directories in `.gitignore` and
ruff's `exclude` (the test enforces it).

### 4.2 New skills

Each is `.agents/skills/<name>/SKILL.md`, under 500 words: a one-line overview, steps each
ending on a checkable done-condition, a quick-reference table, and **Common mistakes** filled
only from the baseline failures the evaluation records. A fact another doc owns is linked, not
copied.

| Skill | Source | Models | Description |
|---|---|---|---|
| `changing-seam-contracts` | SOP 1, SOP 4.2 | Opus | Use when adding or changing a stunt-core seam contract or format parser (a type or field under `crates/stunt-core/src/contracts/`: vfs, trajectory, shape, palette), or the synthetic fixtures that test one. |
| `recording-binary-findings` | SOP 2, SOP 4.1 | Opus | Use when disassembly, a debugger session or a capture turns up an offset, opcode, DGROUP field or behaviour of PLAYONE.EXE, MAKEONE.EXE, STUNT.EXE or a game file format worth keeping in `research/`, or when promoting a finding's evidentiary tier. |
| `managing-worktrees` | SOP 6.1–6.3, 6.5 | Opus, Haiku | Use when creating, removing or reaping a stunt-reel worktree, running `mise run reap` or `clean`, or when a task in a worktree needs the corpus, a capture or the data root (`STUNT_DATA_ROOT`). |

Each skill's steps and the condition that ends them:

- **`changing-seam-contracts`:**
  1. Add or change the types and re-export them from `contracts/mod.rs`.
  2. Give each new field `#[cfg_attr(feature = "serde", serde(default))]`.
  3. Write synthetic fixture bytes and their entry in `tests/fixtures/README.md`.
  4. Add unit and roundtrip tests and run them with `--all-features`.
  5. Run `mise run check-rust` while iterating, then the full gate.

  Done when every new field has a roundtrip test and every new fixture has a README entry.
- **`recording-binary-findings`:**
  1. Choose the owning note by the routing rule in `research/README.md`; link the rule, don't
     copy it.
  2. Add every new `PLAYONE.EXE` offset to `research/playone-exe/memory-map.md`, and register every new
     `# [MEM-*]`/`# [FMT-*]` anchor in `python/stunt_reel/doc_anchors.py`.
  3. Raise the evidentiary tier. The ladder is owned by `EVIDENTIARY_TIERS` in
     `python/scripts/verify_formats_docs.py`; each step up cites the linear address or the note
     that proves it.
  4. Change `docs/SPEC.md` only if the finding changes a goal, invariant or gate.

  Done when the note ends with **Ruled out** and **Open questions**, and every offset and anchor
  it introduces is registered.
- **`managing-worktrees`:** where worktrees go and the Orca exception; that a new worktree needs
  no setup (ADR 0036); the data root and its captures, the SOP 6.3 paragraph (ADRs 0022, 0024,
  0028, `references.toml` pins); reaping and its flags. It links to
  [`docs/harness-setup.md`](../../harness-setup.md) for the junction and robocopy details and
  to [`docs/harness.md`](../../harness.md) for writer modes, without copying either.

### 4.3 Removing the remaining repeats

- **`docs/harness.md` Policy:** the gate, `mise run`, and one-writer bullets become a single line
  linking to `AGENTS.md`'s headings. The policies only it holds stay: worktree-per-writer mode,
  which model a subagent uses, globbing from a named folder, and the note that nothing enforces
  these for you.
- **`.claude/skills/`:** deleted; `AGENTS.md` points at the skills instead (D2). `CLAUDE.md`'s second sentence, which says the stub
  works "the same way `.claude/skills/` points at `.agents/skills/`", loses that comparison.

### 4.4 Citations

`SOP <n>` and `Directive <n>` citations in live files become the heading or skill name:

- `.github/workflows/ci.yml`, `mise.toml`
- `python/scripts/check_commit_msg.py` with `tests/test_check_commit_msg.py`
- `python/scripts/worktree_init.py`, `tests/test_parity_frame.py`, `tests/test_worktree_layout.py`
- `docs/harness.md`, `docs/harness-setup.md`
- ADRs 0008, 0012, 0026 (its `SOP 6.4` link gets a heading anchor) and 0031

Dated plans under `docs/process/plans/` are records of the past, so they keep their old
citations. The directives stay numbered, so `Directive <n>` citations stay valid.

### 4.5 New check

`python/scripts/verify_formats_docs.py` adds `.agents/skills/*/SKILL.md` to `LINK_SCAN_GLOBS`,
so a broken link in a skill fails the gate.

### 4.6 Reaping waits for low disk space (D7)

In `python/scripts/worktree_init.py`, `reap` first reads the free space on the drive holding the
primary checkout (`shutil.disk_usage`).

- **At or above the bar** (default 20 GB, set by `--min-free-gb`): it prints the free space, the
  bar and what it would reap, then exits 0 without removing anything, `--yes` or not.
- **Below the bar, or with `--force`:** it reaps as it does today.
- **A dry run** (no `--yes`) prints the free space and the bar before its usual list.

The `mise.toml` task description names both flags, and the `managing-worktrees` skill says to
reap when space is short. Tests in `tests/` drive the gate through a stubbed `disk_usage`,
covering above the bar, below it, and `--force`.

## 5. Order

1. Trim `AGENTS.md` (4.1) and fix the citations (4.4). The skills draw the removed SOP text
   from `git show main:AGENTS.md`.
2. For each skill in turn: run the baseline, write the skill, run the evaluation with the skill
   (section 6). Only then start the next skill.
3. `docs/harness.md` (4.3), the link check (4.5), delete `.claude/skills/`.
4. The reap gate (4.6), test-first. It is independent of steps 1–3 and lands in its own commit.
5. Verification (section 7), then a pull request.

## 6. Skill evaluation

Each run is a dry run in this worktree: the prompt below, then "list the files you would touch
and the steps you would take; edit nothing". Three repetitions per model, each a headless
session: `claude -p --model <opus|haiku> --permission-mode plan --output-format stream-json
--verbose "<prompt>"`. A real session sees the real skill listing, plan mode keeps it read-only,
and the stream shows whether it called the Skill tool, which a subagent's final report would
hide. The command is not pre-approved, so each batch of repetitions runs as one shell command
and asks once.

| Skill | Model | Prompt | Must cover |
|---|---|---|---|
| `changing-seam-contracts` | Opus | Add a field to the shape contract (`crates/stunt-core/src/contracts/shape.rs`) recording the name of the resource the shape came from. | `serde(default)` on the field; a synthetic fixture and its `tests/fixtures/README.md` entry; a roundtrip test run with `--all-features` |
| `recording-binary-findings` | Opus | A debugger session found that `PLAYONE.EXE` keeps the camera's lens index at `DGROUP:0x1A2C` and reads it at `1A2F:0042` (a made-up example). Record it. | the owning note chosen by `research/README.md`; a `memory-map.md` row; a `doc_anchors.py` entry for any new anchor; a tier that cites the address; **Ruled out** and **Open questions** |
| `managing-worktrees` | Opus | Remove the worktree `.claude/worktrees/old-branch`, made before ADR 0036, whose pull request was squash-merged. | `mise run reap -- --yes` from the primary checkout, after its dry run; no `git worktree remove` by hand; the 20 GB bar and `--force` (D7) |
| `managing-worktrees` | Haiku | From this worktree, find the reference capture for `CTRY.FLM` and say whether it is complete. | the data root (`STUNT_DATA_ROOT` or the sibling `.data` directory); `captures/<film slug>/frames` (here `vault-ctry`), complete only once its `meta.json` exists; the pin in `research/parity/references.toml` |

- **Baseline (expected to fail):** trimmed `AGENTS.md`, skill absent. Record what each run
  misses, word for word.
- **With the skill (expected to pass):** skill present. A pass means the transcript shows the
  skill loaded without being named in the prompt, and the answer covers every item in its
  row. The first such run also settles D2.
- **Tightening:** a miss in the second run changes the wording, not the length, and that skill is
  tested again.
- **Already-followed rules:** a rule the baseline already follows is one the model follows by
  default; it is deleted rather than moved into the skill.

Record the results in section 8 of this note.

## 7. Verification

- `mise run check` passes.
- `AGENTS.md` is at most about 8 KB.
- `git grep -n 'SOP [0-9]' -- ':!docs/process/plans'` finds nothing. (`git grep` keeps out
  the other worktrees under `.claude/worktrees/`, which a plain recursive grep walks.)
- Every skill passes section 6 on each model named for it.

## 8. Results

Run 2026-11-05 with `mise run skill-eval`, three repetitions per row, about $13 in all. A run
"loaded" the skill when it called Skill or read the skill's `SKILL.md`; no counted run read this
spec or its plan.

| Skill | Model | Baseline (no skill): misses in every run | With the skill |
|---|---|---|---|
| `changing-seam-contracts` | Opus | `serde(default)`; any fixture or `tests/fixtures/README.md` entry; a roundtrip test run with `--all-features` | 3/3 loaded; 3/3 cover the fixture README entry and a fixture test, and say why `serde(default)` does not apply |
| `recording-binary-findings` | Opus | **Ruled out** (all three chose the note, the `memory-map.md` row and a tier unaided) | 3/3 loaded; 3/3 cover every item |
| `managing-worktrees` | Opus | none: the `AGENTS.md` Worktrees rule and the `reap` task description already carry reap, the dry run, no `git worktree remove`, the 20 GB bar and `--force` | 3/3 loaded; 3/3 cover every item |
| `managing-worktrees` | Haiku | one run missed the data root, `captures/vault-ctry/frames` and the `meta.json` rule; another found the `meta.json` rule only by grepping this spec (peeked) | 3/3 loaded; 3/3 cover every item |

Findings that changed the design or the tooling:

- **D2.** Claude Code does not list skills from `.agents/skills/`: no run's `init` skill list held
  the new skills. The first with-skill runs found them only through untracked paths in git status,
  so with-skill runs now start from a clean tree. `AGENTS.md` points at each skill instead.
- **Reading is loading.** Haiku read `SKILL.md` with Read rather than calling Skill, so
  `skill-eval` counts both.
- **Peeking through results.** A Grep result can quote this spec; `skill-eval` marks that run
  peeked.
- **Tightening.** `changing-seam-contracts` first stated its serde rule for every field. All three
  runs on the shape prompt rightly declined it, since `SodModelIr` and `DecodeRecord` do not derive
  serde; the rule is now keyed to types that do, and the re-run passed. The table's must-cover item
  for that row assumed a serde type, so the re-run is judged against the conditional rule.
- **Merging #238.** `main` widened SOP 2 to rendering and render-residual findings and added
  Directive 4. The skill became `recording-findings` with that scope, Directive 4 points at it
  (its `Skills` line went), and `changing-seam-contracts` records new format facts by it.
  Re-run with the same prompt: 3/3 loaded `recording-findings` and covered every item.

## Out of scope

- Rewording `improving-render-parity`'s description into the "Use when …" form (D5); a
  follow-up.
- `docs/development.md` (35 KB) and `docs/ARCHITECTURE.md` (22 KB); neither is loaded every
  turn.
- Personal skills under `~/.claude/skills/`.

## Open questions

- None: D2 was settled by the first evaluation in favour of `AGENTS.md` pointers.
