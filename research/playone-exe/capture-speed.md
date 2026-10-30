# `PLAYONE.EXE`: Capture Speed and DOSBox-X Configuration Experiments

The harness is in [`capture.md`](capture.md). This note records what was tried to make capture faster, more repeatable or parallel, and what each change did.

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
* **`--sample-frames K` does not thin frames.** It announces `dumping every 2 trap hits` for K = 40 on `BALLOON.FLM` (1,192 ticks) yet captured 112 frames 10 to 11 ticks apart, as without it. Together with the wall-paced run time this suggests guest time advances with the host clock through each debugger round trip, so a skipped dump does not widen the tick spacing; unconfirmed. The batch survey therefore defaults to every frame.
* **Built-in capture.** `dx-capture /v playone.exe` as the last `[autoexec]` line records ZMBV video (the harness cannot start a capture at run time: the control port takes debugger verbs only, and BDA key injection reaches the guest, not the mapper). The film AVI is 640x400 at 70.09 Hz, Mode 13h exactly doubled, RGB with no palette: 764 to 784 distinct frames per run against 111 stepped ones for the same wall time (44 s). It is not index-preserving (32 of 111 stepped frames have two indices sharing one RGB; the video colour scaling differs from the DAC read by 1 in places), carries no film tick (about 1.43 video frames per tick, range 1.09 to 2.0), and two free runs agreed on only 1744 of 2939 frames at the same index (363 distinct frames common), though both ended at tick 1192.

## Ruled out

- **Any `dosbox-parity.conf` speed setting for capture:** window size, frameskip, scaler, `core = dynamic`, `cycles = max`; no per-frame gain.
- **`nosound` or `sbtype = none` for capture:** freezes the film clock.
- **Built-in video as the scored reference:** RGB, untagged and unrepeatable; at most a denser visual reference.

## Open questions

1. Parallel capture under heavy load (8 captures plus renders): the idle test held the band; the -28 tick dips seen under survey load are untested at that load.
2. Shorten the end-of-film tail (read the film clock on idle hits or lower `END_IDLE_HITS`): up to about 25 s per film, a change to a tracked file.
3. How many survey captures hit the stuck clock (3 frames at tick 0)? `-time-limit` does not catch it; a validity check on tick advance and frame count would.
4. A debugger verb that runs to a condition or dumps memory in bulk was not listed and is the only plausible route to a faster per-frame loop.
5. Does the AVI index carry per-frame timestamps (`skip encoding unchanged frames = true`)?

_Found 2026-10-30; see the [parity log](../parity/log.md)._
