# Journal: full-rate video captures

## 2026-11-27: LOCATION with the slot words in the per-frame row

**Question.** Does `capture-video` still finish `LOCATION.FLM` (previous row: `end` `hold` at 11,616 frames) when the row also reads `slot_clock` and `slot_ticks`, against the emulator's one-million-instruction Lua budget (`capture-dosbox-automation.md` § 4.7)?

**Method.** `main` at `d21e5cd` plus the change in #1198, Patch 3 build, the reference `.ALL` pinned in `references.toml`, stubbed samples, `capture` profile (`core = dynamic`, `cpu_cycles = 45000`), dosbox-automation 0.85.1 in a cloud session.
The row read `film_tick`, `global_tick`, `slot_clock` and `slot_ticks` (`DS:0x421C`, `0x1C3E`, `0x4220`, `0x1C62`; the last two inferred, ADR 0057) every frame.
Two runs of `mise run capture-video -- --film corpus/stuntisl/VAULT/LOCATION.FLM --out <dir>`: the first with `meta.json` carrying the slot columns only, the second with the whole-film fields too.

**Result.**

| Run | `end` | Frames | Palette changes | `capture.avi` | `meta.json` | Whole task |
|---|---|---|---|---|---|---|
| 1 | hold | 11,616 | 118 | 19,996,314 B | 2,622,322 B | 334 s (its first build) |
| 2 | hold | 11,616 | 118 | 19,996,314 B | 2,622,941 B | 185 s |

* Both runs finished before the budget ran out, so the row costs under about 86 instructions per frame, the million divided by 11,616 frames, boot and tail included.
  The count itself is not exposed, so the 0.6 to 0.7M estimate ([#1194 budget check](https://github.com/neilsh/stunt-reel/issues/1194#issuecomment-7227024791)) stands unmeasured.
* The two runs' `capture.avi` share one SHA-256 (`16f37fb3980c1b98a0fa2cf3d28bfb22c4a6fcacb250a568ab23a63f0df656ad`), and their `log` and `palettes` objects (`frame`, `film_tick`, `global_tick`, `slot_clock`, `slot_ticks`) are equal.
* `slot_ticks` runs 0 to 2 in the log; `slot_clock` runs 3 to 8,266 with 7,897 distinct values.
* The previous row's `capture.avi` was 19,996,314 bytes (issue #1194, 2026-11-27 comment), the same length as both runs here.
* `meta.json` pretty-printed at indent 2 grew from 2.38 MB to 2.62 MB with the two columns.
* Run 2's `meta.json` validates against the regenerated `video.schema.json` (`jsonschema`), loads in `load_video_capture` (Python) and reads and validates as `VideoCapture` in `stunt-parity`.

**Verdict.** Adopted: the per-frame slot columns stay, and the change-only `slot` log the issue held in reserve is not needed for LOCATION.

**Lives in.** [`capture-dosbox-automation.md` § 4.6 and § 4.7](../../../research/playone-exe/capture-dosbox-automation.md).
