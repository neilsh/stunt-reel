# Journal: #693, frame spacing under the capture harness

## 2026-11-18: drawn frames are 0 or 1 tick apart under the capture profile

- **Question**: under the capture harness's own settings, how many film ticks separate a drawn `PLAYONE` frame from the one before it, in `INTRO` and in `LOCATION` ticks 836–901, so that `PREVIOUS_FRAME_TICKS` and #624's rotor arm rest on a measurement?
- **Method**: on `75b9106a` (main), in a cloud session, dosbox-automation 0.85.1 headless (`SDL_VIDEODRIVER=offscreen`), the `capture` profile (`core = dynamic`, `cpu_cycles = 45000`), the Patch #3 `PLAYONE.EXE` both reference captures name, each reference capture's own archive (`captures/vault-location/archives/LOCATION.ALL`, `captures/vault-intro/archives/INTRO.ALL`) staged with its sound samples stubbed as `capture-ref` stages it, and the dialog keys and boot frames of `luagen` (the trace starts at frame 1276, the first after the keys).
  A one-off Lua script (`mise exec -- uv run python <scratch driver>`, built on `luagen._prelude`, `capture_run.staged_play` and `automation.launched`, not committed) read after every emulated frame (`dosbox.wait_frames(1)`): the film clock `DS:0x421C`, the global tick `DS:0x1C3E` (unpatched `0x22B8`), the previous bank call's var 10 `DS:0x1C42` (unpatched `0x22BC`), var 10 in the snapshot struct `DS:0x42A0` (`0x420E + 0x92`), and bank words `0x10`, `0x12` and `0x14` at `work:0x811E..0x8122`, the work segment read from `DS:0x05BE`; `DS = 0x0E66` ([`memory-map-patch3.md`](../../../research/playone-exe/memory-map-patch3.md)).
  `LOCATION` ran to tick 1000 (1,399 frames, 47 s); `INTRO` to its end (5,653 frames, tick 3822, then the 300-frame hold, 101 s).
  A drawn frame's spacing is read from bank word `0x12`, `d << 8` with `d` the change of var 10 since the previous drawn frame: the drawn frame's var 10 is `DS:0x1C42` after the bank call, the previous one's is that minus `d`, and each value maps back to the film tick at which the trace saw var 10 take it (values var 10 held for more than two ticks, or never showed in the struct, are skipped).
  Only frames where var 10 moves count, since `d` is 0 otherwise whatever the spacing.
- **Result**:
  - **The trace keeps the reference captures' timing.**
    At each kept page's `emu_frame` in the reference `meta.json`, the trace's film clock equals the page's `film_tick` on all 84 `vault-location` pages up to tick 1000 and all 347 `vault-intro` pages.
    The global tick equals the film clock on every frame of both traces while the film plays; after `INTRO`'s last tick (3822) the global tick runs on to 4036 while the film clock holds.
    The clock advances 0.713 ticks per emulated frame over the `LOCATION` trace (50 Hz ticks against 70.087 Hz frames).
  - **Spacing, film ticks between consecutive drawn frames**, one sample per emulated frame:

    | Window | Frames with var 10 moving, measured | 0 ticks | 1 tick | 2 ticks |
    |---|---|---|---|---|
    | `LOCATION` 836–901 | 91 | 74 (81.3%) | 17 (18.7%) | 0 |
    | `LOCATION` 1–1000 | 1,189 | 836 (70.3%) | 321 (27.0%) | 32 (2.7%) |
    | `INTRO` 1337–1452 | 96 | 56 (58.3%) | 30 (31.2%) | 10 (10.4%) |
    | `INTRO` 2804–2840 | 44 | 18 (40.9%) | 26 (59.1%) | 0 |
    | `INTRO` 1–3822 | 1,531 | 575 (37.6%) | 666 (43.5%) | 290 (18.9%) |

    No window measured 3 or more ticks; `INTRO` also had 10 frames with word `0x12` saturated at `0xFF00` (a fall or a change of 255 or more, at cuts) and 665 it could not map, and `LOCATION` 1–1000 had 38 unmapped.
    In `INTRO` ticks 2806–2822 every sample shows `d` of 0 or 23 to 26, var 10 moving 23 to 26 a tick, so the frames there are 0 or 1 tick apart; the mapping by tick can be off by one where a sample reads var 10 before the bank call that follows it.
  - **More than one drawn frame per emulated frame.**
    Between consecutive samples `DS:0x1C42` often moved by one tick's worth of var 10 while the later sample's word `0x12` read 0 (`INTRO` frame 5209, tick 2809: `0x1C42` 508 then 534, `d` 0), so at least two bank calls ran between them: one that moved var 10 and one that did not.
  - **The bank at a captured frame does not always give that page's arm.**
    At `vault-location`'s page at tick 837 (frame 2445) the bank holds a frame drawn at clock 836 with word `0x12` = 0, the solid arm; at the page at tick 881 (frame 2507) it holds a frame drawn at clock 881 with `0x1C00`, the line arm.
    [#504's journal](../504_rotor-trapezoid/journal.md#2026-11-16-the-trapezoid-is-the-rotors-slow-arm-at-rest) counts large index-0 and index-23 shapes, read there as `[Hypothesis]` solid blades, on both pages.
    If they are, the 881 page shows the frame before the one whose bank the sample read (drawn at clock 880, whose own sample at frame 2506 reads `d` 0): `[Hypothesis]` that a sample can land after a frame's bank call and before its page reaches `A000`, which would also fit the one-tick page lag ([`capture.md`](../../../research/playone-exe/capture.md) § 4).
- **Verdict**: control, a measurement. Under the capture profile `PLAYONE` draws several frames per film tick, so consecutive drawn frames are 0 or 1 tick apart in most measured frames and 2 at most, not the 2 to 5 DOSBox-X showed at its default cycles; the share at 0 differs by film and scene (81% in `LOCATION` 836–901, 41% in `INTRO` 2804–2840), so no one constant reproduces every frame.
  The trace ran headless in a cloud session; the reference captures, made locally on 2026-11-09, were not rerun there, but the trace's clocks matched theirs at every kept page above, and the emulated machine, not the host, sets the guest's frame rate at a fixed `cpu_cycles` (`[Supported Inference]`).
- **Lives in**: [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 2.

## 2026-11-18: `PREVIOUS_FRAME_TICKS` swept at 3, 0 and 1

- **Question**: which of the measured spacings, 0 or 1 tick, should replace the guessed 3 as `PREVIOUS_FRAME_TICKS`, the lag at which the renderer reads var 10 for bank words `0x12` and `0x14`?
- **Method**: on `75b9106a` with a temporary switch `DBG_PREV_TICKS` overriding the constant in `previous_bank` (`crates/stunt-core/src/scene/film.rs`, not committed), on lavapipe in a cloud session:
  `mise run sweep -- --var DBG_PREV_TICKS=3,0,1 --track evidence --record work/2026-11/693_frame-spacing --topic previous frame ticks --target location:836-901 --images work/2026-11/693_frame-spacing/images --jobs 4`.
  Evidence-backed track: the rule is the bank writer's, read at `0x1DA9..0x1DC6` ([`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 1), and its one parameter is the spacing measured in the entry above; the `location` range is attribution only.
  `BVGT` still reads bank words as 0 (#624), so the sweep moves only what reads word `0x14`, the propeller and rotor angles.
- **Result**: the sweep's table, `mean_ssim` per film ([`previous-frame-ticks.toml`](sweeps/previous-frame-ticks.toml)):

  | `DBG_PREV_TICKS` | ctry | intro | land | balloon | traintnl | bomb | location | mean |
  |---|---|---|---|---|---|---|---|---|
  | 3 (baseline) | 0.9184 | 0.8612 | 0.8943 | 0.8172 | 0.8627 | 0.8461 | 0.8320 | 0.8617 |
  | 0 | 0.9188 | 0.8617 | 0.8943 | 0.8172 | 0.8635 | 0.8461 | 0.8383 | 0.8628 |
  | 1 | 0.9187 | 0.8619 | 0.8943 | 0.8172 | 0.8633 | 0.8461 | 0.8328 | 0.8620 |

  `winner: DBG_PREV_TICKS=0 adopts (evidence, film means; target idx +0.0323 attribution; worst target frame +0.0000 location:848; 8 frames down >0.005, listed)`.
  Against the baseline, 0 raised the `location` target range by +0.0336 SSIM; its 8 frames down by more than 0.005 are `location:551 -0.0181`, `location:496 -0.0172`, `location:1057 -0.0143`, `location:124 -0.0110`, `location:507 -0.0105`, `traintnl:694 -0.0065`, `location:7580 -0.0065` and `intro:3125 -0.0061`.
  Variant 1 put 51 frames down by more than 0.005, its worst `-0.1253`.
  The sweep's pictures (capture, baseline 3, winner 0): [`location` 848](images/location-848-previous-frame-ticks.png), [`location` 881](images/location-881-previous-frame-ticks.png), where the rotor's solid blades now lie near the capture's black shape instead of out of view, and the guard frames [`location` 551](images/location-551-previous-frame-ticks-guard.png), [`intro` 3125](images/intro-3125-previous-frame-ticks-guard.png) and [`traintnl` 694](images/traintnl-694-previous-frame-ticks-guard.png), each a rotor or propeller at another angle than the capture's.
  For the films the sweep did not picture, `mise run frame -- --var DBG_PREV_TICKS=3,0` on `15a615e` (main after #783) with the switch drew each film's most-raised frame: [`ctry` 122](images/ctry-122-previous-frame-ticks-frame.png) (+0.0030), [`intro` 1299](images/intro-1299-previous-frame-ticks-frame.png) (+0.0084) and [`traintnl` 650](images/traintnl-650-previous-frame-ticks-frame.png) (+0.0189), the last a propeller turned to the capture's angle.
- **Verdict**: adopted, `PREVIOUS_FRAME_TICKS` = 0, by the evidence-backed film-mean branch (`location`, `ctry`, `intro` and `traintnl` rise; `land`, `balloon` and `bomb` do not move).
  1 rose more than 0 on `intro` alone (+0.0002 over 0), which fits `INTRO`'s larger share of 1-tick frames in the entry above, but it fell on `location`'s target frames, so neither measured constant suits every film.
  With 0, word `0x12` is always 0, so once `BVGT` reads the bank (#624) a rotor would always take the solid arm; the measured mix (19% of `location` 836–901 at 1 tick) says the original sometimes draws the line arm.
- **Lives in**: [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 2.
