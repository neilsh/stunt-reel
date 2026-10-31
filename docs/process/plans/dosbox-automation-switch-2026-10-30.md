# Switch Capture From DOSBox-X To dosbox-automation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** `capture-ref`, the probes, `make-all` and `play` run on dosbox-automation 0.85.1, DOSBox-X and `dosbox-x-mcp-server` are no longer pinned or referenced by code, and what is specific to DOSBox-X lives in one legacy research note.

**Why:** [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) §§ 2 to 4.3. Runs are bit-repeatable, frames are addressed by emulated frame number (video frame *j* is frame 1200 + *j*), a page and its working palette read in one Lua step, and 24 runs go in parallel.

**Architecture:** dosbox-automation cannot pause or step the guest, so the halt-at-a-trap session is replaced by a deterministic **plan, then run** model. A run boots the film from a staged mount, and a generated Lua script records what the plan asks for. Pass 1 is a trace (`film_tick`, `global_tick`, page-changed flag per frame, plus any pointers a probe needs). Python reads the trace, picks frames, and pass 2 dumps pages, palettes and memory ranges at exactly those frames (at most 40 samples per run, `MAX_DUMPS`: the output store holds about 15 MB, but 90 page dumps ran out of Lua memory live). Validated 2026-10-30: trace and dump passes over 2,101 frames of `CTRY.FLM` gave identical per-frame clocks and page-changed flags, and a conf plus mount staged under the data root boots while one under the checkout is refused by the mount policy.

**Tech Stack:** Python 3.12, `urllib` REST with a bearer token, Lua on the emulation thread, ffmpeg only for the optional AVI check.

**Spec:** this plan is the design. Background: [ADR 0021](../../adr/0021-capture-chooses-its-control-port.md) (superseded by Task 7), [ADR 0022](../../adr/0022-captures-are-add-only-beside-a-read-only-corpus.md), [ADR 0024](../../adr/0024-captures-are-filed-by-film-then-kind.md).

## Global Constraints

- Offline tests only: nothing under `tests/` starts an emulator or reads `corpus/`. A `MockEmulator` returns canned trace and dump output (AGENTS.md directive 1).
- Stage the conf and the mount **together under the data root** (`<data>/stage/<run>/`); a mount under the checkout is refused ("outside allowed directories"). Remove the stage after the run.
- The Lua instruction limit forbids per-byte loops: use `raw:gsub(".", H)` for hex, compare pages as strings, and diff offline in Python. Prefix string outputs with a letter, because `dosbox.output` coerces numeric-looking strings.
- Keep a run to at most 40 page samples (`MAX_DUMPS`; 90 ran out of Lua memory live) and 15 MB of output. Chunk longer plans into runs.
- `DS` is `0x0F46` here (image paragraph `0x01F5` + `0x0D51`), not `0x1575`. Derive it from the constants, do not hard-code it twice.
- Do not kill running DOSBox-X processes until Task 7. Captures never serialise: each run takes its own web-server port and a fresh random bearer token passed as `DOSBOX_API_TOKEN`.
- Run `mise run check-py` while iterating and `mise run check` once before each commit. Stage files by name, never `corpus/`. Conventional Commits with a why body, `mise run check passes.`, and the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Append-only `research/parity/log.md`; plans and handoffs stay in `docs/` or `research/`, not in memory.

## Review Focus

1. A page read at a frame boundary can be torn (10 of 97 INTRO samples). The tear rule must be a documented scorer or retry rule, not silent.
2. The DAC during a fade is *low half new, high half previous*. A capture that records the working palette alone scores fade frames against the wrong colours.
3. Existing references (`vault-ctry/001`, `vault-intro/001`) came from DOSBox-X: a different DAC expansion (`(v<<2)|(v>>4)` against `round(v*255/63)`) and a different page-to-clock lag. Scores move; the move is recorded, not hidden.
4. Port and token handling: ports are chosen by binding port 0 and releasing it, so allow a retry on a lost race.

---

## File Structure

- Create `python/stunt_reel/tac/automation.py`: REST client (info, script load/start/status, cycles, shutdown) and the `DosboxAutomation` emulator process wrapper.
- Create `python/stunt_reel/tac/luagen.py`: the Lua generator for boot-and-keys, trace and dump passes.
- Create `python/stunt_reel/tac/plan.py`: `TracePlan`, `DumpPlan`, the decoded `Trace` and `Dump`, and the chunking rule.
- Modify `python/stunt_reel/tac/staging.py`: stage under the data root, write the dosbox-automation conf.
- Modify `python/stunt_reel/tac/session.py` and `emulator.py`: replace `run_session` and the halted `Page` with `run_plan`; keep `Profile`, errors and the event types that still apply.
- Delete `python/stunt_reel/tac/transport.py` (listener, framing, debugger commands), `vsync.py`, `client.py` once their remaining callers move; keep `bda.py` only if the keys are still needed (the Lua `dosbox.key` takes names, so likely delete).
- Modify `python/stunt_reel/tac/framebuffer.py` (`capture`), `python/scripts/capture_playone_reference.py`, `python/scripts/probe_playone_light.py`, `python/stunt_reel/tac/makeone.py`, `python/scripts/make_all.py`, `python/stunt_reel/batch_stages.py`.
- Delete `python/scripts/ensure_dosbox.py`, `tests/test_ensure_dosbox.py`, `tools/dosbox/` confs for DOSBox-X (replace with `tools/dosbox/` automation confs for `play`), the `dosbox-x` and `dosbox-x-mcp-server` pins and the `ensure-dosbox` and `mcp` tasks in `mise.toml`.
- Create `research/playone-exe/dosbox-x-legacy.md`; rewrite `research/playone-exe/capture.md` and `capture-speed.md` for the new harness.
- Create `docs/adr/0025-capture-runs-are-plans-not-sessions.md`; mark ADR 0021 superseded.
- Tests: `tests/test_tac_luagen.py`, `tests/test_tac_plan.py`, `tests/test_tac_automation.py`, and a rewrite of `tests/test_tac_capture_session.py`, `tests/test_tac_adversarial.py`, `tests/test_tac_staging.py`, `tests/test_tac_makeone.py`; delete `tests/test_tac_transport_framing.py`, `tests/test_tac_video_mode.py`, `tests/test_ensure_dosbox.py` with their subjects.

---

## Task 1: Preserve the DOSBox-X facts

- [x] **1.1** Create `research/playone-exe/dosbox-x-legacy.md` from the DOSBox-X content of `capture.md`, `capture-speed.md`, ADR 0021 and `docs/development.md` § 2: the `mcp_server` dial-out, the debugger command table, `BP 0D51:0C5E`, port 0 binding, the `dacexpand` formula, the `DS = 0x1575` constants, measured speeds and the caveats. State at the top that the harness is retired, which commit last had it, and that the `0C5E` target is the `ret` of `set_palette` ([`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.3).
- [x] **1.2** Add a pointer from `research/README.md` and `static-tooling.md`. Run `mise run check-py` (the doc-anchor tests check `# [MEM-*]` tokens: move none of them).
- [x] **1.3** Commit: `docs(research): move the retired DOSBox-X harness into its own note`.

## Task 2: Staging and conf under the data root

- [x] **2.1** Write the failing tests in `tests/test_tac_staging.py`: the stage directory is `<data>/stage/<film>-<label>/`, the conf and the mount are inside it, the conf has `webserver_enabled`, `webserver_port`, `core = normal`, `cpu_cycles = 7000` (370 render loops against 369; § 4.1), `machine = svga_s3`, `sbtype = sb16`, an `[autoexec]` that mounts and runs `playone.exe`, and removal deletes the whole directory. (Amended 2026-10-31: the committed profiles are `core = dynamic` at 45,000 cycles for `capture` and `play`, and `max` for `archive`; see the Rulings.)
- [x] **2.2** Change `staging.py` and `parity_layout.stage_dir` to the new location. `parity_layout.py` stays the only place with the path literal.
- [x] **2.3** Confirm the existing film and archive copying (`MAKEONE_FILES`, the sibling `.ALL`) is unchanged.
- [x] **2.4** Commit.

## Task 3: Lua generator and the automation emulator

- [x] **3.1** Tests for `luagen.py` as string checks: the boot section waits to the start frame then presses the film keys with 20-frame gaps and 5-frame holds; the trace section reads `DS:0x4896` and `DS:0x22B8` and compares `A000` as strings; the dump section hex-encodes with `gsub(".", H)`; outputs are prefixed with a letter; no per-byte loop over 64 KB exists.
- [x] **3.2** Implement `luagen.py` from the proven `scan.py` and `inv7_run.py` in the spike notes (the 'snippet' in `capture-dosbox-automation.md` § 6).
- [x] **3.3** Tests for `automation.py` against a fake HTTP server: token header, `script/load` as `text/plain`, polling `script/status` until `completed` or `error`, the error text carried into the exception, shutdown on teardown, and port-race retry.
- [x] **3.4** Implement the client and `DosboxAutomation(Emulator)` (`EmulatorUnavailable` when the executable is not found, `GuestTimeout` for a run that exceeds its budget).
- [x] **3.5** Add a `MockEmulator` that returns canned trace and dump output, and a `[dosbox-automation]` mise tool entry check (the pin already exists in `mise.toml`). (Amended 2026-10-31: the check is `test_mise_pins_dosbox_automation_with_a_checksum` in `tests/test_tac_automation.py`.)
- [x] **3.6** Commit.

## Task 4: Plans replace sessions

- [x] **4.1** Tests for `plan.py`: decoding a trace string (`tick:global:changed,...`), chunking a frame list to at most `MAX_DUMPS` (40) per run, and mapping dumps back to frames.
- [x] **4.2** Implement `run_plan(film, trace_plan, pick, dump_plan_builder)`. `pick` is a Python function over the trace that returns the frames to dump, so the sampler's old adaptive logic (new film tick, end of film after N holds, requested ticks) moves there.
- [x] **4.3** Rewrite `framebuffer.capture` and `capture_playone_reference.py` on it. Keep `meta.json` and the `frames/` layout (ADR 0022 and 0024).
- [x] **4.4** Rewrite `probe_playone_light.py` (the work segment pointer and the lighting words are read into the trace, then the dump reads the ranges).
- [x] **4.5** Update `test_tac_capture_session.py` and `test_tac_adversarial.py` to the mock emulator.
- [x] **4.6** Delete `transport.py`, `vsync.py`, `client.py`, `bda.py` and the framing and video-mode tests when nothing imports them; keep `streamer.py` only if its decoders still apply (check callers first). (Amended 2026-10-31: only the live DOSBox-X I/O was deleted; the offline streamer stack stays, see the Rulings, `[dead code kept]`.)
- [x] **4.7** Commit.

## Task 5: make-all and play

- [x] **5.1** Port `makeone.py`: end of run is the video mode back to text. Read it from `GET /api/v1/video/frame/info` or `video/text`, polled every 2 s, with the 600 s timeout.
- [x] **5.2** Replace the `play` task with a dosbox-automation conf (interactive, no webserver needed). Remove `play_ctry.bat` if it only launched DOSBox-X.
- [x] **5.3** Update `batch_stages.py` and its tests; the batch driver runs one emulator at a time unless the plan allows parallel chunks.
- [x] **5.4** Commit.

## Task 6: Tear rule, DAC model, re-baseline

- [x] **6.1** (Done 2026-10-31 by skipping, without video: the trace flags a page torn between the two composed pages and `pick` takes the next frame; see `method.md` § 3.1 and `capture-dosbox-automation.md` § 4.5.) Capture `CTRY.FLM` and `INTRO.FLM` with the new path plus a video capture, and measure the tear rate against the lossless AVI at matched frames. Write the rule (accept a page whose rows match some video frame in *f-2* to *f+4*, else retry at *f+1*) into `research/parity/method.md` and implement it in `pick`.
- [x] **6.2** (Done 2026-10-31 by skipping: the DAC is `low = W(f-1)`, `high = W(f-2)`, so `pick` skips the two frames of each palette step and every kept page's working palette is its DAC; rebuilding the DAC waits for a film that needs those frames. Earlier note, partly done: the fade model is written in `method.md` § 3.1, but `framebuffer.py` still records the working palette alone, `"palette_source": "working"`.) Record the DAC for each page: the working palette plus the fade model (low half new, high half previous) for frames where the working palette differs from the previous frame's. Decide the palette-lead question left open in § 4.3 by testing the working palette at *f-2*.
- [x] **6.3** (Done 2026-10-31: `vault-ctry/frames/004` and `vault-intro/frames/004`; see the `parity/log.md` row.) Capture the new references as new add-only directories, edit `references.toml` in a reviewed commit with the new hashes, rescore, and append a `parity/log.md` row stating the move against the DOSBox-X references.
- [x] **6.4** Commit.

## Task 7: Remove DOSBox-X

- [x] **7.1** Delete the `dosbox-x` and `dosbox-x-mcp-server` entries, the `ensure-dosbox` and `mcp` tasks and `renovate.jsonc` rules from `mise.toml` and `.github/renovate.jsonc`.
- [x] **7.2** Delete `python/scripts/ensure_dosbox.py`, its test, and the DOSBox-X confs under `tools/dosbox/`; rewrite `tools/dosbox/README.md`.
- [x] **7.3** Rewrite `docs/development.md` §§ 1, 2 and the tables, `README.md`, `AGENTS.md` (the routing table row for `capture.md`), `GLOSSARY.md`, `docs/SPEC.md`, `docs/harness-setup.md`, `docs/ARCHITECTURE.md` and `NOTICE.md` mentions. Run `rg -i dosbox-x` over everything except `research/` and the legacy note; the only hits left are the legacy pointers. (Amended 2026-10-31: the remaining hits are retirement pointers and history: `emulator.py`, `batch_stages.py`, the ADRs and older plans.)
- [x] **7.4** Write `docs/adr/0025-capture-runs-are-plans-not-sessions.md` and mark ADR 0021 superseded; update `doc_anchors.py` if any anchor moves.
- [ ] **7.5** Run `mise run check` (passes, 2026-10-31), then reap the old DOSBox-X processes by hand (the user's call; still open).
- [x] **7.6** Commit.

## Open Questions

1. The tear rule (Task 6.1) and the palette lead (6.2) are the two measurements that can change the capture format.
2. Whether `mount_allowed_bases` in a primary config would let the stage live elsewhere. Not needed while the stage sits under the data root.
3. Linux and macOS capture is lost: dosbox-automation ships a Windows zip only, and capture is local-only and not in CI.

## Status and Handoff (2026-10-31)

Tasks 1 to 5 are done on branch `worktree-dosbox-automation-spike`, and Task 7 except 7.5's process reaping, which is the user's. Task 6 is partly done (6.3 and 6.4 done, 6.2's fade model written down but not applied, 6.1 open). The live findings are in [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4 and [`driving.md`](../../../research/makeone-exe/driving.md) § 9.

Verified live: `capture-ref` on `CTRY.FLM` (113 frames at 7,000 cycles one pass at a time; 121 frames in 112 s at 45,000 with parallel passes) and `INTRO.FLM` (315 frames, 17 min before passes ran in parallel); `make-all` on `747LAND.FLM` on both CPU profiles, byte-identical to the DOSBox-X archive. `probe-light` on `CTRY.FLM` (seven samples in 111 s). `mise run play` (640x480 window, key script done in 21 s, exit 0 and stage removed after the window closed). Scored with `stuntreel parity`: new captures score as well as the DOSBox-X references or better on both films (§ 4.4). Not run live: the batch survey. A dynamic-core sweep matched the normal core's rate within 1% at 40% less host CPU, so capture moved to the dynamic core.

Rulings made while executing (cost if wrong in brackets):

- The stage is `<data>/stage/<film>-<label>/{mount/, dosbox.conf}` and the conf is rendered per run at launch, because the port is only known then and the emulator refuses a mount under the checkout. [one layout change]
- The offline streamer stack (`streamer.py`, `client.py`, `bda.py`, `vsync.py`, `Transport`, `MockTransport`) stays, because the Rust oracle cites `streamer.py` as its reference model; only the live DOSBox-X I/O, `session.py` and `ensure_dosbox.py` were deleted. [dead code kept]
- The trace stops after the film clock holds for 30 frames (`end_hold`), so the frame window is only a cap. [a film with a long pause mid-film is cut short]
- `MAX_DUMPS` is 40, not 90: 90 pages ran out of Lua memory live. [more replay passes]
- A dumped page carries the tick its own pass read; a frame more than `MAX_SKEW_TICKS` (2) from the trace pass is a `PlanDivergence`. `COUNT.FLM` replays differ by a tick; `CTRY.FLM` replays do not. [a capture with a stride under 5 ticks could hold two pages of one tick]
- `make-all` runs MAKEONE on the `archive` CPU profile (dynamic core, `cpu_cycles = max`): 41 s against 227 s, same archive bytes. [a film whose archive differs between profiles]
- Every run's window is `window_size = 640x480`.
- Every script parks the mouse cursor bottom-left after the dialog keys, over the button bar, so it no longer sits in the 3D view of captured pages. [captures before 2026-10-31 differ by the cursor]
- Capture and `play` run the dynamic core at 45,000 cycles, not the normal core at 7,000 (the dynamic core costs 0.23 of a host core against 0.39 at the same rate): the render rate saturates there (99% of emulated frames draw a new page against 46%). 7,000 only matched DOSBox-X's loop count. [captures no longer match the DOSBox-X references' pacing; they are being replaced]
- Dump passes run up to eight at once, split evenly, each launch with its own `dosbox-<port>.conf`: one pass at a time put `INTRO.FLM` past the batch's 900 s timeout. [four emulators' memory and CPU during a capture]
- The tear rule and fade model are applied in `pick` by skipping (2026-10-31, [`stack-review-and-tear-palette-2026-10-31.md`](stack-review-and-tear-palette-2026-10-31.md)); the video rule was replaced by a test against the game's two composed pages. [a film that does not double-buffer through `DS:0x22CA`/`0x22CC` reads as never torn]
- `tools/dosbox/dosbox-utils.conf` stays as a by-hand profile, unverified on dosbox-automation; `capture.md` and `capture-speed.md` carry a historical banner rather than a rewrite.
- `KNOWN_CAPTURE_STALLS` is unchanged pending a re-survey.

Next:

1. `INTRO.FLM` before film tick 769: the new reference covers it and the render scores about 0 SSIM on all 70 frames there (`parity/log.md`, 2026-10-31). Find what the opening shows and why the render misses it.
2. Patch #3: build patched and unpatched `PLAYONE.EXE`, `STUNT.EXE` and `MAKEONE.EXE` trees from `corpus/patches/`, find the patched build's offsets, and test `COUNT.FLM` and the other stalled films on it. A separate piece of work.
3. Re-survey the batch on dosbox-automation (timeouts, the stall list).
4. 7.5: the stale `dosbox-x.exe` processes on the machine are the user's to end.
