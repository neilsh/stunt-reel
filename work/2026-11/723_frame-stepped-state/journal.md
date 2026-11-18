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

## 2026-11-18: the slot pass keeps each slot's previous position, and the probe sweeps from it

- **Question**: Which state does the slot update `0x1463` advance, does anything reach `0x22DC` or `0x3712` indirectly, and what calls `0xB58D` ([#723](https://github.com/neilsh/stunt-reel/issues/723), continued at `origin/main` `75b9106`)?
- **Method**: Static reading of the unpacked load image, image offsets:
  - `mise run re-tool -- disasm` over `0x13A0..0x13EA` and `0x1422..0x1463` (the rest of `0x136F`, and `0x1423`), `0x14D5..0x1588` (sphere), `0x1588..0x1720` (pair test), `0x1723..0x1790`, `0x240A..0x2631` (probe entry and handlers), `0x26D0..0x2810` (box walk entry), `0x2A50..0x2AA0`, `0x3A72..0x3BD0` (film step and its zero-length-slice path), `0x39AE..0x3A11` (snapshot copy), `0x3E63..0x3E70`, `0x3793..0x37E0` (film reset), `0x4AF8..0x4B06`, `0x4A80..0x4AA5`, `0x0158..0x0172`, `0x0900..0x0918`, `0x4820..0x4880`, `0x43FC..0x44B5`, `0x66C8..0x66E0`, `0xB858..0xB870`, and `0xF791..0xF794` (the load image's bytes at `DS:0x2281`, `0x2282`).
  - `mise run re-tool -- xref` of `0x2281`, `0x2282`, `0x2230`, `0x04EA`, `0x0546`, `0x0DEC`; `mise run re-tool -- vm-handler 0x63` (the `OP_IPG` subtype table).
  - `disasm 0x0 0xD510` searched for near calls and jumps to `0x1423`, `0x144A`, `0x14D5`, `0x1588`, `0x1723`, `0x131B`, `0x16CB`, `0x3B2C`, `0x3712`, `0x4B03`; for operands `0x22C0..0x22DF` other than direct memory operands; for `[reg + 30h]`; and for every `inc` or `dec` of a fixed memory operand.
  - A one-off scan of the unpacked image's bytes (through `re_tool._load`) for the little-endian words `0x3712`, `0x22DC`, `0x22BE`, `0x16CB`, `0x1423`, `0x144A`.
- **Result**:
  - `0x136F` clears bit 0 of each slot's byte `+0` (`0x13B4..0x13C2`) and calls `0x1423` for each slot whose bit is clear (`0x13C5..0x13DC`); `0x1423` sets it, copies `+0x04..+0x0F` to `+0x24..+0x2F` (`0x142A..0x1433`), then jumps to `0x3E63` (byte `+0` bit 7) or through `+0x30` (`0x1440..0x1447`).
    The one instruction naming `+0x30` with a base register stores 0 (`0x37D8`).
  - `0x136F`'s callers are `0x13EB` (the frame, through `0x13EA` from `0x4A17`) and `0x3B6E`, `0x3BAD`, both in `0x3B2C..0x3BBC`, reached from `0x3B14` for a zero-length slice while `0x2281` is set.
    `0x39AE` copies 12 words per slot (`0x39C4`).
  - `0x14D5` writes the sphere's centre as the midpoint of `+0x04` and `+0x24` per axis (`0x14D5..0x153F`) and its radius as the largest half-displacement (`0x1522..0x155E`) plus the shape's radius (`0x1561..0x1584`).
  - The probe's splits `0x24B8`/`0x24C2` pick one side or both by the sphere's centre and radius high word `0x2302`; `0x2547` and `0x257A` test it against cubes and objects; the slopes `0x250D`/`0x252A` and the ground square `0x25F5` use the current position copied to `0x2308` (`0x2425..0x2432`).
    The box walk subtracts the object's position from the current position (`0x2762..0x27A5`) and from the `+0x24` one (`0x27A9..0x2808`).
    On carry from `0x26D0` (`0x25D2`), `0x25D7` loads `SP` from `0x2340`, stored at `0x240A`, so the probe returns.
  - `0x2282` is 0 in the load image and written only at `0x49C1`, with 0; `0x1588` is called under it (`0x149A`).
    `0x4B03` is `ret`; `0x16C2` and `0x25EE` go there.
  - The word `0x3712` is nowhere in the image; `0x22DC` only at `0x137C` and `0x3720`, inside its stores; `0x22BE` at `0x054D` (inside `mov si,722h`), `0x0E50`, `0x3719`, `0x371D`.
    No instruction uses an operand in `0x22C0..0x22DF` as an immediate or base, except `0x837B` and `0x838D` among `(bad)` decodes.
  - `vm-handler 0x63` lists type `0x0006 -> image 0xB58D`.
  - The DGROUP `inc`/`dec` of a fixed operand below image `0x8240`: `0x2230` (`0x016C`), `0x4EA` (`0x090F`), `0x2366` (`0x1412`, `0x145E`), `0x22BA`, `0x22B8` (`0x43A5`, `0x43B0`), `0x0BD4` (`0x449A`), `0x546` (`0x4879`, `0x6421`, `0x7411`), `0x4896` (`0x4A8B`, `0x4A9D`), `0x0DEC`, `0x1092`, `0x10C6` (`0x66D8..0x78AB`).
- **Conclusion**: The state stepped per drawn frame is each slot's `+0x24..+0x2F`, its position at the previous pass; the probe sweeps from it to the current position, so its results, the shadow's plane and box top, can depend on the frame before.
  Whether that explains CTRY's pages in [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 needs a live log ([#779](https://github.com/neilsh/stunt-reel/issues/779)).
- **Recorded in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5, Ruled out and open question 1; [`sod-vm-frame.md`](../../../research/playone-exe/sod-vm-frame.md) § 9.1; [`memory-map.md`](../../../research/playone-exe/memory-map.md) rows `0x2282`, `0x22BE`, `0x22DC`, `0x2B2A`; [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md) rows `CS:0x1423` and `CS:0xB58D`.
