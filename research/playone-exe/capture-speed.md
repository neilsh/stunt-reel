# `PLAYONE.EXE`: Capture Speed and DOSBox-X Configuration Experiments

> [!NOTE]
> **Historical.** These experiments were run on DOSBox-X; capture now runs on dosbox-automation ([ADR 0025](../../docs/adr/0025-capture-runs-are-plans-not-sessions.md)).

The harness is in [`capture.md`](capture.md); a frame-locked video alternative on another emulator is in [`capture-dosbox-automation.md`](capture-dosbox-automation.md). This note records what was tried to make capture faster, more repeatable or parallel, and what each change did.

## 1. Experiments


`[Bounded Observation]`, 2026-10-30, `vault-balloon` (112 frames), 16 logical cores with the batch survey running (CPU 70 to 90%), so seconds are indicative. Scratch scripts patched `emulator.launch_argv`; no tracked file changed.

* **Time breakdown.** Launch to the first frame is about 4 s (dialog settled at 3.1 to 3.4 s, first frame 0.9 s later); the per-frame loop costs 0.25 to 0.26 s per frame in every configuration. A profile of one run spent 57 of 58.6 s in `socket.recv_into`: Python waits while DOSBox-X runs to the trap and dumps the page. A run lasts 35 to 59 s, so boot is under 2% of a median survey capture (200 s). The earlier "34 s launch" figure was wrong.
* **End-of-film tail.** After the last distinct raster the harness waits for `END_IDLE_HITS = 300` idle trap hits (about 0.09 s each) in [`framebuffer.py`](../../python/stunt_reel/tac/framebuffer.py); the "film clock holding" exit only fires after a new raster. The tail ranged 0 to 30 s per run (about half of a short film's run).
* **No setting sped the loop up.** `windowresolution = 320x200`, `[render] frameskip = 10` with `scaler = none`, `core = dynamic` and `cycles = max` each left the per-frame cost unchanged; `dynamic` and `max` did not crash on this short film but gave no gain.
* **Sound off breaks the clock.** `sbtype = none` with `nosound = true` produced a film clock stuck at 14650, global tick 0 and a 3-frame capture, the same signature as a survey capture of the same film (`vault-balloon/frames/002`).
* **Baseline noise.** Two unmodified captures: 112 frames each and identical palettes, but 93 of 112 `.idx` files differ and `film_tick` differs by about 1 in 100 of 112 frames; mid-run dips of about -28 ticks occurred under load.
* **DOSBox-X flags.** `-time-limit N` ends the process after N s (the harness then reports a lost debugger socket, exit 1, partial frames and no `meta.json`); it is a wall-clock cap, not a stuck-clock detector, because a stuck run ends within seconds. `-fastlaunch` saves 0.3 to 0.4 s of boot and changes nothing else.
* **Idle spread and parallel capture.** On a machine at 18 to 31% CPU, four serial runs gave a first-frame tick of 6 to 8 and a first-8-frame spread of 0 to 2 ticks, so the noise floor is the same idle as under survey load. Eight captures at once (each with its own port, stage directory and `--out`, an absolute `-c "mount ..."` path, no `-defaultdir`; a relative mount path failed twice) finished in 64 s with the spread within 0 to 2 ticks, no stuck clock and no dip over 5 ticks, about 450 films per hour of this 112-frame film against 64 to 95 serial. `[sdl] priority = higher,higher` and pinning each instance to a core pair (4 instances) made no measurable difference. Wall time for one film is bimodal, 35 to 45 s or 60 to 64 s, serial or parallel; cause unknown.
* **`turbo` does not help.** `[cpu] turbo = true` (with `stop turbo on key = false`, `stop turbo after second = 0`) made guest time run 5 to 20 times faster against the wall clock but left the cost per captured frame at 0.25 s, so frames fell 57 to 150 ticks apart (9 to 23 frames per film); tags and palettes stayed valid and the film ended at tick 1192, but pages at equal ticks differed more than baseline against baseline (about 18% of pixels against 7%), and `core = dynamic` with turbo never settled the dialog. Not adopted.
* **Frame sampling does not thin frames.** An experimental `--sample-frames K` (stepping stride-1 trap hits between dumps; removed again) announced `dumping every 2 trap hits` for K = 40 on `BALLOON.FLM` (1,192 ticks) yet captured 112 frames 10 to 11 ticks apart, as without it. Guest time advances with the host clock through each debugger round trip (§ 2), so a skipped dump does not widen the tick spacing.
* **Built-in capture.** `dx-capture /v playone.exe` as the last `[autoexec]` line records ZMBV video (the harness cannot start a capture at run time: the control port takes debugger verbs only, and BDA key injection reaches the guest, not the mapper). The film AVI is 640x400 at 70.09 Hz, Mode 13h exactly doubled, RGB with no palette: 764 to 784 distinct frames per run against 111 stepped ones for the same wall time (44 s). It is not index-preserving (32 of 111 stepped frames have two indices sharing one RGB; the video colour scaling differs from the DAC read by 1 in places), carries no film tick (about 1.43 video frames per tick, range 1.09 to 2.0), and two free runs agreed on only 1744 of 2939 frames at the same index (363 distinct frames common), though both ended at tick 1192.

## 2. Tick Lag: Cause and a Deterministic Stepper

`[Bounded Observation]`, 2026-10-30, `vault-balloon` only, 18 DOSBox-X runs on a mostly idle machine; working notes and scripts in `build/scratch/lag/`.

* **The debugger does not halt the guest.** CS:IP and the film clock move between verbs with no RUN. Every verb, RUN included, is answered at a slice boundary about 50 ms apart (20 verbs took 1.01 s and 54 ticks); a RUN is "the next slice" and the post-retrace breakpoint at `0D51:0C5E` was never the stop address in 30 stops. During a pause of S seconds the clock gained 6, 55, 152 and 297 ticks for S = 0, 1, 3 and 6 (49.3 ticks per host second), and the extra ticks at the next RUN were 5 whatever S was. Guest time follows the host wall clock continuously, which is why run time tracks film length, why load adds jitter and why `cycles`, the core and `turbo` change nothing about the cost per frame.
* **The tags are late.** A 64,000-byte dump costs one slice; the clock read before and after a dump spans 5.75 ticks (standard deviation 0.47). Each baseline page best matches a deterministic stepped page 7 to 10 ticks earlier than its tag (5 of 5 sampled frames in each of two runs), not the one tick of [`capture.md`](capture.md) § 4; the midpoint of the clock read before and after the dump bounds the tag within 3 ticks but cannot reach 0.
* **Verbs not in the earlier notes** (from the DOSBox-X exe): `INP`/`OUTP`/`OUTW`/`OUTD <port> <data>` (port I/O), `EV cs ip ss sp ax …` (a register read), `CPU`, `TIMERIRQ`. `SM` parses tokens as expressions, so the bytes `AF`, `CF`, `DF` and `AC` read as flag names and become 0; write them with three digits (`0AC`).
* **Injecting `INT 8` does not work** (the clock advanced in about 1 of 14 injections: the guest is live and the injection races). **Masking does:** `OUTP 21 FF` masks every IRQ; the clock then stays frozen across a 2 s pause and across RUNs, and the render loop still redraws and reaches stops, with no stall or crash.
* **A stepper that is byte-repeatable.** After the film starts: `OUTP 21 FF`; per frame `SM 1575:4896 0LL 0HH 000 000` (tick word, then fraction word); RUN and dump until two consecutive dumps are equal (3.2 runs on average, 4 at most; a fixed 3 RUNs gave only 225 of 418 identical); `VGA DACPAL`; read the clock back. Two runs of 211 frames gave 211 of 211 identical pages and palettes, no clock mismatch and no stuck clock; the page for clock T shows the HUD timecode T x 0.02 s; 10 of 10 palettes equal at matched ticks. The same-hour baseline pair matched byte for byte on 2 of 10 common tags. Cost is 0.58 s per frame, offset by dropping the `END_IDLE_HITS` tail because the film length is known. Jumps larger than the frame spacing were history-dependent in one test, so the schedule must ascend.
* **Production design** (not built): `transport.py` gains a clock-write and an IRQ-mask operation; `session.py` a `step_to(tick)` that writes the clock, runs and dumps until two dumps match; `framebuffer.py` a sampler over a tick schedule. Tags become exact, so the one-tick alignment fit and the pinned reference in `references.toml` need recalibrating. All IRQs masked means no Sound Blaster audio or keyboard; film end, exit, `INTRO.FLM` and `CTRY.FLM` were not tried, and about 100 pixels differ from free-run pages (probably the cursor; unchecked).

## 3. Where a capture ends (the "1001 against 1335" gap)

`[Supported Inference]`, 2026-11-01. The end ticks in [`batch.md`](../parity/batch.md) § 4 and § 5 do not describe the same thing. A capture does not stop early and does not drop its tail: it runs to the film's end (`CTRY.FLM` last tick 1,342) every time. Section 4's `Ticks` column is the span of the 12 frames the error readout picked (`pick_ticks` in [`errors.py`](../../python/stunt_reel/bench/errors.py): scored, `fade_level >= MIN_FADE_LEVEL` = 0.95, spread evenly), so its last tick is the last unfaded scored frame's neighbour, not the capture's last frame. Section 5 lists the capture's own first and last `film_tick`.

Captures of one film, from `captures/<slug>/frames/<run>/meta.json` (runs 001 to 006 of `vault-ctry` predate the validity check and the stepper; all stop within 7 ticks of the film end):

| Film | Run | Frames | First / last `film_tick` |
|---|---|---|---|
| `vault-ctry` | 002 / 003 / 004 | 113 / 121 / 121 | 4 to 1332 / 1335 / 1340 |
| `vault-ctry` | 005 / 006 / 007 / 008 | 121 / 121 / 120 / 120 | 4 to 1340 / 1342 / 1335 / 1335 |
| `vault-splanes` | 001 / 002 | 112 / 112 | 3 to 1235 / 1240 |
| `vault-bomb` | 001 / 002 | 333 / 328 | 3 to 3730 / 3725 |

The scorer's own report for the current batch captures (`build/parity/batch/<slug>/report/report.json`) excludes the closing fade frames and scores the rest; the last scored tick matches the § 4 range, and the last tick the readout can pick is 1252 / 1159 / 3470 with threshold 0.25, or 990 / 951 / 3470 at 0.95:

| Film | Frames | Last capture tick | Excluded (fade) | Last scored tick | Readout's picked span, current capture | Section 4 |
|---|---|---|---|---|---|---|
| `vault-ctry` | 120 | 1335 | 7 (ticks 1263 to 1335, fade 0.22 to 0.02) | 1252 | 4 to 990 | 4 to 1001 |
| `vault-splanes` | 112 | 1240 | 6 (1183 to 1240) | 1172 | 3 to 951 | 3 to 961 |
| `vault-bomb` | 328 | 3725 | 23 (3481 to 3725, fade 0.0) | 3470 | 3 to 3470 | 3 to 3475 |

So both surveys' scored sets are the same size (113, 106 and 305 to 310 frames) and the same span; the SSIM agreement within 0.003 is expected, not a coincidence. The picked-span ends differ from § 4 by 5 to 11 ticks, the capture-to-capture tick jitter ([§ 1](#1-experiments)).

**Do scores compare different spans?** No. The earlier span is the picked-sample span of the same fade-excluded scored set, not a shorter capture: sampling stops before the fade tail. Fade frames are excluded from the mean in both. Section 5's `Frames` and `film_tick` columns are unscored totals including the fade tail (about 7 frames for 1,342-tick films, 23 for `vault-bomb`, whose film ends in black).

### Ruled out

* A capture timeout or frame cap: no run of the three films ends before the film's last 7 ticks, and all 12 captures listed end within 12 ticks of the film end (ctry) or in the fade tail.
* The batch capture stage ending at a different point from `capture-ref`: the same runs span 1332 to 1342 whichever script made them.

### Open questions

* `vault-bomb` ends 3725 to 3730 but its closing 23 frames are fully black (fade 0.0); is the film's own last tick near 3,730, or does the clock keep running after the picture fades? No `BOMB.FLM` length is recorded.
* Section 4's capture is not preserved apart from the ledger, so the 5 to 11 tick gap to the current picked span is inferred, not measured.

## Ruled out

- **Any `dosbox-parity.conf` speed setting for capture:** window size, frameskip, scaler, `core = dynamic`, `cycles = max`; no per-frame gain.
- **`nosound` or `sbtype = none` for capture:** freezes the film clock.
- **Built-in video as the scored reference:** RGB, untagged and unrepeatable; at most a denser visual reference.

## Open questions

1. Build the masked, clock-writing stepper and run it on `CTRY.FLM` twice (every 11 ticks, ascending): byte identity, a clean film end, then score the stepped set against the same renders and recalibrate the one-tick alignment offset and `references.toml`.
2. Does masking all IRQs break film end, exit or the intro films (`INTRO.FLM`), and what is the roughly 100-pixel residual against free-run pages (the cursor)?
3. Parallel stepped capture: with the clock written by the harness, the heavy-load dips should vanish; confirm with 8 stepped captures plus renders.
4. How many survey captures hit the stuck clock (3 frames at tick 0)? The stepper makes this impossible by construction; `-time-limit` does not catch it, and a validity check on tick advance and frame count now rejects it.
5. Does the AVI index carry per-frame timestamps (`skip encoding unchanged frames = true`)? Low priority now that stepped capture is repeatable.

_Found 2026-10-30; see the [parity log](../parity/log.md)._
