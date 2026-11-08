# Stack Review Fixes and the Tear/Palette Skip Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix what the 2026-10-31 two-axis review found on PRs #28 and #29, each on its own layer, and add a third
stacked PR that makes capture plans skip torn pages (6.1) and pages shown during a palette step (6.2).

**Architecture:** Three layers of stack #30: `(main) <- worktree-dosbox-automation-spike (#28) <- claude/si-patch3-3dddea
(#29) <- claude/tear-palette-skip (new)`. Review fixes land on the layer that owns them, then `gh stack rebase --upstack`.
The new layer adds two bits to the trace pass (torn page, working palette changed), and `pick` skips any frame that is
torn or whose DAC still lags the working palette; dump passes refuse a page that fails the same test.

**Tech Stack:** Python 3 (`python/stunt_reel/tac/`), generated Lua run by dosbox-automation 0.85.1, pytest, `gh stack`.

**Spec:**
- Review findings: the Standards and Spec reports of 2026-10-31, restated as the table below (the source of truth here).
- 6.1/6.2: [`tear-palette-investigation-2026-10-31.md`](tear-palette-investigation-2026-10-31.md) §§ 1.3 and 2.4.
- Plan items 6.1/6.2 in [`dosbox-automation-switch-2026-10-30.md`](dosbox-automation-switch-2026-10-30.md).

| # | Layer | Finding | Disposition |
|---|---|---|---|
| R1 | #28 | `play.py` has two identical `except` arms (`EmulatorUnavailable` is a `RuntimeError`) | Task 1 |
| R2 | #28 | `makeone.film_selection_names` shares a name with `playone.film_selection_names` but sends other keys | Task 1 |
| R3 | #28 | `make_all.run` passes `launch` through `**extra`, typed `Callable[..., Any]` | Task 1 |
| R4 | #28 | `capture-dosbox-automation.md:97` "up to four at once" against `DEFAULT_PARALLEL_PASSES = 8` | Task 2 |
| R5 | #28 | `AGENTS.md` doc table omits `dosbox-x-legacy.md` | Task 2 |
| R6 | #28 | Switch plan: 2.1 text says `normal`/7000, 3.5 ticked without a mise pin check, 4.6 ticked though the streamer stack stays, 7.3 overclaims | Task 2 |
| R7 | #29 | `layout: PlayoneLayout = UNPATCHED` defaults on `luagen.script`, `plan.run_plan`, `framebuffer.capture` | Task 3 |
| R8 | #29 | probe reads `playone.AUTOMATION_DS`, `framebuffer.py` docstring cites `DS:0x4896` | Task 3 |
| R9 | #29 | `patch3.md` § 3 says the harness ran `core = normal` | Task 4 |
| R10 | #29 | `patch3.md` not in `AGENTS.md` table; archives and batch runs do not name their build | Task 4 |

## Global Constraints

- Stage files by name; never `git add -A`/`git commit -a`; never anything under `corpus/`.
- Nothing writes `corpus/`; captures are add-only (`captures/<film>/frames/<run>`, ADR 0022/0024); `references.toml` changes only by a reviewed commit.
- `research/parity/log.md` is append-only with LF line endings.
- Conventional Commit subject, a why-body, then `mise run check passes.` (or name what ran), then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `mise run check` before every commit; `mise run check-py` while iterating.
- Lua never loops per byte over a page (instruction limit); every Lua string output starts with a letter.
- Never force-push; history already pushed (e.g. commit `3e7c6fc`'s missing closer) stays as it is.
- Subagents, if any, run on Sonnet or Opus.
- Evidentiary tiers stay out of headings; research notes end with **Ruled out** and **Open questions**.

## Review Focus

1. A film that does not double-buffer through `DS:0x22CA`/`0x22CC`: no band is "only A" and "only B", so nothing reads as torn and capture proceeds as today. Test in Task 6.
2. Every changed frame unusable (all torn, or a long fade over a static scene): capture must fail with a message naming the counts, not write an empty capture. Test in Task 8.
3. Wrong `composed_pages` for `PATCH3` (they are inferred, offset −0x67A): the torn rate reads near 0% or near 100%. Live check in Task 9.
4. Old two-state traces (`...:0`/`...:1`) still decode, so mock fixtures and the probe keep working. Existing tests in Task 6.
5. A palette step at the trace's first frame: frame `first` has no f−1 in the trace and must count as usable on that side. Test in Task 7.

## Rulings Made While Planning

- R1: `play.py` keeps its hand-rolled `DosboxAutomation` start/stop, because `automation.launched()` exposes no `wait()` for a person closing the window — cost if wrong: one helper later.
- Reviewer smell "broad `except Exception` in `make_all`": kept; it is documented control flow so a good archive survives a failed shutdown.
- Reviewer smell "`UNPATCHED` duplicates module constants": not a defect; `UNPATCHED` references the constants rather than copying values, and the offline streamer and Rust oracle cite them.
- `emulator.py:3` and `batch_stages.py:47` mention DOSBox-X as history (retirement pointer; the survey that recorded the stalls); 7.3's text is amended rather than the code.
- #29's `KNOWN_CAPTURE_STALLS` edit stays: `patch3.md` § 3 is a live capture of those films under the new harness. The pending batch re-survey goes to Open questions.
- `PATCH3` offsets keep `[Supported Inference]`; Task 9's patched capture adds the page-pointer check as further evidence.
- 6.2 takes the investigation's option (d), skipping, now; option (b), rebuilding the DAC from W(f−1)/W(f−2), waits for a film that needs fade frames.
- 6.1 replaces `method.md` § 3.1's video rule (match a video frame in f−2..f+4) with the buffer test; the video rule needs an AVI per film and decodes ambiguously (investigation § 1.2).
- If #28 or #29 is merged before a layer's task runs, that layer's fixes go on a fresh branch from `main` as their own PR instead.

---

### Task 0: Bring the stack in line

`claude/si-patch3-3dddea` (`d436b11`) lacks #28's `732443e`, `7df5ce5`, `2edc8ee`.

- [ ] **Step 1:** `gh pr view 28 --json state` and `gh pr view 29 --json state`. Expected: both `OPEN` (else apply the last ruling above).
- [ ] **Step 2:** From the #29 branch: `gh stack rebase --upstack`, then `gh stack push`. Expected: `gh stack view --json` shows `needsRebase: false` on every branch. On exit 3, resolve, `git add <files>`, `gh stack rebase --continue`.

### Task 1: #28 code smells (R1–R3)

**Files:**
- Modify: `python/scripts/play.py:48-53`, `python/stunt_reel/tac/makeone.py:67,115-151`, `python/scripts/make_all.py:72-101`
- Test: `tests/test_tac_makeone.py`, the make-all script test (`rg -l "make_all" tests`)

**Interfaces:**
- Produces: `makeone.film_requester_names(name: str) -> list[str]` (renamed from `film_selection_names`; same keys: letter, Enter).
- Produces: `makeone.make_all(..., launch: Launch | None = None, ...)` where `Launch = Callable[[staging.StagedMount], AbstractContextManager[MakeOneClient]]` and `None` means `_launch`.
- Produces: `make_all.run(args, launch: makeone.Launch | None = None) -> int` passing `launch=launch` directly.

- [ ] **Step 1:** In `play.py`, delete the `except EmulatorUnavailable` arm and drop the now-unused import; the remaining arm already catches it.
- [ ] **Step 2:** Rename `makeone.film_selection_names` to `film_requester_names` (MAKEONE's file requester), updating every caller and test (`rg film_selection_names python tests`; leave `playone.film_selection_names` alone).
- [ ] **Step 3:** Add the `Launch` alias to `makeone.py` (`__all__` too), make `make_all`'s `launch` `Launch | None = None` and resolve it to `_launch` inside; in `make_all.run` drop `extra` and pass `launch=launch`.
- [ ] **Step 4:** `mise run check-py`. Expected: PASS.
- [ ] **Step 5:** Commit on `worktree-dosbox-automation-spike`: `refactor(tac): one except arm in play, a requester name for MAKEONE keys, a typed make-all launch` (body: the review; that `launched()` lacks `wait()`).

### Task 2: #28 docs and the switch plan (R4–R6)

**Files:**
- Modify: `research/playone-exe/capture-dosbox-automation.md:97`, `AGENTS.md` (Binary Disassembly row), `docs/process/plans/dosbox-automation-switch-2026-10-30.md` (2.1, 3.5, 4.6, 7.3)
- Test: `tests/test_tac_staging.py`

- [ ] **Step 1: Write the failing test** `test_mise_pins_dosbox_automation`: load `mise.toml` with `tomllib`; assert `tools["github:dosbox-automation/dosbox-automation"]["version"] == "0.85.1"` and `== automation.PINNED_VERSION` if such a constant exists (`rg -n "0\.85\.1" python`); otherwise only the first assertion.
- [ ] **Step 2:** `mise run check-py`. Expected: PASS if the pin already holds (this pins it rather than drives code); a failure here means the pin moved, so stop.
- [ ] **Step 3:** Edit `capture-dosbox-automation.md:97`: "up to four at once (`DEFAULT_PARALLEL_PASSES`, since raised to eight; § 4.4)".
- [ ] **Step 4:** In `AGENTS.md`'s Binary Disassembly row, after the `capture.md` link, add `[`dosbox-x-legacy.md`](research/playone-exe/dosbox-x-legacy.md) (what the DOSBox-X harness established)`.
- [ ] **Step 5:** In the switch plan, add "(Amended 2026-10-31: …)" notes: 2.1 says the committed profile is `core = dynamic` at 45,000 cycles (capture, play) and `max` (archive), per the Rulings; 3.5 names `test_mise_pins_dosbox_automation`; 4.6 says only the live DOSBox-X I/O was deleted and the streamer stack stays (Rulings, `[dead code kept]`); 7.3 says the remaining hits are retirement pointers and history (`emulator.py`, `batch_stages.py`, ADRs, older plans).
- [ ] **Step 6:** `mise run check`. Expected: all steps PASS.
- [ ] **Step 7:** Commit: `docs(plan): true up the switch plan's ticked items and route the legacy note`; then `gh stack rebase --upstack` and `gh stack push`.

### Task 3: #29 explicit layout (R7–R8)

**Files:**
- Modify: `python/stunt_reel/tac/luagen.py` (`script`), `python/stunt_reel/tac/plan.py` (`run_plan`), `python/stunt_reel/tac/framebuffer.py` (`capture`, module docstring), `python/scripts/probe_playone_light.py`, every caller and test that relied on the default
- Test: `tests/test_tac_luagen.py`, `tests/test_tac_plan.py`, `tests/test_tac_capture.py`

**Interfaces:**
- Produces: `script(*, keys, first, last, layout: PlayoneLayout, dump_frames=(), ranges=(), words=(), end_hold=None) -> str`; `run_plan(..., layout: PlayoneLayout, ...)`; `capture(..., layout: PlayoneLayout, ...)`, with no defaults for `layout`.

- [ ] **Step 1: Write the failing test** `test_every_capture_entry_point_requires_a_layout`, parametrized over `luagen.script`, `plan.run_plan`, `framebuffer.capture`: `inspect.signature(fn).parameters["layout"].default is inspect.Parameter.empty`. (A `pytest.raises(TypeError)` call would pass on any other missing argument.)
- [ ] **Step 2:** `mise run check-py`. Expected: three FAIL.
- [ ] **Step 3:** Drop the three defaults; pass `layout=` at every call site (`rg -n "script\(|run_plan\(|framebuffer.capture\(|capture\(" python tests`); tests pass `playone.UNPATCHED`. In the probe, use `layout.ds` in place of `playone.AUTOMATION_DS`. In the `framebuffer.py` docstring, say "the layout's film clock" instead of `DS:0x4896`.
- [ ] **Step 4:** `mise run check-py`. Expected: PASS.
- [ ] **Step 5:** Commit on `claude/si-patch3-3dddea`: `fix(tac): make every capture name its PLAYONE build` (body: a forgotten layout silently read Patch #3 at unpatched offsets).

### Task 4: #29 notes (R9–R10)

**Files:**
- Modify: `research/playone-exe/patch3.md` (§ 3, Open questions), `AGENTS.md` (Binary Disassembly row)

- [ ] **Step 1:** Find which core the § 3 runs used: `git log --format="%h %ad" -S"core = dynamic" -- python/stunt_reel/tac/staging.py` against the runs' dates in § 3. Correct the bracket to the profile actually used (expected `core = dynamic`, 45,000 cycles for `PLAYONE`).
- [ ] **Step 2:** In Open questions add: (1) the batch survey has no `--game-root`, so it cannot run the patched build, and the stall list awaits its re-survey; (2) `captures/<film>/archives/<run>` and `frames/<run>` record the build only in `meta.json`, so a run name says nothing about the build.
- [ ] **Step 3:** In `AGENTS.md`'s Binary Disassembly row, add `[`patch3.md`](research/playone-exe/patch3.md) (Patch #3 builds and their offsets)`.
- [ ] **Step 4:** `mise run check`. Expected: PASS.
- [ ] **Step 5:** Commit: `docs(research): correct the Patch #3 run profile and list what the store does not record`; then `gh stack rebase --upstack` (no-op until layer 3 exists) and `gh stack push`.

### Task 5: Start layer 3 and name the composed pages

**Files:**
- Create: branch `claude/tear-palette-skip` via `gh stack add claude/tear-palette-skip` (from the #29 branch)
- Add: this plan and `docs/process/plans/tear-palette-investigation-2026-10-31.md`
- Modify: `python/stunt_reel/tac/playone.py` (`PlayoneLayout`, `UNPATCHED`, `PATCH3`), `research/playone-exe/memory-map.md` (the DGROUP table)
- Test: the layout tests (`rg -l "PATCH3" tests`)

**Interfaces:**
- Produces: `PlayoneLayout.composed_pages: tuple[int, int]`, the DS offsets of the two words holding the composed pages' segments. `UNPATCHED.composed_pages == (0x22CA, 0x22CC)`; `PATCH3.composed_pages == (0x22CA - 0x67A, 0x22CC - 0x67A)`, inferred from the uniform −0x67A shift and checked live in Task 9.

- [ ] **Step 1:** `gh stack add claude/tear-palette-skip`; commit the plan and the investigation: `docs(plan): plan the review fixes and the tear and palette skip`.
- [ ] **Step 2: Write the failing test** `test_layouts_name_both_composed_pages` with the two equalities above.
- [ ] **Step 3:** `mise run check-py`. Expected: FAIL (`composed_pages` missing).
- [ ] **Step 4:** Add the field and values; in `memory-map.md` add rows for `0x22CA`/`0x22CC` (segment words of the two composed pages, swapped every render; rows 0–191 of A000 equal one after a finished copy) if absent, citing the investigation § 1.1.
- [ ] **Step 5:** `mise run check-py`. Expected: PASS. Commit: `feat(tac): name where each PLAYONE build keeps its two composed pages`.

### Task 6: The trace mask

**Files:**
- Modify: `python/stunt_reel/tac/luagen.py` (`script`, docstring), `python/stunt_reel/tac/plan.py` (`TraceEntry`, `decode_trace`)
- Test: `tests/test_tac_luagen.py`, `tests/test_tac_plan.py`

**Interfaces:**
- Produces: `luagen.TRACE_CHANGED = 1`, `TRACE_TORN = 2`, `TRACE_PALETTE = 4` (in `__all__`): the last trace field is their sum.
- Produces: `TraceEntry(film_tick, global_tick, words, changed, torn: bool = False, palette_changed: bool = False)`.

- [ ] **Step 1: Write the failing tests:**
  - `test_trace_decodes_the_flag_mask`: `decode_trace("x5:7:3,6:8:4", 1300)` gives entry 0 `changed and torn and not palette_changed`, entry 1 `palette_changed and not changed and not torn`.
  - `test_trace_refuses_a_mask_above_seven`: `"x5:7:8"` raises `PlanError`.
  - `test_trace_reads_both_composed_pages_and_the_palette`: `script(..., layout=UNPATCHED)` contains `mem_read_word(DS, 0x22CA)`, `mem_read_word(DS, 0x22CC)` and `f"mem_read(DS, 0x{UNPATCHED.working_palette:X}, 768)"` outside the dump block (the trace reads it every frame).
  - `test_tear_check_compares_bands`: the script contains `2560` and `61440` and no `string.byte`/`:byte(`.
- [ ] **Step 2:** `mise run check-py`. Expected: these four FAIL.
- [ ] **Step 3:** In `decode_trace` accept a last field `0..7` and fill the three flags. In `script`, before the loop read `ppal` once; per frame compute `torn` and `pc` and emit `t .. ":" .. g{extra} .. ":" .. mask`. The tear test, matching the measured draft (bands only in A and bands only in B):

```lua
local ROWS, BAND = 61440, 2560  -- rows 0..191 (192..199 are the button bar, drawn on A000)
local function torn(pg)
  local a = dosbox.mem_read(dosbox.mem_read_word(DS, 0x22CA), 0, ROWS)
  local b = dosbox.mem_read(dosbox.mem_read_word(DS, 0x22CC), 0, ROWS)
  local top = pg:sub(1, ROWS)
  if top == a or top == b then return false end
  local onlyA, onlyB = false, false
  for o = 1, ROWS, BAND do
    local s = top:sub(o, o + BAND - 1)
    local ea, eb = s == a:sub(o, o + BAND - 1), s == b:sub(o, o + BAND - 1)
    if ea and not eb then onlyA = true elseif eb and not ea then onlyB = true end
  end
  return onlyA and onlyB
end
```

  The offsets come from `layout.composed_pages`; update the docstring's trace format.
- [ ] **Step 4:** `mise run check-py`. Expected: PASS, including the existing two-state trace tests (Review Focus 4).
- [ ] **Step 5:** Commit: `feat(tac): trace torn pages and palette steps per frame` (body: investigation § 1.1 and 2.1; the band size fits the instruction limit where 192 row compares did not).

### Task 7: Pick only usable frames, and refuse unusable dumps

**Files:**
- Modify: `python/stunt_reel/tac/plan.py` (`usable`, `pick_every`, `pick_ticks`, `run_plan.dump_pass`)
- Test: `tests/test_tac_plan.py`

**Interfaces:**
- Consumes: `TraceEntry.torn`, `TraceEntry.palette_changed` (Task 6).
- Produces: `plan.usable(trace: Trace, frame: int) -> bool`: false when *frame* is torn, or the working palette changed at *frame* or at *frame* − 1 (a frame before `trace.first` counts as unchanged). Rationale: the DAC shows `low = W(f−1)`, `high = W(f−2)` (investigation § 2.1), which equals W(f) only if neither step happened.

- [ ] **Step 1: Write the failing tests:**
  - `test_pick_every_skips_a_torn_frame_for_the_next_change`: frames with ticks 1,2,3, all changed, the second torn, stride 1 → picks frames 1 and 3.
  - `test_pick_every_skips_the_two_frames_of_a_palette_step`: changed frames c−1..c+2, palette step at c → picks c−1 and c+2 (stride 1).
  - `test_pick_ticks_moves_past_an_unusable_frame`: tick 10 first reached at a torn frame → the next usable frame is picked.
  - `test_a_palette_step_at_the_first_frame_spares_nothing_before_it`: step at `trace.first` → `usable(trace, first)` is False, `usable(trace, first + 2)` is True, no `IndexError`.
  - `test_a_dump_pass_that_reads_a_torn_page_diverges`: with the canned-runner pattern of `test_extra_ranges_shrink_each_pass_to_the_measured_byte_budget`, the dump pass's own trace marks a picked frame torn → `run_plan` raises `PlanDivergence` whose message names the frame.
- [ ] **Step 2:** `mise run check-py`. Expected: these five FAIL.
- [ ] **Step 3:** Implement `usable`; in `pick_every` and `pick_ticks` skip frames that are not usable (in `pick_ticks` a skipped frame does not consume a pending tick); in `dump_pass` after `_check_close` raise `PlanDivergence(f"dump pass read an unusable page at frame {f}: {own.entry(f)}")` for the first frame its own trace marks unusable.
- [ ] **Step 4:** `mise run check-py`. Expected: PASS.
- [ ] **Step 5:** Commit: `feat(tac): pick past torn pages and palette steps` (body: the retry-at-f+1 rule without video; option (d) of 6.2 and why (b) waits).

### Task 8: Diagnostics, an honest empty capture, and the notes

**Files:**
- Modify: `python/stunt_reel/tac/framebuffer.py` (`capture`), `research/parity/method.md` § 3.1, `research/playone-exe/capture-dosbox-automation.md` (new § 4.5), `research/playone-exe/palette-fade.md`, `docs/process/plans/dosbox-automation-switch-2026-10-30.md` (6.1, 6.2, Open questions)
- Test: `tests/test_tac_capture.py`

- [ ] **Step 1: Write the failing tests:**
  - `test_capture_records_torn_and_palette_counts`: a canned trace with 2 torn frames and 3 palette steps → `meta.json` diagnostics hold `"torn_frames": 2` and `"palette_steps": 3`.
  - `test_capture_with_no_usable_frame_says_why`: every changed frame torn → `capture` raises `plan.PlanError` whose message contains `torn` and the count, and no `meta.json` is written.
- [ ] **Step 2:** `mise run check-py`. Expected: both FAIL.
- [ ] **Step 3:** Implement both in `capture` (counts from `result.trace.entries`; the empty check before writing).
- [ ] **Step 4:** Docs. `method.md` § 3.1: the tear rule is now the buffer test with `pick` skipping, and the palette paragraph states the measured lag (low half f−1, high half f−2) and the skip. `capture-dosbox-automation.md` § 4.5: the investigation's tear table (§ 1.1) and fade result (§ 2.1, 2.2), tiers in body text, with its Open questions (rate versus cycles unswept; DAC lag measured on one CTRY fade only; other films' buffers unchecked). `palette-fade.md`: one paragraph on the DAC lag, linking § 4.5. Switch plan: tick 6.1 and 6.2 with "(Done 2026-10-31 by skipping; …)" and remove "[tears go unflagged]".
- [ ] **Step 5:** `mise run check`. Expected: PASS. Commit: `feat(capture): record tear and palette counts, and refuse a capture with nothing usable`, then `docs(research): the tear test and the DAC lag, measured` as a second commit.

### Task 9: Live check, recapture and promote

Live runs; nothing writes `corpus/`, new runs land as `captures/<film>/frames/005`.

- [ ] **Step 1:** `mise run capture-ref` (CTRY) and `mise run capture-ref -- --film corpus/stisldem/VAULT/INTRO.FLM`. Expected: no `instruction limit` or `PlanDivergence`; `meta.json` `torn_frames` near 66–71 (CTRY) and 127 (INTRO), the investigation's counts (§ 1.1).
- [ ] **Step 2:** Patched check: `mise run capture-ref -- --game-root <patched tree from mise run game-builds>` on CTRY. Expected: `torn_frames` between 2% and 6% of traced frames. Near 0% or near 100% means `PATCH3.composed_pages` is wrong: stop, record it in `patch3.md` Open questions, and do not promote anything patched.
- [ ] **Step 3:** Point `references.toml` at `005` in the working tree only and run `mise run parity -- --no-build`. Expected: CTRY SSIM ≥ 0.7808 and INTRO ≥ 0.5488 (the 004 row); torn picks of 004 (CTRY ticks at frames 1816, 1986) score higher on their ticks.
- [ ] **Step 4:** If Expected holds: pin both `capture_digest` sha256 values, append one LF row to `research/parity/log.md`, `mise run check`, commit `feat(parity): promote the tear-free captures to the references`. If not, restore `references.toml`, append the row anyway with the note, and record the finding in § 4.5.
- [ ] **Step 5:** `gh stack submit --auto`, then set the new PR's body with the `pr` skill template (Summary: the trace-mask diff sketch; Evidence: 004 vs 005 parity rows and torn counts; Merge Danger: two-way door, blast radius "captures").

## Status and Handoff (2026-10-31)

Tasks 0 to 8 are done and Task 9 ran; layer 3 is `claude/tear-palette-skip`. The live recaptures flagged exactly the investigation's counts (CTRY 66 torn of 1,908, INTRO 127 of 5,384), and a patched CTRY capture flagged 72 of 1,906, which confirms `PATCH3.composed_pages`. Against one render, `005` scores CTRY 0.7800 / INTRO 0.5444 where `004` scores 0.7808 / 0.5488, so the promotion gate failed and `references.toml` stays on `004` (`parity/log.md`; open question 9 of `capture-dosbox-automation.md`).

Rulings made while executing (cost if wrong in brackets):

- Task 0's rebase left conflict markers in one #29 commit; the commits were rebuilt on a detached head before anything was pushed. [none; caught before push]
- Task 2's pin test already existed (`test_mise_pins_dosbox_automation_with_a_checksum`), so 3.5's amendment names it and no test was added. [none]
- `test_no_per_byte_loop_over_a_page` forbade every `:sub(`; the band test needs slices, so it now forbids one-byte slices only. [a per-byte loop written another way slips past; the `for` regex still guards pages]
- `patch3.md` § 3 names the dynamic core, because `efb6009` is an ancestor of the branch the runs were made on. [the runs were older than the rebase]
- After the final review, a dump pass drops an unusable page instead of raising `PlanDivergence` (Task 7 said raise): a jitter film would otherwise rarely finish. [a capture silently has one page fewer; the progress line names it]
- Task 9 step 2's "near 100%" symptom cannot occur: wrong composed-page words make `torn()` always false, so only "near 0%" means wrong offsets. A `composed_matches` diagnostic that would catch it on any build was not added, since both known layouts are now checked live. [a future build with wrong words captures with tears unflagged]