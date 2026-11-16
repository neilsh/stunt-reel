---
summary: "Index of the `PLAYONE.EXE` memory-map files and the conventions they share, with the `DGROUP` offset table of the unpatched build: strings, flags, clocks, view and slot state."
---
# Runtime Memory Map & Real-Mode Offsets

**The memory map is split across five files; this file lists its files, states the conventions below, and holds the `DGROUP` table (§ 1).** Other notes keep subject tables of their own, such as the file-name strings in [`startup.md` § 4](startup.md#4-primary-asset-dependencies). The evidence behind a row (disassembly, live samples, provenance) lives in [`research/playone-exe/`](./) and is linked from the row; it is not restated here. Tier names come from the list `EVIDENTIARY_TIERS` in [`python/scripts/formats_docs/catalog.py`](../../python/scripts/formats_docs/catalog.py) and defined in [`SPEC.md` § 2.4](../../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).

| File | Holds | Anchors defined |
|---|---|---|
| [`memory-map.md`](memory-map.md) | § 1: `DGROUP` (`DS`) offsets of the unpatched build | |
| [`memory-map-patch3.md`](memory-map-patch3.md) | § 1.1: Patch #3 counterparts of § 1, § 3 and `[MEM-PALETTE]` rows, with the unmapped ones marked | |
| [`memory-map-runtime.md`](memory-map-runtime.md) | § 2: runtime capture anchors | `[MEM-VSYNC-03DA]`, `[MEM-FLM-TICK]`, `[MEM-CAMERA-RIG]`, `[MEM-ACTOR-TABLE]` |
| [`memory-map-vm.md`](memory-map-vm.md) | § 3: the SOD display-list VM's work segment and its code anchors | `[MEM-SOD-VM]`, `[MEM-SOD-ANCHOR-TABLE]` |
| [`memory-map-main.md`](memory-map-main.md) | `DS` data offsets, code addresses and the resident mixer setter: film state and variables, palette, view setup, light, matrix and draw routines | `[MEM-FLM-VARS]`, `[MEM-PALETTE]` |

`[MEM-UNPACK-LOCKOUT]` is defined in [`memory.md` § 3.4](memory.md#34-lzexe-unpack-lockout--mem-unpack-lockout); [`doc_anchors.py`](../../python/stunt_reel/doc_anchors.py) names each anchor's home.

* **Target Binary**: `PLAYONE.EXE` (Unpacked LZEXE 0.91 image)
* **Image Dump Base**: paragraph `0x0D51` (file offset `0xD910` in the unpacked image). This is the snapshot base used by earlier dumps, **not** the runtime `DS`. In the captured session `CS = 0x0F17` and `DS = 0x1575` (DOSBox-X; `DS = 0x0F46` under dosbox-automation); table offsets are `DS`-relative. See [`memory.md` § 1](memory.md#1-segment-architecture--dgroup-map).
* **Linear Address Formula**:
  $$\text{Address}_{\text{linear}} = (\text{Segment} \ll 4) + \text{Offset} = (\text{Segment} \times 16) + \text{Offset}$$

---

## 1. DGROUP Memory Reference Table

| Offset in `DS` | Evidentiary Tier | Data Type | Purpose / Value | Anchor |
|---|---|---|---|---|
| `0x0584` | `[Established]` | `u16[]` | Dispatch table of the ground and collision probe `0x240A`, by scenery node type (the draw walk's is `0x554`): type 10 (object) `0x257A`, 14 (ground leaf) `0x2631` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x05AC` | `[Established]` | String (null-term) | `"game.cfg"` — Hardware configuration file | |
| `0x05B5` | `[Established]` | String (null-term) | `"game.var"` — Game variables definition | |
| `0x05BE` | `[Established]` | String (null-term) | `"install.exe"` — Setup utility executable | |
| `0x05CA` | `[Established]` | String (null-term) | `"pfont.bin"` — UI font bitmap and metrics | |
| `0x05D4` | `[Established]` | String (null-term) | `"pilots"` — Pilot profiles directory | |
| `0x05DB` | `[Established]` | String (null-term) | `"res\*.res"` — Core resource archive wildcard | |
| `0x065D` | `[Established]` | String (`$`-term) | `"Not enough memory.  Stunt Island requires 570,000 bytes free."` | |
| `0x069B` | `[Established]` | String (`$`-term) | `"Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."` | |
| `0x09FC..0x0A13` | `[Established]` | `u16[3]` × 4 | Dispatch tables of the probe's walk of collision records (shape header word `+0xA`), by record type 0, 2, 4, one table per walk context: `0x9FC` = `0x28DB`, `0x2979`, `0x2A96`; `0xA02` = `0x2C2D`, `0x2B2A`, `0x2CF6`; `0xA08` = `0x2DFE`, `0x2CFE`, `0x2CF6`; `0xA0E` = `0x2EC8`, `0x2CFA`, `0x2CF6`. Types 0 and 4 are 12-byte records, type 2 the 16-byte box, which `0x2979` tests through `0x3047` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x0A58` | `[Established]` | String (null-term) | `"VAULT\*.*"` — Search pattern for film dialog | |
| `0x0A62` | `[Established]` | String (null-term) | `"LOAD FILM"` — File dialog header string | |
| `0x0AAB` | `[Established]` | Buffer (128B) | Destination buffer for selected film path | |
| `0x0C10` | `[Hypothesis]` | Struct (32B) | Active camera rig descriptor; layout comes from the offline mock, not from `PLAYONE.EXE` (see [§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-CAMERA-RIG]` |
| `0x0C50` | `[Hypothesis]` | Far Pointer (32b) | Heap pointer to dynamic actor channel table; offset comes from the offline mock (see [§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-ACTOR-TABLE]` |
| `0x0C5E` | `[Bounded Observation]` | Code Offset | Post-`0x03DA` retrace breakpoint target. **Static identity conflicts with the entry point — needs live re-verification** (see [§ 2](memory-map-runtime.md#2-runtime-dynamic-capture-anchors)) | `# [MEM-VSYNC-03DA]` |
| `0x0C60` | `[Superseded]` | — | Retired historic tick-counter label; no code references `DGROUP:0x0C60` (see `0x4896`) | |
| `0x2263` | `[Established]` | `u8` | Active display mode flag | |
| `0x2264` | `[Established]` | `u8` | Sound hardware driver mode | |
| `0x2265` | `[Established]` | `u8` | Audio playback channel flag | |
| `0x2272` | `[Established]` | `u8` | Playback-active flag gating the `0x22B8` increment | `# [MEM-FLM-TICK]` |
| `0x2294`, `0x2296`, `0x2298`, `0x229A` | `[Established]` | `i16` x 4 | Inclusive clip rectangle (left, right, top, bottom) the credits text is centred in at `0x0F84`; the film view is `0..319` by `0..184` ([`pfont.md` § 3.2](../formats/auxiliary/pfont.md#32-drawing-the-credits)) | |
| `0x22A0`, `0x22A2` | `[Established]` | `u16` x 2 | Frustum factors of the cull `0x1B0C`, Q16 per unit of depth: a point passes while `\|x\| ≤ (z + (r >> [0x229E])/2)·[0x22A0]/65536 + r·[0x229C]/65536`, and the same for `y` with `[0x22A2]` (`0x1B43..0x1B67`); live 40960 and 23552 in `CTRY.FLM` and `FLIP.FLM` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) _Source: [the #512 breaks](../../work/2026-11/512_altitude-cutoff/journal.md#2026-11-16-the-shadows-cull-the-display-list-run-and-stuntexes-shadow-draw)._ | |
| `0x22B8` | `[Established]` | `u16` | Global 50 Hz timer tick (incremented by the INT 8 path while `0x2272` is set) | `# [MEM-FLM-TICK]` |
| `0x22C4` | `[Established]` | `u16` | Stored PSP segment address: written at image `0x0C78` (`mov [0x22C4], es`, right after `DS` is set to `0x0D51`); read at `0x0CF2`/`0x0CFA` for the free-memory check against `PSP:[2]` | |
| `0x22CA`, `0x22CC` | `[Supported Inference]` | `u16` x 2 | Segments of the two composed pages, swapped every render; after a finished copy, rows 0–191 of `A000` equal one of them (rows 192–199, the button bar, are drawn on `A000` directly). A page with bands from each is torn ([`capture-dosbox-automation.md` § 4.5](capture-dosbox-automation.md#45-torn-pages-and-the-dac-lag)) | |
| `0x22CE` | `[Established]` | `u16` | Preserved `SS` register during `INSTALL.EXE` child execution: written at image `0x0C94`, restored at `0x0CC4` around the `int 21h AX=4B00h` EXEC of `DS:0x05BE` (`install.exe`) at `0x0CBD` | |
| `0x22D0` | `[Established]` | `u16` | Preserved `SP` register during `INSTALL.EXE` child execution: written at image `0x0C98`, restored at `0x0CC8` around the same EXEC | |
| `0x2285` | `[Supported Inference]` | `u8` | View-direction selector read by the view setup at `0x126F`: 1, 2 and 3 turn the camera's angle words a quarter or half turn (`0x1289..0x12A3`), other nonzero values call `0x4B03`. The only writer in a linear decode of the image is `mov byte [0x2285], 0` at `0x49F3`, so film playback draws with 0 | |
| `0x22DE` | `[Established]` | `u16` | Near pointer to the view camera's slot record, `[0x4888 + 2 × view_obj + 0x2E]`, stored by the view setup at `0x1206`; the scene walk skips the actor draw for this slot (`0x1E26`). Live on `INTRO.FLM`: `0x3994` (slot 1) at ticks 2678-2766, `0x3AA2` (slot 4) at 2801 ([`film-segments.md` § 2.1](../parity/film-segments.md#21-held-sand-shots-at-ticks-2690-2850)) | |
| `0x22F0` | `[Established]` | `u16` | Slot record the probe `0x240A` is filling (`0x1487`, `0x240E`) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x22F4` | `[Established]` | `i32[3]`, `i32`, `i32` | The probe `0x240A`'s sphere, filled by `0x14D5` (`0x148C`): centre at the midpoint of the slot's position `+0x04..+0x0F` and `+0x24..+0x2F`, radius `0x2300` (the larger half-displacement plus the shape radius), shape radius `0x2304`; the cube nodes (`0x2547`) compare against the radius's high word `0x2302` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) _Source: [the #512 breaks](../../work/2026-11/512_altitude-cutoff/journal.md#2026-11-16-the-shadows-cull-the-display-list-run-and-stuntexes-shadow-draw)._ | |
| `0x2346` | `[Established]` | `u16[]` | Pending-object list heads, indexed by byte offset: `OP_IPG` type 4 (image `0xB54C`) skips a zero head, else hands the offset to `0x1B75`, which takes the head (`xchg di, [bx+0x2346]`) and draws the list | _Source: [the generators read](../../work/2026-11/272_generator-model-frame/journal.md#2026-11-11-the-raw-coordinate-generators-read-statically)._ |
| `0x2A68` | `[Established]` | `i32[3]` | View eye, 16.16 fixed-point metres in `PLAYONE`'s axes (x and y negated against `[I1]`): `0x1251..0x125E` copy the slot record's `+0x04..+0x0F` here each frame; the ground-leaf back-face test (`0x23C8`) and the scene walk (`0x1DD9`, `0x1E43`) read it. The record's angle words `+0x10`, `+0x12`, `+0x14` (roll, pitch, yaw in binary angle units, `[Bounded Observation]` from matching our camera, [`film-segments.md` § 2.1](../parity/film-segments.md#21-held-sand-shots-at-ticks-2690-2850)) go to the rotation builder at `0x12A7` | |
| `0x2B2A` | `[Established]` | `0x5A`-byte records × 80 | Slot records, 40 for `0x474A` then 40 for `0x4888` (`0x3729..0x376B`); zero in the load image. `+1` is the create's `type_flags` (`0x3CFD`); `+0x1E` the ground-leaf plane pointer, `+0x20/+0x22` the box-top height, `+0x18/+0x1A` the hit object node and `+0x1C/+0x1D` its box codes, all from `0x240A` ([`sod-vm-frame.md` § 9.1](sod-vm-frame.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x4758` | `[Established]` | `u16` | Field `+0x0E` of the sibling `0x474A` struct; reads 0 during playback — **not** the film clock | `# [MEM-FLM-TICK]` |
| `0x4896` | `[Established]` | `u16` | Active film clock in 50 Hz ticks (struct base `0x4888` + `0x0E`); ends at the film's authored total and holds there; equals `0x22B8` on every frame-locked read until it holds, see below | `# [MEM-FLM-TICK]` |
| `0x4F02` | `[Established]` | `u8[128]` | `PFONT.BIN` width table, indexed by character code at `0x58D0` ([`pfont.md`](../formats/auxiliary/pfont.md)) | |
| image offset + `0x8240` | `[Bounded Observation]` | Rule | Relocation: `runtime_linear = image_offset + 0x8240` (`DGROUP` image `0xD510` -> segment `0x1575`); VM `CS:IP` = image - `0x8240`; see [`memory.md` § 4](memory.md#4-image-to-memory-relocation-and-a-candidate-embedded-data-region) | |

Rows `0x22C4`, `0x22CE` and `0x22D0` were promoted from `[Supported Inference]` to `[Established]` on 2026-10-23. A Capstone 16-bit decode of the whole unpacked image found exactly those instructions referencing them, all inside the entry routine `0x0C5E`, and raw word matches elsewhere are not instruction operands. Offsets are load-image offsets (see [`startup.md` § 5](startup.md#5-reproducing-the-static-analysis)). The EXEC runs when the command line starts with `?` (`0x0C90`) or when opening `game.cfg` (`DS:0x05AC`, call at `0x0CD2`) fails. The `entry` listing in rea/Ghidra matches the same instructions at analysis address `0x10000 +` image offset.
