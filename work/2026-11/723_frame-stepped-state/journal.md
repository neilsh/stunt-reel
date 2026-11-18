# Journal: what `PLAYONE` steps per drawn frame

## 2026-11-18: the per-frame call steps no frame counter

- **Question**: What state does `PLAYONE.EXE` step per drawn frame rather than per film tick, so that a later film start changes what is drawn at a tick ([#723](https://github.com/neilsh/stunt-reel/issues/723); [`film-load.md`](../../../research/playone-exe/film-load.md) open question 1)?
- **Method**: Static reading of the unpatched load image at `origin/main` of 2026-11-18 (`f81532a`), image offsets:
  - `mise run re-tool -- xref` of `0x22DC` (also with `--code-end 0xFFFF`), `0x22DA`, `0x22D8`, `0x22DE`, `0x22BE`, `0x22BA`, `0x22B8`, `0x4758`, `0x475C`, `0x41B6`, `0x2366`, `0x2368`.
  - `mise run re-tool -- disasm` over `0x43A5..0x4400` (INT 8 path), `0x49F9..0x4A60` (film step), `0x1360..0x13A0`, `0x13EA..0x14D5` (slot pass, queue, slot update), `0x5540..0x5570`, `0x8368..0x8385`, `0xB585..0xB5D0`.
  - `mise run re-tool -- disasm 0x0 0xD510`, searched for `call`, `jmp` and operands naming `0x3712`, `0x136F`, `0x13EA`, `0x1463`, `0x240A` and `0xB58D`.
- **Result**:
  - The film step `0x49F9..0x4A52` increments no word in memory; `0x13EA` runs `0x136F`, `0x1463`, then a deferred-call queue (`DS:0x2366` count, entries at `0x2368`, pushed by `0x144A`, at most 64) that it runs down to 0 each frame.
  - `0x22DC`: stores at `0x137B` and `0x371F`, no other operand over the whole image; `0x22DA` is no operand; the `0x22D8` operand at `0x837B` sits among `(bad)` decodes.
  - `0x22BE`: zeroed at `0x0E4E`, used at `0x3712..0x371B`; nothing in the code names `0x3712`.
  - `0x22BA`: counted on every interrupt; read at `0x5552` (sets `0x0D98` when at most 10 ticks passed since `0x0D90`) and `0x5B4A`/`0x5B66` (a timer at `0x0D90` that calls `[si + 8]` after 20 ticks, then every 3).
  - `0x22B8`: read at `0x3712` and, through `ES = 0x0D51`, at `0xB5A6`, where `0xB58D` turns its low six bits into an angle into the table at `0x19AA` and stores half the entry at `0x41B6`; `0xB58D` has no near caller.
  - `0x4758:0x475A`: a second clock, the speed `0x475E` added per tick (`0x43B4..0x43D2`), copied to `0x475C` at `0x0E48`, saved and restored at `0x3B33`/`0x3BB8`.
  - Callers of `0x136F`: `0x13EB`, `0x3B6E`, `0x3BAD`.
- **Conclusion**: No frame counter and no reader by address of the per-frame deltas carries the start's phase; the timer-tick phase at `0xB58D` follows `0x22B8`, not the drawn frame.
  Left unread: `0x14D5`, `0x240A` and `0x1588` in the slot update, a reader of `0x22DC` through a computed pointer, the callers of `0x3712` and `0xB58D`, and `0x62E7`, `0x4FCD`, `0x0EE9`, `0x33C3`, `[0x225A]` and `0x31C0` in the film step.
- **Recorded in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5, Ruled out and open question 1; [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md) rows `CS:0x13EA` and `CS:0xB58D`.
