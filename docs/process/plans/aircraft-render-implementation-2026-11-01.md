# Aircraft Render Errors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Find and fix why `CTRY.FLM`'s aircraft loses its fuselage and `INTRO.FLM`'s aircraft is
not drawn, adopting each fix only through the score gate and the error readout.

**Architecture:** The lead session takes a baseline, dispatches two Sonnet diagnosticians in scratch
worktrees at once, then for each diagnosis applies the fix test-first in this worktree, runs a
score gate (no subagents) and, if it passes, a readout gate (Haiku and Sonnet graders), and commits
or reverts. The fix code cannot be written in advance: each fix task takes its files, test and
change from that track's `diagnosis.md`, and this plan fixes everything around it.

**Tech Stack:** Rust (`stunt-core`, `stunt-render`, `stunt-cli`), Python bench and probe scripts,
`mise` tasks, Claude subagents (Agent tool, `model` override).

**Spec:** [`aircraft-render-2026-11-01.md`](aircraft-render-2026-11-01.md)

## Global Constraints

- Worktree `E:\git\stunt-reel.wt\aircraft-render`, branch `fix/aircraft-render`; every command
  below runs there unless it names another directory.
- Scratch worktrees from `origin/main` at `514053c`: `E:\git\stunt-reel.wt\aircraft-diag-a`
  (branch `diag/aircraft-a`) and `E:\git\stunt-reel.wt\aircraft-diag-b` (branch `diag/aircraft-b`).
- References (`research/parity/references.toml`): `ctry` is `build/parity/captures/vault-ctry/frames/004`,
  `intro` is `build/parity/captures/vault-intro/frames/004`. Never edit `references.toml`; never capture.
- Noise floor for both films: `--noise-sigma 0.000303 --build-floor 0`.
- Readout `min_change` is 4 frames of 12 (`research/parity/error-categories.toml`).
- Tests use synthetic fixtures only (`tests/fixtures/`, no game bytes; Directive 1, [I7]).
- At most two rounds per track; a track stops after two rounds with nothing adopted.
- Stage paths by name; Conventional Commit subjects; bodies say why and end with
  `mise run check passes.` only when the full gate ran.
- Every attempt, adopted or not, gets a row at the end of `research/parity/log.md`.

## Review Focus

- **A correct body drawn at the hero's 10 px offset lowers SSIM** (`method.md` § 2.2): the score
  gate must pass it on actor overlap, not reject it; Task 5 step 4 pins this.
- **A fix aimed at one film moves the other** (a cull or decode change reaches every shape): the
  score gate always runs both films; Task 5.
- **A gate render that is not the fix's** (stale binary, `--no-build` after an edit): Task 5 builds
  before rendering, and `errors-score` refuses a render changed since `errors-make`.
- **A diagnosis that rests on instrumentation output alone**: Task 3 reruns its key command in a
  clean build before any fix is applied.
- **A subagent acting on the wrong checkout:** every subagent's shell starts in the primary
  checkout, so a relative path or a bare `mise run` lands there, breaking SOP 6. The briefs give
  absolute paths and a `cd` rule; Task 9's reap dry run and `git -C E:/git/stunt-reel status`
  show any leftover.

---

### Task 1: Baseline scores, overlap and readout

**Files:**
- Create (gitignored): `build/scratch/baseline/{ctry,intro}/{render/,report.json,iou.txt,readout.json}`
- Create (gitignored): `build/scratch/gate_check.py`

**Interfaces:**
- Produces: the baseline tree above, read by Tasks 2, 5 and 6; `gate_check.py` used by Task 5.

- [ ] **Step 1: Render and score both films**

Run: `mise run parity -- --films ctry,intro`
Expected: one summary line per film; `CTRY` about SSIM 0.78, `INTRO` about 0.55 (log 2026-10-31,
`004`). A different headline means the binary or references moved; stop and report.

- [ ] **Step 2: Keep the baseline**

Copy `build/parity/ours/<film>_current/` to `build/scratch/baseline/<film>/render/` and
`build/parity/report/<film>_current/report.json` to `build/scratch/baseline/<film>/report.json`,
for `ctry` and `intro`.

- [ ] **Step 3: Actor overlap**

Run, per film (`<cap>` from Global Constraints):
`mise run parity-probe -- iou --reference <cap> --ours build/scratch/baseline/<film>/render --report build/scratch/baseline/<film>/report.json`
Expected: one line `<iou> <frames>`; save it to `build/scratch/baseline/<film>/iou.txt`.

- [ ] **Step 4: Readout sheets**

Run: `mise run parity-bench -- errors-make --film ctry` and `... --film intro`
Expected: `build/parity/bench/<film>/errors/` holds 12 sheets, `brief.md`, `brief-2.md`.

- [ ] **Step 5: Two Haiku graders at once** (`model: "haiku"`, background)

Prompt 1, whole: "Read E:/git/stunt-reel.wt/aircraft-render/build/parity/bench/ctry/errors/brief.md
and follow it; then read …/bench/intro/errors/brief.md (same prefix) and follow it. Each is your
whole instruction for its film." Prompt 2: the same with `brief-2.md`. Absolute paths, because a
subagent's shell starts in the primary checkout; the briefs themselves already name absolute
folders. Wait for both notifications.

- [ ] **Step 6: Disputes and tie-break**

Run: `mise run parity-bench -- errors-disputes --film ctry` and `... --film intro`.
If either names disputed sheets, one Sonnet subagent (`model: "sonnet"`) with the prompt "Read
E:/git/stunt-reel.wt/aircraft-render/build/parity/bench/<film>/errors/brief-tiebreak.md and follow
it", listing each film that has one, in one prompt.

- [ ] **Step 7: Score and keep the readouts**

Run: `mise run parity-bench -- errors-score --film ctry` and `... --film intro` (no `--against`).
Copy each `build/parity/bench/<film>/errors/readout.json` to `build/scratch/baseline/<film>/readout.json`.
Expected: the three aircraft categories' 2+ counts near the log's (CTRY parts missing 11–12 of 12;
INTRO absent 7–10 of 12).

- [ ] **Step 8: Write `build/scratch/gate_check.py`**

`gate_check.py <compare.json> <iou-before.txt> <iou-after.txt>` prints `PASS` or `FAIL` and the
reason. Rule: let *F* be the verdict frames (`compare.json` → `verdict.frames`) with
`class == "further"`; a frame in *F* is actor-driven when `changed_by_layer["actors"]` is at least
half the sum of its `changed_by_layer` values (the layer is the *after* render's). FAIL when any
frame in *F* is not actor-driven, or when *F* holds actor-driven frames and the after IoU is not
greater than the before IoU. Print each failing frame's `film_tick` and its `changed_by_layer`.
Run it with `mise exec -- uv run python build/scratch/gate_check.py …` (an approval prompt).

No commit: everything in this task is gitignored.

### Task 2: Scratch worktrees and the two diagnosticians

**Files:**
- Create: the two scratch worktrees in Global Constraints.

**Interfaces:**
- Consumes: `build/scratch/baseline/` (Task 1).
- Produces: in each scratch worktree, `build/scratch/<track>/diagnosis.md`, `fix.patch`,
  `instrumentation.patch` (`<track>` is `a` or `b`).

- [ ] **Step 1: Create and initialise**

```bash
git -C E:/git/stunt-reel worktree add -b diag/aircraft-a E:/git/stunt-reel.wt/aircraft-diag-a 514053c
git -C E:/git/stunt-reel worktree add -b diag/aircraft-b E:/git/stunt-reel.wt/aircraft-diag-b 514053c
```
Then `mise run init` in each. Expected: the data-root links listed, `uv sync` done.

- [ ] **Step 2: Dispatch both at once** (`model: "sonnet"`, background)

Each prompt is the shared brief below with its track block appended.

**Shared brief** (replace `<W>` with the scratch worktree, `<M>` with
`E:\git\stunt-reel.wt\aircraft-render`, `<t>` with the track letter):

> You are diagnosing one rendering error in stunt-reel, a reimplementation of the 1992 game *Stunt
> Island*'s film player. Read `<W>\AGENTS.md` and the cost rules in
> `<W>\.agents\skills\improving-render-parity\SKILL.md` first. Work only in `<W>`, a scratch
> worktree of `origin/main`: you may edit source there to add instrumentation and build it
> (`mise run parity -- --films <film>` builds, renders and scores; `target\release\stuntreel.exe
> export-gltf --help` exports a shape or a film frame as glTF). Never commit, push, capture, run
> `mise run reap` or `clean`, edit `research\parity\references.toml`, or write outside `<W>`.
> AGENTS.md's quality gate and commit rules do not apply to you, since you commit nothing.
>
> Your shell starts in `E:\git\stunt-reel`, another checkout, on every call: begin every Bash
> command with `cd <W in forward slashes> &&`, and give file tools absolute paths under `<W>`.
> Prefer `mise run …` tasks and `target/release/stuntreel.exe`, which run without an approval
> prompt; other commands may wait for one.
>
> Read-only inputs: the baseline render and report at `<M>\build\scratch\baseline\<film>\`; the
> reference capture at `<W>\build\parity\captures\<capture>`; the corpus at
> `<W>\corpus\stisldem\VAULT\` (archives `CTRY.ALL`, `INTRO.ALL`) and `SIDATA` at
> `<W>\corpus\siarchive\Developer\FreeFlight\SIDATA`; notes `research\parity\framing-and-actors.md`
> § 1, `research\playone-exe\sod-vm.md`, `research\formats\sod-opcodes.md`; the example sheets in
> `research\parity\error-examples\`. `mise run parity-probe -- crop|iou ...` crops and measures.
>
> Output, in `<W>\build\scratch\<t>\`: `diagnosis.md` with exactly these headings — **Claim** (one
> root cause, one paragraph), **Evidence** (counts, offsets, commands with their output; cite at
> most 3 images), **Proposed change** (files and functions, and the synthetic test that would fail
> before it), **Predicted effect** (per film, on the aircraft and on everything else), **Ruled out**,
> **Open**; `fix.patch` (`git diff` of the proposed change only, against `origin/main`); and
> `instrumentation.patch` (`git diff` of your instrumentation). Then run `git checkout -- .` and
> delete untracked files you added outside `build\`, so the worktree is clean.
>
> Stop when you have a claim backed by evidence, or after about 60 tool calls or 10 images read;
> then write the best lead and what you ruled out under the same headings. If the cause needs a
> rule from `PLAYONE.EXE` that the notes do not decode, say so under **Claim** and propose no
> change. Your final reply is at most five lines: the claim and the path to `diagnosis.md`.

**Track A block** (film `intro`, capture `vault-intro\frames\004`):

> The error: in `INTRO.FLM` the aircraft is not drawn at all on 7–10 of 12 graded frames; at tick
> 1009 (`error-examples\intro-1009.png`) the capture shows a red triplane and a parked vehicle and
> figure, and our render draws only a flat black shape where the triplane is, no vehicle, no figure.
> Tick 1108 is a second example. Answer: which actor slot and shape is the aircraft at tick 1009?
> Is that shape in `INTRO.ALL`, and does `decode_sod` reach `RETURN` or stop on a blocking opcode
> (its `DecodeRecord`)? How many triangles of it reach the renderer at that tick after LOD, `IFVIS`
> and back-face culling? What is the flat black shape: a shadow, or the aircraft collapsed or
> recoloured? Are the missing vehicle and figure the same cause? `vault-land` and `vault-splanes`
> show the same error but have no kept render; use them only if your claim needs a second film.

**Track B block** (film `ctry`, capture `vault-ctry\frames\004`):

> The error: in `CTRY.FLM` the hero biplane, shape `0x7F37`, is drawn as its lower wing and struts
> only; the capture shows a white and blue fuselage, upper wing, wheels and cowl (ticks 48 and 92,
> `error-examples\ctry-0048.png`, `ctry-0092.png`). Known (`framing-and-actors.md` § 1): the shape
> decodes to 36 opcode polygons (20 `POLYZ`, 16 `GVPOLY`), 388 vertices and 195 triangles in four
> nodes, one gated at `LodDistanceSq(1000)`; the body was a 4–6 px sliver before back-face culling
> was adopted (`attribution.md` § 6) and is still missing after it. Answer: do all 36 opcode
> polygons reach the mesh? With culling off, which faces does the cull remove? Is the
> `LodDistanceSq(1000)` node ever drawn in this film? Is the fuselage behind an `IFVIS`/BSP branch
> we take wrongly, or behind the undecoded two-sided flag (`SodVertex::flags` bit 1)?

- [ ] **Step 3: Wait for both notifications**

Do not poll. Each reply names its `diagnosis.md`.

### Task 3: Review a diagnosis (once per track, as each returns)

**Interfaces:**
- Consumes: the scratch worktree's `build/scratch/<t>/` (Task 2).
- Produces: `<M>/build/scratch/<t>/` (a copy) and a decision: *fix*, *merged with the other
  track*, or *finding only*.

- [ ] **Step 1: Copy** the scratch worktree's `build/scratch/<t>/` to this worktree's `build/scratch/<t>/`.
- [ ] **Step 2: Read** `diagnosis.md`; check every heading is present and the claim names one cause.
- [ ] **Step 3: Rerun its key evidence command** in the scratch worktree, now idle: with
  `git -C <W> apply build/scratch/<t>/instrumentation.patch` first if the command needs it, then
  `git -C <W> checkout -- .` after. Expected: the output quoted under **Evidence**. A mismatch
  means *finding only* for this round, recorded in Task 7.
- [ ] **Step 4: Decide.** *Fix* when **Proposed change** names files and a failing test and
  `git apply --check build/scratch/<t>/fix.patch` succeeds (or the change is small enough to adapt);
  *merged* when both tracks name the same cause (one fix, gated against both tracks' bars);
  *finding only* when the claim needs an undecoded `PLAYONE.EXE` rule.
- [ ] **Step 5: Size check.** More than about 100 changed lines or a second crate: dispatch one
  Sonnet implementer for Task 4 with Task 4's steps and the diagnosis as its prompt; it does not commit.

### Task 4: Apply the fix test-first (per *fix* decision)

One fix is in flight at a time: a second track's Task 4 starts only after the first's Task 7.

**Files:** as `diagnosis.md` **Proposed change** names them; the test in the crate's `tests/`
directory or its unit-test module, its bytes built in the test or added under `tests/fixtures/`
and described in `tests/fixtures/README.md` (SOP 1).

**Interfaces:**
- Consumes: `build/scratch/<t>/diagnosis.md`, `fix.patch`.
- Produces: an uncommitted change set; its file list is recorded in `build/scratch/<t>/files.txt`
  for revert.

- [ ] **Step 1: Write the failing test** named in **Proposed change**, on synthetic shape bytes that
  reproduce the defect (for example, a two-polygon shape in which the dropped polygon's path is
  the one the claim names). Assert on the decoded or emitted geometry the claim says is lost.
- [ ] **Step 2: Run it.** `mise exec -- cargo test -p <crate> --all-features <test_name>`. Expected:
  FAIL for the reason the claim gives.
- [ ] **Step 3: Apply the change** (`git apply build/scratch/<t>/fix.patch`, adapted to what has
  landed since `514053c`).
- [ ] **Step 4: Run it.** Same command. Expected: PASS.
- [ ] **Step 5: Scoped gate.** `mise run check-rust`. Expected: PASS on every step.
- [ ] **Step 6: Record** `git status --porcelain` paths into `build/scratch/<t>/files.txt`.

### Task 5: Score gate (per fix; no subagents)

**Interfaces:**
- Consumes: the Task 4 change; `build/scratch/baseline/`; `gate_check.py`.
- Produces: `build/scratch/<t>/gate/<film>/{compare.json,iou.txt}` and PASS or FAIL.

- [ ] **Step 1: Build, render, score.** `mise run parity -- --films ctry,intro` (builds first).
  Record both summary lines.
- [ ] **Step 2: Verdict, per film:**
  `target/release/stuntreel.exe parity --reference <cap> --test build/parity/ours/<film>_current --output build/scratch/<t>/gate/<film> --compare build/scratch/baseline/<film>/report.json --compare-test build/scratch/baseline/<film>/render --noise-sigma 0.000303 --build-floor 0`
  Expected: a `[verdict] changed …` line; `compare.json` in the output directory.
- [ ] **Step 3: Overlap, per film:** Task 1 step 3's command on `build/parity/ours/<film>_current`
  and `build/parity/report/<film>_current/report.json`, saved to `build/scratch/<t>/gate/<film>/iou.txt`.
- [ ] **Step 4: Check, per film:**
  `mise exec -- uv run python build/scratch/gate_check.py build/scratch/<t>/gate/<film>/compare.json build/scratch/baseline/<film>/iou.txt build/scratch/<t>/gate/<film>/iou.txt`
  Expected: `PASS` on both films. A `further` frame driven by the aircraft passes only with the IoU
  rise (Review Focus 1). Either FAIL: go to Task 7 as *not adopted*, without a readout.

### Task 6: Readout gate (per fix that passed Task 5)

- [ ] **Step 1:** Task 1 steps 4 to 6 on the current render (sheets, two Haiku graders, disputes,
  tie-break).
- [ ] **Step 2:** `mise run parity-bench -- errors-score --film <film> --against build/scratch/baseline/<film>/readout.json`
  for `ctry` and `intro`. Expected: the categories whose 2+ count moved by 4 or more, per film.
- [ ] **Step 3: Apply the bar.**
  - Track A: `aircraft-absent` falls by 4 or more on `intro`; `aircraft-parts-missing` and
    `aircraft-shape-broken` may rise.
  - Track B: `aircraft-parts-missing` or `aircraft-shape-broken` falls by 4 or more on `ctry`, and
    `aircraft-absent` does not rise by 4 or more.
  - Either: no category outside the three aircraft ones rises by 4 or more on either film.
  - *Merged*: both tracks' bars.
  PASS adopts (Task 7); FAIL does not.

### Task 7: Adopt or revert, and record

**Files:**
- Modify: `research/parity/log.md` (append one row at the end)
- Modify: the note owning the finding (`research/parity/framing-and-actors.md` § 1,
  `research/playone-exe/sod-vm.md`, or the one the diagnosis names): the finding with its tier, or
  a **Ruled out** entry when not adopted.

- [ ] **Step 1 (not adopted only): Revert** the paths in `build/scratch/<t>/files.txt`
  (`git restore` tracked ones, delete new ones); `git status` shows only the docs edits below.
- [ ] **Step 2: Log row.** `| 2026-11-DD | <commit or —> | <ctry> / <intro> scored | <ctry> / <intro> SSIM | <ctry> / <intro> IoU | <what changed, verdict counts, overlap before → after, readout moves, adopted or not, link to the note> |`
- [ ] **Step 3: Owning note** updated as above.
- [ ] **Step 4: Full gate.** `mise run check`. Expected: `[gate] PASS`.
- [ ] **Step 5: Commit.** Adopted: `fix(<crate>): <what now draws>`, staging the fix, its test and
  the docs; body gives the cause, the evidence (verdict counts, overlap, readout moves) and what was
  rejected. Not adopted: `docs(parity): record the <track> aircraft attempt`, docs only.
- [ ] **Step 6 (adopted only): New baseline.** Copy the gate's render, report, IoU and readouts over
  `build/scratch/baseline/<film>/`, so the next fix is measured against this one.

### Task 8: Round 2 (per track not adopted in round 1)

- [ ] **Step 1:** Stop the track if it already had two rounds, or if round 1 ended *finding only*
  for want of an undecoded rule (another round cannot supply it).
- [ ] **Step 2:** Recreate its scratch worktree clean (`git -C <W> status` shows nothing; if not,
  `git -C <W> checkout -- .`), copy this worktree's `build/scratch/<t>/` back into it as
  `build/scratch/<t>-round1/`, then dispatch the same brief with one more paragraph: round 1's
  **Claim**, the gate it failed and the numbers, "round 1's diagnosis and instrumentation patch are
  in `build/scratch/<t>-round1/`", and "do not repeat these: <Ruled out list>".
- [ ] **Step 3:** Tasks 3 to 7 again.

### Task 9: Close

- [ ] **Step 0: Primary checkout untouched.** `git -C E:/git/stunt-reel status --short`. Expected:
  empty, as at the start (branch `fix/venv-ownership-marker`, clean).
- [ ] **Step 1: Reap dry run.** From `E:\git\stunt-reel`: `mise run reap`. Expected: exactly the two
  scratch worktrees (`diag/aircraft-a`, `diag/aircraft-b`). Anything else listed: ask the user
  before step 2.
- [ ] **Step 2: Reap.** `mise run reap -- --yes`. Expected: both removed, branches deleted.
- [ ] **Step 3: Handoff.** Update the spec's Status line with the outcome per track (adopted
  commits, or where each finding is recorded); commit as `docs(process): close the aircraft render plan`.
- [ ] **Step 4: Full gate and push.** `mise run check`, then `git push -u origin fix/aircraft-render`.
  A PR only if the user asks.
