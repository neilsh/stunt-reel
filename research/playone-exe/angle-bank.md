---
summary: "Bank words `0x10`..`0x14`, `0x18` and `0x1A` (`work:0x811E`..`0x8128`) are written once per frame for the whole film from the clock and film variables 10 and 12; only `0x16` is per actor. `BVGT` reads the bank too, and a rotor picks solid or line blades by word `0x12`."
sidebar_label: "Angle bank & film variables"
---
# `PLAYONE.EXE`: the Angle Bank and Film Variables 10 and 12

* **Binary**: `PLAYONE.EXE`, the unpatched load image (`build/re/playone.img` in the data root).
* **Method**: Static reading with `mise run re-tool -- disasm` and `mise run re-tool -- xref`; live breakpoints and watches on DOSBox-X ([ADR 0034](../../docs/adr/0034-breakpoints-run-on-dosbox-x.md)) with the plan [`film-vars-10-12.toml`](../../tools/dosbox-x/plans/film-vars-10-12.toml) on `INTRO.FLM`.
* **Scope**: what writes the bank words `ROTX`, `ROTY`, `ROTZ` ([`sod-vm-execution.md`](sod-vm-execution.md) § 8.7) and `OP_ANIMATE` ([`sod-animate.md`](sod-animate.md) § 2) read, when, and from what.

Offsets are load-image offsets; `DS:` offsets are `DGROUP`-relative and `work:` offsets are in the VM work segment (`0x15D4` in the image, `ES` at the writer).

---

## 1. The Rule

`[Established]` for the instruction sequences, static, and observed live: all 94 stops at the writer's `ret` across three runs match the table below (section 3).

Once per frame, before the object loop at `0x1E07`, `0x1D96` fills the bank from the film state at `DS:0x4888`; each operand's word is `work:0x810E + operand` ([`memory-map-vm.md`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) § 3).
With `v10` and `v12` film variables 10 and 12 as interpolated for this frame, `p10` the `v10` of the previous call (kept at `DS:0x22BC`) and `clock` the film clock `[0x4888 + 0x0E]`:

| Operand | Image offset | Value |
|---|---|---|
| [`0x10`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1DCA..0x1DD0` | `clock << 12` |
| [`0x12`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1DA9..0x1DBD` | `d << 8` with `d = (v10 − p10) mod 2^16` when `d < 256`, else `0xFF00`: the change of var 10 since the previous frame, saturated at 255, a fall included |
| [`0x14`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1DC2..0x1DC6` | `(p10 & 0xFF) << 8`: the low byte of the **previous** frame's var 10 |
| [`0x16`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1D66..0x1D69` | The drawn slot's animate word, written by the actor draw for each actor, not by `0x1D96` ([`sod-animate.md`](sod-animate.md) § 2) |
| [`0x18`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1D9B..0x1D9F` | `v12` |
| [`0x1A`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) | `0x1DA3..0x1DA5` | `−v12 mod 2^16` |

`0x22BC` is `xchg`ed with the new `v10` (`0x1DAF`), so `p10` is the value the previous call stored.
No other instruction names `0x22BC` (`mise run re-tool -- xref`, one reference), and its image value is 0, so it starts at 0; no film-start fill found covers it (the `rep stos` sites at `0x3747`, `0x37C8`, `0x37EF`, `0x3F5F` and `0x4021` do not), so a film's first frame likely takes `p10` from whatever ran before it (`[Supported Inference]`).

**Per film, not per actor.**
The only call of `0x1D96` is `0x1DD6`, the first thing `0x1DD5` does, and `0x1DD5`'s only call is `0x0F77` in the frame step `0x0F4A`, which `0x4A2F` reaches through `0x0EE9` with `BX = 0x4888` (byte scan for near `call`/`jmp` targets, and `mise run re-tool -- disasm`).
`0x1DD5` then walks the object list at `[bx + 0x2E]` (`0x1E07..0x1E3A`) and queues each object whose flag tests pass (`0x1A90`, `0x19FC`), then walks the scene from `0x1E82` to draw them through `0x1C00` ([`sod-vm-frame.md`](sod-vm-frame.md) § 9.1), so every actor of a frame reads the same words `0x10`..`0x14`, `0x18` and `0x1A`.

**Film variables 10 and 12 move only as film variables.**
`0x1D9B` (`[bx+0x96]`) and `0x1DA9` (`[bx+0x92]`) are the only instructions that name them by offset (`mise run re-tool -- xref` on `0x92`, `0x96`, `0x47DC`, `0x47E0`, `0x491A`, `0x491E`).
Every other access is generic over all 16 variables: `var_set` keys (`0x3D54`), `before` records (`0x3D2A`), the per-frame interpolation `0x136F` and the film-start reset ([`palette-fade.md`](palette-fade.md) § 2).
So per tick, var 10 and var 12 are their `var_set` keys interpolated linearly by the film clock, as vars 13 to 15 are; no code adds a rate or a per-actor term.

_Source: [the bank writer read and broken on](../../work/2026-11/456_film-vars-10-12/journal.md#2026-11-13-the-bank-writer-read-and-broken-on)._

---

## 2. Consequences for a Tick-Sampled Renderer

* `0x18` and `0x1A` depend on var 12 at the frame alone, and `0x10` on the clock alone, so a renderer that samples the film at a tick reproduces them.
  `CTRY.FLM` never keys var 12, so it stays 0 there and every `ROT*` reading `0x18` or `0x1A` is skipped.
  `INTRO.FLM` keys var 12 to 16384 from tick 2786 to 3641 (`mise run flm-events`).
* `0x14` lags by one `PLAYONE` frame, and `0x12` is the change over one frame, so both depend on how many ticks a frame spans.
  Under DOSBox-X at the harness's default cycles, successive frames in `INTRO` ticks 1337–1452 and 2804–2840 were 2 to 5 ticks apart (`[Bounded Observation]`, one film, one emulator setting); real hardware is unmeasured.
  In `INTRO.FLM`'s montage the stops show `0x12` between `0x0600` and `0xD400` (a change of 6 to 212), and `0xFF00` once, at the first stop of the tick-2800 window (tick 2804, var 10 = 363, previous frame not observed), so it is not a constant.
  `CTRY.FLM`'s keys climb about 24 a tick, which at 2 to 5 ticks a frame is 48 to 120.
* **Under the capture harness frames are mostly 0 or 1 tick apart** (`[Bounded Observation]`, two films, the `capture` profile: dosbox-automation 0.85.1, `core = dynamic`, `cpu_cycles = 45000`, Patch #3 `PLAYONE.EXE`, each reference capture's own archive with its sound samples stubbed).
  `PLAYONE` draws more than one frame per film tick there, so var 10 often has not moved since the previous drawn frame.
  Read from bank word `0x12` after every emulated frame.
  A frame counts when the var-10 value it was drawn with shows in the trace at no more than two consecutive film ticks, so var 10 was moving there; one whose word `0x12` is 0 counts as 0 ticks, and any other is placed by mapping both its var-10 value and the previous frame's to the ticks that showed them:

  | Window | Measured | 0 ticks | 1 tick | 2 ticks |
  |---|---|---|---|---|
  | `LOCATION` 836–901 | 91 | 81.3% | 18.7% | 0 |
  | `LOCATION` 1–1000 | 1,189 | 70.3% | 27.0% | 2.7% |
  | `INTRO` 1337–1452 | 96 | 58.3% | 31.2% | 10.4% |
  | `INTRO` 2804–2840 | 44 | 40.9% | 59.1% | 0 |
  | `INTRO` 1–3822 | 1,531 | 37.6% | 43.5% | 18.9% |

  No counted frame was 3 ticks or more, but the table leaves out frames whose change of var 10 maps to no tick (665 in `INTRO` 1–3822, 38 in `LOCATION` 1–1000) or is saturated at `0xFF00` (10 in `INTRO`), so larger gaps, at cuts or elsewhere, are not excluded.
  The spacing varies frame to frame and its mix varies by film and scene, so no constant reproduces every frame.
  A tick is mapped from each var-10 value, which can be one tick off where a sample reads var 10 before the bank call after it.
  The run was headless in a cloud session, while the reference captures were made locally before cloud sessions ran the emulator (2026-11-09); its film clock matched theirs at all 431 kept pages it covered (84 `vault-location`, 347 `vault-intro`), and at a fixed `cpu_cycles` the emulated machine, not the host, paces the guest (`[Supported Inference]`).
  The bank a sample reads may not be the one the page at that frame was drawn with: `vault-location`'s page at tick 881 shows what #504 read as the solid arm (`[Hypothesis]`), while the bank at that frame holds a frame drawn at clock 881 with word `0x12` = `0x1C00`, the line arm; the frame before it, drawn at clock 880, had `0x12` = 0.
* The renderer fills the bank this way per actor and tick ([`angle_bank`](../../crates/stunt-core/src/scene/bank.rs)), taking `p10` as var 10 [`PREVIOUS_FRAME_TICKS`](../../crates/stunt-core/src/scene/bank.rs) = 0 ticks earlier, so word `0x12` is 0 and `0x14` takes this frame's var 10.
  Of 0, 1 and 3, 0 gave the best mean over the reference films; 1 scored above 0 on `intro` alone, the film with the larger share of 1-tick frames above.
  A frame the original drew 1 tick after the one before has its propeller phase off by var 10's rate in a tick, and once `BVGT` reads the bank (#624) a constant 0 would always draw a rotor's solid arm, while the measured mix says the original sometimes draws the line arm.
* `[Supported Inference]` that var 10's low byte is a propeller phase in 1/256 turns: [`sod-vm-execution.md`](sod-vm-execution.md) § 8.7 has stock propellers turning by `ROTZ` on operand `0x14`, and `(p10 & 0xFF) << 8` sweeps the 16-bit angle once every 256 units of var 10.

_Source: [drawn frames are mostly 0 or 1 tick apart under the capture profile](../../work/2026-11/693_frame-spacing/journal.md#2026-11-18-drawn-frames-are-mostly-0-or-1-tick-apart-under-the-capture-profile), [`PREVIOUS_FRAME_TICKS` swept at 3, 0 and 1](../../work/2026-11/693_frame-spacing/journal.md#2026-11-18-previous_frame_ticks-swept-at-3-0-and-1)._

---

## 3. Live Check

`[Established]`, three runs of [`film-vars-10-12.toml`](../../tools/dosbox-x/plans/film-vars-10-12.toml) on `INTRO.FLM`, unpatched build, DOSBox-X 2026.10.01:

* **The words.**
  A break at the `ret` `0x1DD4` read the bank (`ES:0x811E`, 12 bytes), the clock, the 16 variables of `DS:0x4888` and `DS:0x22BC` on every stop: 94 stops, none that differs from the table in section 1 (the first stop of each window checks `0x10`, `0x18` and `0x1A` only, having no previous stop for `p10`).
  From tick 2804 var 12 is 16384 and the bank holds `0x4000` and `0xC000`; at ticks 1337–1452 it is 0 and both words are 0.
* **Once a frame.**
  Every stop had `BX = 0x4888`.
  In every run the frame step `0x4A2F` and the bank stops alternated strictly over all 24 frames of the tick-1300 window, and in each complete frame the 60-stop cap on the actor draw `0x1D66` allowed (ticks 1334–1382) it stopped 16 to 18 times between two bank stops.
* **No other writer.**
  A watch on `work:0x811E..0x8129` (ticks 1364–1418, 40 changing writes) named only `0x1DBD` (13), `0x1DC6` (12) and the per-actor `0x1D69` (15).
  A watch on var 10 in the `DS:0x4888` struct (`DS:0x491A`) named only `0x13AC`, the store of `0x136F` (24 of 24); the same variable in `DS:0x474A` (`DS:0x47DC`) did not change in any run after tick 1300.

_Source: [the bank writer read and broken on](../../work/2026-11/456_film-vars-10-12/journal.md#2026-11-13-the-bank-writer-read-and-broken-on)._

---

## 4. A Reader of Word `0x12`: the Rotor of Shape `0x3E57`

`[Established]` for the handler and the shape's stream, static; `[Bounded Observation]` for the live words, one film under DOSBox-X, run with the `.ALL` from `corpus/siarchive/Films/OldPLAY/Vault`, which differs from the reference capture's The `.FLM` is the same, so the film variables and clock the words are made from match; words `0x12` and `0x14` also depend on how many ticks a frame spans (section 2), which the archive and emulator settings can shift ([`linking.md`](../makeone-exe/linking.md) § 7.2), so this run's spacing need not be the capture's.

* **`BVGT` reads the bank.**
  Its handler `0x9C23` (unpatched dispatch slot `0x853D`) loads the operand word into `BX`, compares `[BX + 0x810E]` with the threshold word, and branches by the rel word unless the bank word is below it (`jb` at `0x9C2D`): taken when `bank[op] >= val`, unsigned, the target being the rel word's address plus the rel word.
  This confirms the si-tools reading in [`sod-opcodes.md`](../formats/sod-opcodes.md) § 3.
* **The rotor.**
  The helicopter shape `0x3E57` (in `LOCATION.ALL`) turns its main rotor by `ROTY` on operand `0x14` inside `PUSHRELMAT`/`POPRELMAT` (stream `0x0D7E..0x0D98`), then runs `BVGT 0x12, 0x0FA0`: below the threshold it calls `0x13E2`, the hub and two solid blades (colours 0 and `0x17`); at or above it, `0x18A0`, the hub with the blades as `ZLINETO` lines.
  The tail rotor (`0x0E76`) repeats the pattern with `ROTX`.
  So the solid blades are drawn when var 10 moved by less than 16 since the previous frame, and the line blades otherwise.
  This answers open question 1 for `BVGT`, not for `ROT*`.
* **Live, `LOCATION.FLM`.**
  On Patch #3 under DOSBox-X at 8000 cycles, 30 stops at the bank writer over ticks 836 to 901 had frames 2 or 3 ticks apart and word `0x12` between `0x1D00` and `0x9000`, so every frame took the line arm.

How our render differs is in [`framing-and-actors.md`](../parity/framing-and-actors.md) § 3.

_Source: [the trapezoid is the rotor's slow arm at rest](../../work/2026-11/504_rotor-trapezoid/journal.md#2026-11-16-the-trapezoid-is-the-rotors-slow-arm-at-rest)._

---

## Ruled out

* **A per-actor value for operands `0x10`..`0x14`, `0x18`, `0x1A`.**
  One caller per frame, before the object loop; `BX = 0x4888` on every stop; no writer but `0x1D96` in the bank watch. [Journal](../../work/2026-11/456_film-vars-10-12/journal.md#2026-11-13-the-bank-writer-read-and-broken-on).
* **`0x8120` as the sign of var 10's change** ([`palette-fade.md`](palette-fade.md) § 3.2 before this note): it is the change itself, saturated at 255; the live stops show `0x7F00`, `0xA000`, `0x4800` and others.
* **`0x8122` as `(var 10 & 0xFF) << 8` of the current frame** ([`sod-vm-execution.md`](sod-vm-execution.md) § 8.7 before this note): it is the previous call's var 10; at tick 1342 var 10 is 12928 (`0x3280`) and the word is `0x0100`, from 12801 (`0x3201`) one frame earlier.

## Open questions

1. Whether any stock shape reads operand `0x12` with a `ROT*` (no `OP_ANIMATE` does, [`sod-animate.md`](sod-animate.md) § 2).
   `BVGT` reads it (section 4), so which arm a rotor draws depends on `PLAYONE`'s frame spacing, mostly 0 or 1 tick under the capture harness (section 2).
2. The watch on `work:0x811E..0x8129` never named the `0x811E` store at `0x1DD0`, though the break stops show the word following the clock; why the watch misses it is not known.
3. Why `0x136F` writes var 10 in the `DS:0x4888` struct during playback while the `DS:0x474A` copy stays still, given [`palette-fade.md`](palette-fade.md) § 3.2's copy from `0x47C8` to `0x4906`.
4. Which drawn frame a captured page shows, relative to the bank a sample at the same emulated frame reads (section 2, tick 881).
   Reading the bank and the composed-page words at more than one point per emulated frame, or a DOSBox-X break at the end of the `A000` copy, would tell.
