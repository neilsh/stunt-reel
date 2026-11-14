---
summary: "Offset tables for `PLAYONE.EXE` `DGROUP` and the SOD VM work segment on the unpatched and Patch #3 builds, defining most [MEM-*] anchors, such as [MEM-FLM-TICK], [MEM-SOD-VM] and [MEM-PALETTE]."
---
# Runtime Memory Map & Real-Mode Offsets

**This file owns every `DGROUP` / work-segment offset table and every `# [MEM-*]` anchor.** The evidence behind a row (disassembly, live samples, provenance) lives in [`research/playone-exe/`](./) and is linked from the row; it is not restated here. Tier names come from the enum owned by [`python/scripts/verify_formats_docs.py`](../../python/scripts/verify_formats_docs.py) (`EVIDENTIARY_TIERS`) and defined in [`SPEC.md` § 2.4](../../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).

* **Target Binary**: `PLAYONE.EXE` (Unpacked LZEXE 0.91 image)
* **Image Dump Base**: paragraph `0x0D51` (file offset `0xD910` in the unpacked image). This is the snapshot base used by earlier dumps, **not** the runtime `DS`. In the captured session `CS = 0x0F17` and `DS = 0x1575` (DOSBox-X; `DS = 0x0F46` under dosbox-automation); table offsets are `DS`-relative. See [`memory.md` § 1](memory.md#1-segment-architecture--dgroup-map).
* **Linear Address Formula**:
  $$\text{Address}_{\text{linear}} = (\text{Segment} \ll 4) + \text{Offset} = (\text{Segment} \times 16) + \text{Offset}$$

---

## 1. DGROUP Memory Reference Table

| Offset in `DS` | Evidentiary Tier | Data Type | Purpose / Value | Anchor |
|---|---|---|---|---|
| `0x0584` | `[Established]` | `u16[]` | Dispatch table of the ground and collision probe `0x240A`, by scenery node type (the draw walk's is `0x554`): type 10 (object) `0x257A`, 14 (ground leaf) `0x2631` ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x05AC` | `[Established]` | String (null-term) | `"game.cfg"` — Hardware configuration file | |
| `0x05B5` | `[Established]` | String (null-term) | `"game.var"` — Game variables definition | |
| `0x05BE` | `[Established]` | String (null-term) | `"install.exe"` — Setup utility executable | |
| `0x05CA` | `[Established]` | String (null-term) | `"pfont.bin"` — UI font bitmap and metrics | |
| `0x05D4` | `[Established]` | String (null-term) | `"pilots"` — Pilot profiles directory | |
| `0x05DB` | `[Established]` | String (null-term) | `"res\*.res"` — Core resource archive wildcard | |
| `0x065D` | `[Established]` | String (`$`-term) | `"Not enough memory.  Stunt Island requires 570,000 bytes free."` | |
| `0x069B` | `[Established]` | String (`$`-term) | `"Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."` | |
| `0x09FC`, `0x0A08` | `[Established]` | `u16[]` | Dispatch tables of the probe's walk of an object shape's collision boxes (shape header word `+0xA`, 16-byte records); type 2 is the box test `0x2979` ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x0A58` | `[Established]` | String (null-term) | `"VAULT\*.*"` — Search pattern for film dialog | |
| `0x0A62` | `[Established]` | String (null-term) | `"LOAD FILM"` — File dialog header string | |
| `0x0AAB` | `[Established]` | Buffer (128B) | Destination buffer for selected film path | |
| `0x0C10` | `[Hypothesis]` | Struct (32B) | Active camera rig descriptor; layout comes from the offline mock, not from `PLAYONE.EXE` (see § 2) | `# [MEM-CAMERA-RIG]` |
| `0x0C50` | `[Hypothesis]` | Far Pointer (32b) | Heap pointer to dynamic actor channel table; offset comes from the offline mock (see § 2) | `# [MEM-ACTOR-TABLE]` |
| `0x0C5E` | `[Bounded Observation]` | Code Offset | Post-`0x03DA` retrace breakpoint target. **Static identity conflicts with the entry point — needs live re-verification** (see § 2) | `# [MEM-VSYNC-03DA]` |
| `0x0C60` | `[Superseded]` | — | Retired historic tick-counter label; no code references `DGROUP:0x0C60` (see `0x4896`) | |
| `0x2263` | `[Established]` | `u8` | Active display mode flag | |
| `0x2264` | `[Established]` | `u8` | Sound hardware driver mode | |
| `0x2265` | `[Established]` | `u8` | Audio playback channel flag | |
| `0x2272` | `[Established]` | `u8` | Playback-active flag gating the `0x22B8` increment | `# [MEM-FLM-TICK]` |
| `0x2294`, `0x2296`, `0x2298`, `0x229A` | `[Established]` | `i16` x 4 | Inclusive clip rectangle (left, right, top, bottom) the credits text is centred in at `0x0F84`; the film view is `0..319` by `0..184` ([`pfont.md` § 3.2](../formats/auxiliary/pfont.md#32-drawing-the-credits)) | |
| `0x22B8` | `[Established]` | `u16` | Global 50 Hz timer tick (incremented by the INT 8 path while `0x2272` is set) | `# [MEM-FLM-TICK]` |
| `0x22C4` | `[Established]` | `u16` | Stored PSP segment address: written at image `0x0C78` (`mov [0x22C4], es`, right after `DS` is set to `0x0D51`); read at `0x0CF2`/`0x0CFA` for the free-memory check against `PSP:[2]` | |
| `0x22CA`, `0x22CC` | `[Supported Inference]` | `u16` x 2 | Segments of the two composed pages, swapped every render; after a finished copy, rows 0–191 of `A000` equal one of them (rows 192–199, the button bar, are drawn on `A000` directly). A page with bands from each is torn ([`capture-dosbox-automation.md` § 4.5](capture-dosbox-automation.md#45-torn-pages-and-the-dac-lag)) | |
| `0x22CE` | `[Established]` | `u16` | Preserved `SS` register during `INSTALL.EXE` child execution: written at image `0x0C94`, restored at `0x0CC4` around the `int 21h AX=4B00h` EXEC of `DS:0x05BE` (`install.exe`) at `0x0CBD` | |
| `0x22D0` | `[Established]` | `u16` | Preserved `SP` register during `INSTALL.EXE` child execution: written at image `0x0C98`, restored at `0x0CC8` around the same EXEC | |
| `0x2285` | `[Supported Inference]` | `u8` | View-direction selector read by the view setup at `0x126F`: 1, 2 and 3 turn the camera's angle words a quarter or half turn (`0x1289..0x12A3`), other nonzero values call `0x4B03`. The only writer in a linear decode of the image is `mov byte [0x2285], 0` at `0x49F3`, so film playback draws with 0 | |
| `0x22DE` | `[Established]` | `u16` | Near pointer to the view camera's slot record, `[0x4888 + 2 × view_obj + 0x2E]`, stored by the view setup at `0x1206`; the scene walk skips the actor draw for this slot (`0x1E26`). Live on `INTRO.FLM`: `0x3994` (slot 1) at ticks 2678-2766, `0x3AA2` (slot 4) at 2801 ([`film-segments.md` § 2.1](../parity/film-segments.md#21-held-sand-shots-at-ticks-2690-2850)) | |
| `0x22F0` | `[Established]` | `u16` | Slot record the probe `0x240A` is filling (`0x1487`, `0x240E`) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x2346` | `[Established]` | `u16[]` | Pending-object list heads, indexed by byte offset: `OP_IPG` type 4 (image `0xB54C`) skips a zero head, else hands the offset to `0x1B75`, which takes the head (`xchg di, [bx+0x2346]`) and draws the list | _Source: [the generators read](../../work/2026-11/272_generator-model-frame/journal.md#2026-11-11-the-raw-coordinate-generators-read-statically)._ |
| `0x2A68` | `[Established]` | `i32[3]` | View eye, 16.16 fixed-point metres in `PLAYONE`'s axes (x and y negated against `[I1]`): `0x1251..0x125E` copy the slot record's `+0x04..+0x0F` here each frame; the ground-leaf back-face test (`0x23C8`) and the scene walk (`0x1DD9`, `0x1E43`) read it. The record's angle words `+0x10`, `+0x12`, `+0x14` (roll, pitch, yaw in binary angle units, `[Bounded Observation]` from matching our camera, [`film-segments.md` § 2.1](../parity/film-segments.md#21-held-sand-shots-at-ticks-2690-2850)) go to the rotation builder at `0x12A7` | |
| `0x2B2A` | `[Established]` | `0x5A`-byte records × 80 | Slot records, 40 for `0x474A` then 40 for `0x4888` (`0x3729..0x376B`); zero in the load image. `+1` is the create's `type_flags` (`0x3CFD`); `+0x1E` the ground-leaf plane pointer, `+0x20/+0x22` the box-top height, `+0x18/+0x1A` the hit object node and `+0x1C/+0x1D` its box codes, all from `0x240A` ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x4758` | `[Established]` | `u16` | Field `+0x0E` of the sibling `0x474A` struct; reads 0 during playback — **not** the film clock | `# [MEM-FLM-TICK]` |
| `0x4896` | `[Established]` | `u16` | Active film clock in 50 Hz ticks (struct base `0x4888` + `0x0E`); ends at the film's authored total and holds there; equals `0x22B8` on every frame-locked read until it holds, see below | `# [MEM-FLM-TICK]` |
| `0x4F02` | `[Established]` | `u8[128]` | `PFONT.BIN` width table, indexed by character code at `0x58D0` ([`pfont.md`](../formats/auxiliary/pfont.md)) | |
| image offset + `0x8240` | `[Bounded Observation]` | Rule | Relocation: `runtime_linear = image_offset + 0x8240` (`DGROUP` image `0xD510` -> segment `0x1575`); VM `CS:IP` = image - `0x8240`; see [`memory.md` § 4](memory.md#4-image-to-memory-relocation-and-a-candidate-embedded-data-region) | |

Rows `0x22C4`, `0x22CE` and `0x22D0` were promoted from `[Supported Inference]` to `[Established]` on 2026-10-23. A Capstone 16-bit decode of the whole unpacked image found exactly those instructions referencing them, all inside the entry routine `0x0C5E`, and raw word matches elsewhere are not instruction operands. Offsets are load-image offsets (see [`startup.md` § 5](startup.md#5-reproducing-the-static-analysis)). The EXEC runs when the command line starts with `?` (`0x0C90`) or when opening `game.cfg` (`DS:0x05AC`, call at `0x0CD2`) fails. The `entry` listing in rea/Ghidra matches the same instructions at analysis address `0x10000 +` image offset.

### 1.1 Patch #3 build

Every row in this file is for the unpatched 1992 `PLAYONE.EXE` (102,703 bytes, sha256 `3c93493c…`). Patch #3's `PLAYONE.EXE` (97,790 bytes, `fc532c94…`) is relinked: `DGROUP` is paragraph `0x0C71` (`DS = 0x0E66` under dosbox-automation), the display-list VM segment `0x0754` (was `0x0824`) and the work segment `0x14BF` (was `0x15D4`), and the `DGROUP` data moved by 12 different shifts, so no single shift maps it. The tables below give every row of § 1, § 3 and `[MEM-PALETTE]` on both builds. They come from pairing the two images function by function with `mise run pair-builds`; the method, the counts and what did not pair are in [`patch3.md` § 4](patch3.md#4-function-pairing-the-whole-map). Patched offsets are `[Supported Inference]` (static) unless a row says otherwise. The unpatched row's own tier is unchanged.

The **Evidence** column says how each patched offset was found. *N refs* means N memory operands name the offset in paired instructions and all N give this answer. *N disp* means N paired displacements off a base or index register (`[bx + 0x4F02]`, an array or table base) do. *N imm* means N paired immediates equal to the offset (a pointer loaded into a register) do. *Bracketed* means no instruction names it and the nearest named offsets on both sides share one shift. *Bytes* means the 16 initialised bytes at the two offsets are equal.

**`DGROUP` (`DS`) offsets.**

| Unpatched | Patch #3 | Evidence | Row | Anchor |
|---|---|---|---|---|
| `0x0542` | `0x05BE` | 13 refs | Segment of the display-list work segment (`mov es, [0x542]` before `es:[0x8078]`) | |
| `0x056C` | `0x05E8` | 1 disp (`jmp [bx+0x56C]` at `0x213D`, `jmp [bx+0x5E8]` at patched `0x2250`, in the paired `SP_1NODE` handlers; [`lod.md`](lod.md) section 1.2) | Scene-walker dispatch table entered by a near `SP_1NODE` | |
| `0x05AC`, `0x05B5`, `0x05BE`, `0x05CA`, `0x05D4`, `0x05DB` | `0x0628`, `0x0631`, `0x063A`, `0x0646`, `0x0650`, `0x0657` | 1, 1, 1, 1, 2, 1 imm; bytes for each | `game.cfg`, `game.var`, `install.exe`, `pfont.bin`, `pilots`, `res\*.res` | |
| `0x065D`, `0x069B` | `0x06D9`, `0x0717` | 1 imm each; bytes | Memory and disk-space messages | |
| `0x09DE`, `0x09EA` | `0x0A62`, `0x0A6E` | 1 imm, 2 imm; bytes | Sky colour pairs; blended zenith and horizon | `# [MEM-PALETTE]` |
| `0x09F0`, `0x09F6` | `0x0A74`, `0x0A7A` | 1 imm each; the 6 bytes of each entry match | Day and night colours of entries 213–214 | `# [MEM-PALETTE]` |
| `0x0A58`, `0x0A62` | `0x0ADC`, `0x0AE6` | 2 imm each; bytes | `VAULT\*.*`, `LOAD FILM` | |
| `0x0AAB` | `0x0B1E` | 2 imm | Selected film path buffer | |
| `0x0C10` | `0x0D22` | 2 imm: `mov di, 0x0C10` before `jmp 0x5404` pairs with `mov di, 0x0D22` before `jmp 0x55FB`. No memory operand names it, and its neighbours moved `+0x74`, not `+0x112` | The address the code passes; that it holds a camera rig stays `[Hypothesis]` (§ 2) | `# [MEM-CAMERA-RIG]` |
| `0x0C50` | `0x0CC4` | 1 imm; bytes | Actor-table far pointer, `[Hypothesis]` (§ 2) | `# [MEM-ACTOR-TABLE]` |
| `0x0CA0` | `0x0D14`, `[Hypothesis]` | bracketed; the bytes differ | Local stage block, `[Hypothesis]` (§ 2) | `# [MEM-ACTOR-TABLE]` |
| `0x0C60` | unmapped | No instruction names it in either build, so nothing pairs it | Retired label | |
| `0x10A4` | `0x0E26` | 1 imm (`mov si, 0x10A4` before the copy to `0x2240`); its 17 near pointers are the 17 paired driver entries (`0x7B70` → `0x6E77`, …) | Graphics driver vector source | `# [MEM-PALETTE]` |
| `0x2240` | `0x1BC6` | 1 ref; bytes | Driver vector table | `# [MEM-PALETTE]` |
| `0x225A` | `0x1BE0` | 12 refs | Text driver slot | |
| `0x2263`, `0x2264`, `0x2265` | `0x1BE9`, `0x1BEA`, `0x1BEB` | 11, 4, 3 refs | Display mode, sound driver mode, audio channel flags | |
| `0x2272` | `0x1BF8` | 20 refs | Playback-active flag | `# [MEM-FLM-TICK]` |
| `0x2275` | `0x1BFB` | 2 refs | Video-mode flag | `# [MEM-PALETTE]` |
| `0x227A`, `0x227B`, `0x227C`, `0x227D` | `0x1C00`, `0x1C01`, `0x1C02`, `0x1C03` | 9, 3, 3, 2 refs | Screen-faded flag, cached palette inputs | `# [MEM-PALETTE]` |
| `0x2285` | `0x1C0B` | 2 refs; bytes | View-direction selector | |
| `0x2294`, `0x2296`, `0x2298`, `0x229A` | `0x1C1A`, `0x1C1C`, `0x1C1E`, `0x1C20` | 27, 16, 13, 9 refs | Credits clip rectangle | |
| `0x229C`, `0x229E`, `0x22A4` | `0x1C22`, `0x1C24`, `0x1C2A` | 4, 4, 2 refs | Lens mantissa, lens shift count, `0x22A4` | `# [MEM-PALETTE]` |
| `0x22B6` | `0x1C3C` | 2 refs | View-setup scale | `# [MEM-PALETTE]` |
| `0x22B8` | `0x1C3E` | 3 refs; a live capture ([`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets)) | Global 50 Hz tick | `# [MEM-FLM-TICK]` |
| `0x22BC` | `0x1C42` | 1 ref | Var 10 at the previous frame's bank write (`0x1D96`) | `# [MEM-PALETTE]` |
| `0x22C4` | `0x1C4A`, `[Established]` | 3 refs (`mov [0x1C4A], es` in the patched entry routine) | Stored PSP segment | |
| `0x22CA`, `0x22CC` | `0x1C50`, `0x1C52`, `[Bounded Observation]` | 17, 6 refs; a live capture flagged 72 of 1,906 frames torn against 66 of 1,908 unpatched ([`patch3.md` § 3.1](patch3.md#31-composed-pages)) | Composed-page segments | |
| `0x22CE`, `0x22D0` | `0x1C54`, `0x1C56` | 2 refs each | Saved `SS`, `SP` around the `INSTALL.EXE` EXEC | |
| `0x22DE` | `0x1C64` | 2 refs; bytes | View camera's slot record pointer | |
| `0x22EC` | `0x1C72` | 1 ref (`0x215A`, patched `0x226D`; [`lod.md`](lod.md) section 1.2) | `SP_1NODE` stand-in object word | |
| `0x2A68` | `0x23EE` | 4 refs; bytes | View eye | |
| `0x2468` | `0x1DEE` | 3 imm | Base palette | `# [MEM-PALETTE]` |
| `0x2768` | `0x20EE` | 9 imm; a live capture read identical palettes ([`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets)) | Working palette | `# [MEM-PALETTE]` |
| `0x474A` | `0x40D0` | 12 imm | Live film-state struct | `# [MEM-PALETTE]` |
| `0x474A + 0x7E + 2n` (`0x47C8 + 2n`) | `0x40D0 + 0x7E + 2n` (`0x414E + 2n`) | 1 imm on `0x47C8`; the struct moved whole | Live film variables: var 13 `0x47E2` → `0x4168`, vars 14 and 15 `0x47E4`/`0x47E6` → `0x416A`/`0x416C` | `# [MEM-PALETTE]` |
| `0x4758` | `0x40DE` | 8 refs | `0x474A + 0x0E`, not the film clock | `# [MEM-FLM-TICK]` |
| `0x4764`, `0x4778` | `0x40EA`, `0x40FE` | 1 ref, 2 disp | `0x474A + 0x1A` (`view_obj`); per-slot record pointers | `# [MEM-PALETTE]` |
| `0x4888` | `0x420E` | 11 refs | Snapshot struct | `# [MEM-PALETTE]` |
| `0x4896` | `0x421C` | 17 refs (the byte match of [`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets) found 2); a live capture | Active film clock | `# [MEM-FLM-TICK]` |
| `0x48A2`, `0x48B6`, `0x4906` | `0x4228`, `0x423C`, `0x428C` | 1 ref, 1 disp, 1 imm | Snapshot `view_obj`, per-slot pointers, variable copies | `# [MEM-PALETTE]` |
| `0x49C6` | `0x434C` | 3 imm | The recorder's previous variables | `# [MEM-PALETTE]` |
| `0x49EC`, `0x49EE`, `0x49F0` | `0x4372`, `0x4374`, `0x4376` | 4 refs each | Sun or moon direction from var 13 | `# [MEM-PALETTE]` |
| `0x4F02` | `0x4888` | 6 disp | `PFONT.BIN` width table | |

**Work-segment offsets are all unchanged.** The work segment is the same `0x8130` bytes in both images. Of the 165 offsets that the VM segment names through `DS`, 164 are work-segment offsets and pair with themselves; the other, `0x8042`, is read while `DS` is `DGROUP` and moved `-0x67A`. All 50 offsets the main program names through `ES` pair with themselves. The segment's initial bytes are identical except 12 at `0x1952..0x195D`. So the § 3 table holds on the patched build as written: `0x19A8`, `0x41B8`, `0x41C8`/`0x41CA`, `0x41D4..0x41DA`, `0x4450 + n*12`, `0x7468`, `0x806C..0x8070`, `0x8072`, `0x8078`, `0x8082..0x8088`, `0x80C0..0x80CA`, `0x8108..0x810C` and `0x8120..0x8128` each pair at least once. The anchor table (`0x0000`, `0x0004 + n*0x1C`) is reached through registers, so no operand names it; it is unchanged by the same identity. The segment's runtime paragraph is the load paragraph plus `0x14BF`. On the patched build, read it from `DS:0x05BE`; that is unpatched `DS:0x0542`, and unpatched `0x05BE` holds the `install.exe` string.

**Code addresses**, as load-image offsets. The notebook addresses of `[MEM-SOD-VM]` are image `- 0x6F30`; a VM `CS:IP` is image `- 0x8240` unpatched and `- 0x7540` patched. Each patched address is an aligned instruction of a paired function unless the row says otherwise.

| Unpatched image | Patch #3 image | Row | Anchor |
|---|---|---|---|
| `0x0C5E` | `0x0D70`, the patched header's entry `CS:IP` | Entry point; the per-frame trap conflict of § 2 is unaffected. The only `0x03DA` poll in either image is in the DAC upload, `0x7B79` → `0x6E80` | `# [MEM-VSYNC-03DA]` |
| `0x0C78`, `0x0C90`, `0x0C94`, `0x0C98`, `0x0CBD`, `0x0CC4`, `0x0CC8`, `0x0CD2`, `0x0CF2`, `0x0CFA` | `0x0D8A`, `0x0DA2`, `0x0DA6`, `0x0DAA`, `0x0DCF`, `0x0DD6`, `0x0DDA`, `0x0DE4`, `0x0E04`, `0x0E0C` | Entry-routine instructions cited in § 1 | |
| `0x0EE6`, `0x0EE9` | `0x0FFA`, `0x0FFD` | Per-frame film render step | `# [MEM-PALETTE]` |
| `0x0F84`, `0x58D0` | `0x1097`, `0x5AC7` | Credits centring, string width | |
| `0x0FD2` | `0x10E5` | Palette build | `# [MEM-PALETTE]` |
| `0x11F8`, `0x11FC`, `0x122E`, `0x1238`, `0x123D` | `0x130B`, `0x130F`, `0x1341`, `0x134B`, `0x1350` | View setup and its lens stores | `# [MEM-PALETTE]` |
| `0x1251` | `0x1364` | View setup: eye copy from the view slot record (the `view-slot` plan's break) | |
| `0x12DC`, `0x12E3`, `0x12F8` | `0x13EF`, `0x13F6`, `0x140B` | Lens zoom of the view matrix | `# [MEM-PALETTE]` |
| `0x136F` | `0x1482` | Film-variable interpolation | `# [MEM-PALETTE]` |
| `0x196C` | `0x1A7F` | World light from var 13 (the same 14 instructions) | `# [MEM-PALETTE]` |
| `0x1D96` | `0x1EA9` | Vars 10 and 12 to the work segment | `# [MEM-PALETTE]` |
| `0x39B0`, `0x39D0` | `0x3AC3`, `0x3AE3` | Film-state snapshot and its variable copy | `# [MEM-PALETTE]` |
| `0x3D54`, `0x3D7F` | `0x3E67`, `0x3E92` | `var_set` and `view_obj` handlers | `# [MEM-PALETTE]` |
| `0x42F5` | `0x4428` | Film recorder | `# [MEM-PALETTE]` |
| `0x4A29`, `0x4A32`, `0x4A35` | `0x4B68`, `0x4B71`, `0x4B74` | Frame loop: lens scale, `view_obj` load, render-step call | `# [MEM-PALETTE]` |
| `0x6E1B` | unmapped | The alternate video-mode path. Its function, `0x6DCB`, is one of the 12 unpatched display-driver functions with no patched counterpart; the patch dropped Tandy and CGA graphics | `# [MEM-PALETTE]` |
| `0x737B` | `0x65A1` | `int 10h` mode `0x13` | `# [MEM-PALETTE]` |
| `0x7B70` | `0x6E77` | VGA DAC upload | `# [MEM-PALETTE]` |
| `0x8240 + 9n` (notebook `0x1310 + 9n`) | `0x7540 + 9n` for opcodes `9n` up to `0x0333`; unpatched opcode `0x033C` has no patched slot; unpatched opcode `0x0345 + 9k` is patched `0x033C + 9k` | Dispatch slots: 108 unpatched, 107 patched, paired through their handlers ([`patch3.md` § 4.1](patch3.md#41-the-patched-build-has-one-dispatch-slot-fewer)) | `# [MEM-SOD-VM]` |
| `0x843E` (notebook `0x150E`) | `0x773E` | `OP_ANIMATE` (`0x01F8`) slot jump; below `0x033C`, so the same slot | `# [FMT-SOD-ANIMATE]` |
| `0x8A1C`, `0x8C45` (VM `0x07DC`, `0x0A05`) | `0x7D13`, `0x7F3C` (VM `0x07D3`, `0x09FC`) | Frame-routine targets chosen by the video-mode flag | `# [MEM-PALETTE]` |
| `0x908E` | `0x8385` | Sun projection through the camera matrix | `# [MEM-PALETTE]` |
| `0x9100`, `0x9106` | `0x83F7`, `0x83FD` | Light setup entries | |
| `0x94D8`, `0x95C0`, `0x9BB3`, `0x9BCC`, `0x9BE5` | `0x87CF`, `0x88B7`, `0x8DBE`, `0x8DD7`, `0x8DF0` | `REJVEC`, `REJ2D`, `BVIS`, `IFVIS` and `BZLT` handlers, byte for byte | `# [FMT-SOD-IFVIS]` |
| `0xA9DC` (notebook `0x3AAC`) | `0x9BE7` | `OP_ANIMATE` handler | `# [FMT-SOD-ANIMATE]` |
| `0xAD88`, `0xAE66` (notebook `0x3E58`, `0x3F36`) | `0x9F93`, `0xA071` | `OP_TAP` handler, `OP_HUGETAP` entry | `# [MEM-SOD-VM]` |
| `0xB85D` (notebook `0x492D`) | `0xAA68` | Anchor-cache invalidation | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x1DEA:0x05B1` (image `0x1E451`) | `0x1CD5:0x0B67` (image `0x1D8B7`), by its one paired far call, from `0x104B` (unpatched call site `0x0F3A`) | PCM mixer var-11 setter. The mixer segment was rewritten (2 of its 30 functions pair): the patched setter takes var 11 in `AX` and a channel in `BX` and stores it at `+0x12` of that channel's record in segment `0x1F57`, so `cs:[0x49]` and `cs:[0xD7]` have no patched counterpart | `# [MEM-PALETTE]` |

The relocation rule of § 1 (`image + 0x8240` in the DOSBox-X session) adds the load paragraph times 16, which depends on the emulator, not the build. Its VM `CS:IP` term is the VM segment's image offset: `0x7540` (paragraph `0x0754`) on the patched build.

---

## 2. Runtime Dynamic Capture Anchors

### # [MEM-VSYNC-03DA]
* **I/O Port**: `0x03DA` (VGA Input Status Register 1)
* **Routine**: Vertical retrace polling loop (`in al, dx; test al, 08h`).
* **Protocol** (`[Bounded Observation]`, one film, `CTRY.FLM`): a one-time breakpoint `BPIO 03DA` isolates the polling loop address; execution breakpoint `BP <CS:IP>` is set immediately *after* the loop. The harness uses `BP 0D51:0C5E` plus `RUN`, which returns once per rendered frame, so one `MEMDUMPBIN A000:0000` per hit is a whole frame. `VRT` cannot substitute for it (stepping a Mode 13h guest exits the emulator with `0xC0000409`). Run-by-run evidence: [`capture.md`](capture.md) and [`memory.md` § 3.1](memory.md#31-post-retrace-vertical-blank-trap).
* **Evidentiary Tier**: runtime behaviour `[Bounded Observation]`; static identification of the trap address `[Hypothesis]` (conflict below).

> [!WARNING]
> **Unresolved conflict — needs live re-verification.** The address `0C5E` is described three incompatible ways:
> 1. [`startup.md`](startup.md) § 1 gives the unpacked **entry point** as `CS:IP = 0000:0C5E` (executed once, followed by the command-tail parser at `0x0C7C`).
> 2. The capture harness uses `BP 0D51:0C5E` as a **per-frame** loop boundary, and 140 consecutive `CTRY.FLM` frames were captured that way.
> 3. [`memory.md` § 3.1](memory.md#31-post-retrace-vertical-blank-trap) lists a polling loop at `0D51:0C48..0C5E` ending in `call render_frame_flush`, which cannot also be the entry point.
>
> The segment is also suspect: `0x0D51` is the image-dump base, while the captured session ran at `CS = 0x0F17`, so `0D51:0C5E` (linear `0xE16E`) is not `CS:0C5E` (linear `0xFDCE`). The breakpoint demonstrably stops once per frame, but the static meaning of that address is unproven. To resolve: with the guest running film playback, run `BPIO 03DA`, record the `CS:IP` it reports, disassemble around it, and compare its linear address to `0D51:0C5E`. Until then, cite the harness behaviour, not the address's meaning.

### # [MEM-FLM-TICK]
* **Scope**: Runtime `DS` offsets `0x22B8` (global 50 Hz tick), `0x4896` (active film clock, struct base `0x4888` + `0x0E`) and `0x2272` (playback flag); rows in § 1. `0x4758` and the retired `0x0C60` label are not the film clock.
* **Data Type**: 16-bit unsigned integer (`u16`).
* **Contract**: the INT 8 path increments `0x22B8` once per 20 ms tick while `0x2272` is set; the film clock `0x4896` advances with it during the film, stops at the authored total (`1342` for `CTRY.FLM`) and holds, while `0x22B8` keeps counting. Read in the same emulated frame, `0x4896` equals `0x22B8` on every frame from playback start until the film clock holds (`[Bounded Observation]`: `CTRY.FLM` to 1342, `INTRO.FLM` to 3822); the 2–3 behind or 5 ahead seen through the debugger harness is read latency, not a stored offset (`[Supported Inference]`, [`memory.md` § 3.2](memory.md#32-tick-counter-evidence)). A rendered frame may advance several ticks (Mode 13h refreshes at 70 Hz and rendering can drop frames), so the streamer gates snapshot capture on:
  $$\text{current\_tick} > \text{last\_captured\_tick}$$
  preventing duplicate frame capture.
* **Evidence**: the only copy of the static-handler and live-sampling evidence is [`memory.md` § 3.2](memory.md#32-tick-counter-evidence). Other documents link there instead of restating it.
* **Evidentiary Tier**: `[Established]` (static disassembly plus live DOSBox-X sampling).

### # [MEM-CAMERA-RIG]
* **Segment / Scope**: Runtime `DS` offset `0x0C10` (the concrete `DS` value depends on the load base; in the captured session `DS = 0x1575`).
* **Evidentiary Tier**: `[Hypothesis]`. The layout below is what `MockTransport._write_tick_state` writes and `TrajectoryStreamer.decode_camera_from_memory` reads (the retired `transport.py` and `streamer.py`, removed in #106); it was decoded only against that offline mock. The capture loop never reads the camera rig from a live `PLAYONE.EXE` ([`capture.md` § 3](capture.md#3-working-protocol)), and no disassembly of a consumer exists. The harness also addresses it as `0D51:0C10` although `0x0D51` is not the runtime `DS`. Treat offsets, field types (`f32` vs `16.16 i32`) and the `+0x1C` cut rule as unverified.
* **Byte Layout Specification (32 bytes)**:
  * `+0x00` (`f32` / `16.16 i32` LE, 4B): Camera Eye World X coordinate in meters `[I1]`.
  * `+0x04` (`f32` / `16.16 i32` LE, 4B): Camera Eye World Y coordinate in meters.
  * `+0x08` (`f32` / `16.16 i32` LE, 4B): Camera Eye World Z coordinate in meters.
  * `+0x0C` (`f32` / `16.16 i32` LE, 4B): Camera Look-At Target X in meters.
  * `+0x10` (`f32` / `16.16 i32` LE, 4B): Camera Look-At Target Y in meters.
  * `+0x14` (`f32` / `16.16 i32` LE, 4B): Camera Look-At Target Z in meters.
  * `+0x18` (`u16` LE, 2B): Integer focal zoom scalar, converted to vertical $\text{FOV}_y$ via:
    $$\text{FOV}_y = 2 \arctan\left(\frac{120.0}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$$
  * `+0x1A` (`u16` LE, 2B): View Roll BAM angle, converted via $\theta = (\text{raw\_u16} / 65536.0) \times 2\pi$.
  * `+0x1C` (`u16` LE, 2B): Active camera rig mode ID (cut triggered if mode changes or $\|\Delta\mathbf{eye}\| > 50\text{ m}$).
  * `+0x1E` (`u16` LE, 2B): Reserved / structure alignment padding.

### # [MEM-ACTOR-TABLE]
* **Segment / Scope**: Dynamic heap buffer addressed by the far pointer at `DS:0x0C50` (or the local stage block at `DS:0x0CA0`).
* **Evidentiary Tier**: `[Hypothesis]`. Two incompatible layouts were previously both labelled `[Established]`; neither is backed by disassembly or a live read.
  * *Layout A* (this file's former table, implemented by `TrajectoryStreamer.decode_actor_from_memory` and written by `MockTransport._write_tick_state`): unit quaternion (`4 × f32`) at `+0x18`, state mask at `+0x28`, joint count at `+0x2A`, joint pairs from `+0x2C`, next-link at `+0x3C`.
  * *Layout B* (the former table in `memory.md`, no code): `3×3` `i16` direction-cosine matrix (or quaternion) at `+0x18`, state mask at `+0x2A`, joint count at `+0x2C`, joint pairs from `+0x2E`, next-link at `+0x3C`.
  * Layout A is retained below because it is the one executable code and tests assumed, but its only source was the offline mock, since removed. Nothing in `research/playone-exe/` records a read of the real table (`capture.md` § 3 states the capture loop deliberately never reads it), and the stored film rotation is BAM-valued (`SPEC.md` § 3.7), so a quaternion field is itself doubtful. Promote only after a live `MEMDUMPBIN` of a populated entry.
* **Byte layout, Layout A (64 bytes per actor entry)**: defined only by [`actor_record.ksy`](../formats/memory/actor_record.ksy) (spike; see [`kaitai-memory-spike.md`](../formats/memory/kaitai-memory-spike.md)). Meaning of the fields: `+0x00` channel id; `+0x04` bound `.SOD` name (NUL-padded); position in signed 16.16 metres `[I1]`; rotation quaternion (normalised, `|‖q‖ - 1| < 1e-4`); state bitmask (visibility, damage, gear, smoke); joint count `N` and `(subobject_id, raw_bam_u16)` pairs; next-actor far pointer as `off:u16, seg:u16`, both zero ends the chain.
* **Traversal guard**: the streamer enforces a bounded node count and cycle detection when following `+0x3C`.

---

## 3. SOD Display-List VM Work Segment (`# [MEM-SOD-VM]`)

The display-list VM runs against a dedicated 64 KB work segment (`0x1DF8` in the captured `CTRY.FLM` session). Offsets are stable; the segment base is runtime-selected. `ES:SI` addresses the bytecode, `DS` the work segment. The Patch #3 build keeps every offset in this section; its code addresses are in [§ 1.1](#11-patch-3-build).

| Offset in work segment | Evidentiary Tier | Data Type | Purpose / Value | Anchor |
|---|---|---|---|---|
| `0x0000` | `[Established]` | 4-byte header | Anchor-table header (record 0 starts at `+0x04`) | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x0004 + n*0x1C` | `[Established]` | 28-byte record | Anchor point `n`: `x/y/z` at `+0x00/+0x02/+0x04`; cache at `+0x06..+0x10`; fields `+0x12/+0x16/+0x1A`; frame stamp `+0x1B` | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x1952` | `[Established]` | `u16` | Span arena pointer: the sliced ops (`OP_DISCSL` `0x9F29`, `OP_PERFDISCSL` `0xA05C` and others) build a span table at it, then move it past the table ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x1954` | `[Established]` | `u16[5]` | `OP_IPG` subtype table, indexed by the type word (0, 2, 4, 6, 8): VM offsets `0x3035`, `0x31DE`, `0x330C`, `0x334D`, `0x3275` (image `0xB275`, `0xB41E`, `0xB54C`, `0xB58D`, `0xB4B5`); these pointers are unpatched-build values, and `0x1952..0x195D` is the range that differs on Patch #3 (§ 1.1), so check the Patch #3 words before relying on them there | _Source: [the generators read](../../work/2026-11/272_generator-model-frame/journal.md#2026-11-11-the-raw-coordinate-generators-read-statically)._ |
| `0x19A8` | `[Established]` | `u8` | Per-frame transform cache counter; incremented by `CS:0x492D` | |
| `0x19AA..0x41A9` | `[Established]` | `i16[5120]` | Q15 sine over 1¼ turns, 4096 entries per turn: the builder at image `0x8725` (`0824:04E5`) reads sine from `0x19AA` and cosine from `0x21AA` (a quarter turn on), indexed by `angle >> 4` | _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| `0x41B8` | `[Established]` | `u16` | `OP_TAP` remaining-count scratch | |
| `0x41C8`, `0x41CA` | `[Established]` | `u16` | Screen-projection center offsets; live `CTRY` session reads 160 and 92 (3D viewport is 185 rows; see `capture.md` § 4) | |
| `0x41EA` | `[Established]` | `u16` | Line colour: written by `LINECOL` (`0x9BAA`), read by the line gateway `0x7FD2` ([`sod-vm.md`](sod-vm.md) section 8.10) | _Source: [the ZLINETO draw path read](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ |
| `0x41EC` | `[Established]` | `u16` | Pen: the register byte offset `MOVETO` (`0x968D`) stores and `ZLINETO` (`0x9696`) draws from | _Source: [the ZLINETO draw path read](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ |
| `0x41D4..0x41DA` | `[Established]` | `i32[3]` | Translation `OP_TAP` adds after `0x80C0` (`0xAE8B`). `[Supported Inference]` that it is the camera's: the anchor cache it fills is per frame, shared by every object ([`sod-vm.md`](sod-vm.md) section 4) | |
| `0x423E + n` | `[Established]` | `u16[]` | Start of the span table a sliced op built for its last operand `n`, 0 when it skipped (the two sliced disc ops store 0 in shadow mode; the other sliced ops do not test it); read by the ops at image `0xA47F..0xA517` _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ | |
| `0x4450 + n*12` | `[Established]` | 12-byte vertex | Vertex register arena (1024 entries): `x/y/z` and projection/flag fields | `# [MEM-SOD-VM]` |
| `0x7C68` | `[Established]` | `u8[]` | Facing flags, one byte per face: `REJ` (`0x9567`), `REJVEC` (`0x94D8`) and `REJ2D` (`0x95C0`) write `0xFF` while the face points at the eye, else 0; `IFVIS` (`0x9BCC`), `BVIS` (`0x9BB3`) and `SORTON` (`0x9183`) read them ([`sod-vm.md`](sod-vm.md) section 8.6) | `# [FMT-SOD-IFVIS]` |
| `0x806C` | `[Established]` for writer and readers (disassembled), `[Hypothesis]` for the run-time effect | `u8` | Shadow-draw mode, set to `0xFF` only by `0x1CE7` around the actor shadow draw: nonzero makes polygon gateways draw in index 0, `GVPOLY`/`GVPOLY16` go flat, and `OP_ANIMATE` take its variable-width skip path ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) | `# [FMT-SOD-ANIMATE]` |
| `0x806E` | `[Established]` | `u8` | Shift of the object's view position from `0x31CF`, stored by `0x9100` (`0x9113`); `OP_TAP` shifts anchors right by `16 - [0x806E]` | _Source: [how OP_TAP places its points](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-how-op_tap-places-its-points)._ |
| `0x806F` | `[Established]` | `u8` | `CH − CL` stored by the object entry `0x9100` (`0x9111..0x9113`), the header's scale shift less the view-position shift: the right shift `OP_VECTORS` applies to each register (`0x9C5A`), the shift of `OP_BZLT`'s threshold (`0x9BEB`), and the shift `0x8070` is derived with | `# [FMT-SOD-ANIMATE]` |
| `0x8070` | `[Bounded Observation]` | `u16` | Projection-scale term consumed by `OP_ANIMATE`; derived from `0x8108` shifted by `0x806F` | `# [FMT-SOD-ANIMATE]` |
| `0x807E` | `[Established]` | `u16` | Line routine `ZLINETO` calls, set by `0x9100` beside `0x8080`: VM `0x3994` (image `0xBBD4`) or `0x3943` (image `0xBB83`, the clipping variant) | _Source: [the ZLINETO draw path read](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ |
| `0x8082` | `[Established]` | `u16` | Special model selector (`0x1AB1` enables TAP screen projection) | |
| `0x8084`, `0x8086`, `0x8088` | `[Established]` | `i16` | The object's origin in view space, shifted (scenery: `0x21B2..0x21BC`); `OP_TAP` subtracts it, so a tapped point is relative to the shape | _Source: [how OP_TAP places its points](../../work/2026-11/254_tap-anchors/journal.md#2026-11-11-how-op_tap-places-its-points)._ |
| `0x808A` | `[Established]` | `i16[9]` | The matrix the display list draws with: `0x80C0 · R` for an actor (`CS:0x1D31`), the matrix at `0x809C` when the object's flag `+0x0F & 1` is set (`CS:0x1D02`), for scenery the view matrix alone, or `0x809C` under the same flag (`CS:0x21C2..0x21CA`). The flag is the shape's `header_flags` bit 0 (`[es:9]`, [`sod-vm.md`](sod-vm.md) section 8.8); `0x809C` is the view matrix built with the yaw zeroed (`CS:0x12C2`) | _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| `0x80C0..0x80CA` | `[Established]` | `i16[9]` | 3×3 view matrix: the scenery draw matrix (`0x808A`) and the matrix `OP_TAP` transforms anchors by | |
| `0x80D2` | `[Established]` | `i16[9]` | Scratch for the rotation `R` from image `0x8725` | _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| `0x8108` | `[Established]` | `u16` | Lens mantissa, a copy of `DS:0x229C` (image `0x122E`); Q15 factor on the view matrix's two screen rows (image `0x12E3`), also read by the sun-disc drawer and `OP_ANIMATE` ([`lod.md`](lod.md) section 2.2) | `# [FMT-SOD-ANIMATE]` |
| `0x810A` | `[Established]` | `u16` | `0x229C² × 2 >> 16` (image `0x1238`); `OP_REJVEC` scales its depth term by it (`0x953F`), undoing the lens zoom ([`sod-vm.md`](sod-vm.md) section 8.6) | |
| `0x810C` | `[Established]` | `u16` | Lens shift count, a copy of `DS:0x229E` (image `0x123D`); arithmetic right shift on the view matrix's depth row (image `0x12F8`). Zoom is `0x8108 / 0x8000 × 2^0x810C`, about `lens / 8192` | |
| `0x811E` | `[Established]` | `u16` | The film clock `[0x4888 + 0x0E]` shifted left 12 (image `0x1DCA`): the bank word `OP_ANIMATE` selector `0x10` reads, one sweep every 16 ticks | `# [FMT-SOD-ANIMATE]` |
| `0x8120` | `[Established]` | `u16` | Var 10's change since the previous frame, saturated at 255, shifted left 8 (image `0x1DBD`): bank operand `0x12` ([`angle-bank.md`](angle-bank.md)) | |
| `0x8122` | `[Established]` | `u16` | The previous frame's var 10, low byte shifted left 8 (image `0x1DC6`): bank operand `0x14`, the stock propellers' `ROTZ` angle ([`angle-bank.md`](angle-bank.md)) | |
| `0x8124` | `[Established]` | `u16` | The drawn slot's animate word, its record's `+0x16` (image `0x1D66`): the bank word `OP_ANIMATE` selector `0x16` and `ROT*` operand `0x16` read | `# [FMT-SOD-ANIMATE]` |
| `0x8126`, `0x8128` | `[Established]` | `i16` | Var 12 and its negation (image `0x1D9F`, `0x1DA5`): bank operands `0x18` and `0x1A` ([`angle-bank.md`](angle-bank.md)) | |

Code anchors (segment-relative; `CS = 0x0F17` in the captured session):

| Code offset | Purpose | Anchor |
|---|---|---|
| `0x1316 + opcode` | Opcode dispatch table, 9-byte pitch | `# [MEM-SOD-VM]` |
| `0x150E` | `[Established]` `OP_ANIMATE` dispatch entry; jumps to `CS:0x3AAC` | `# [FMT-SOD-ANIMATE]` |
| `0x3AAC` | `[Established]` `OP_ANIMATE` handler: frame `(count × [work:0x810E + selector]) >> 16` of its id table, drawn through `0:0x8073` | `# [FMT-SOD-ANIMATE]` |
| `0x3E58` | `OP_TAP` (`0x022E`) handler | `# [MEM-SOD-VM]` |
| `0x3F36` | `OP_HUGETAP` (`0x0237`) entry: `int3` (unimplemented) | `# [MEM-SOD-VM]` |
| `0x3F37` | `OP_TAP` anchor transform (image `0xAE67`): `0x80C0 · anchor + 0x41D4`, cached at record `+0x06..+0x10` | `# [MEM-SOD-VM]` |
| `0x492D` | Per-frame anchor cache invalidation (`DS=0x1DF8`, 231 records) | `# [MEM-SOD-ANCHOR-TABLE]` |

### 3.1 Anchor Table Cache (`# [MEM-SOD-ANCHOR-TABLE]`)

The anchor table is the `0x0000` header and `0x0004 + n*0x1C` records in the work-segment table above, invalidated per frame by `CS:0x492D` over 231 records; `OP_TAP` copies records from it into the vertex register arena. The fields are not restated here: see that table and the cache walk-through in [`sod-vm.md`](sod-vm.md).

See [`research/playone-exe/sod-vm.md`](sod-vm.md) for `OP_TAP` and [`research/playone-exe/sod-animate.md`](sod-animate.md) for `OP_ANIMATE` disassembly and operand evidence.

### # [MEM-FLM-VARS]

### # [MEM-PALETTE]

`DS`-relative data and code in the segment that runs at `CS = 0x0824` (load-image segment `0x0000`). Evidence: [`research/playone-exe/palette-fade.md`](palette-fade.md). Patch #3 offsets: [§ 1.1](#11-patch-3-build).

| Offset | Evidentiary Tier | Purpose |
|---|---|---|
| `DS:0x474A + 0x7E + 2n` | `[Established]` | Live film variable `n` (`u16[16]`), interpolated per frame between `+0xBE + 2n` and `+0xDE + 2n` |
| `DS:0x474A + 0x98` | `[Established]` | Var 13, palette night term |
| `DS:0x474A + 0x9A`, `+ 0x9C` | `[Established]` | Var 14 (palette brightness) and var 15 (palette saturation); 32768 = full |
| `DS:0x09DE` | `[Established]` | Six `(day, night)` sky colour pairs, 6-bit DAC units; blended by the night term into `DS:0x09EA` (zenith, horizon) |
| `DS:0x09F0`, `DS:0x09F6` | `[Established]` | Day and night colours of palette entries 213–214 |
| `DS:0x2240` | `[Established]` | 17-entry graphics driver vector table, copied from `DS:0x10A4` (`set_palette` at `+0x12`, palette-resource load at `+0x1E`) |
| `DS:0x2468` | `[Established]` | Base palette, 6-bit DAC units |
| `DS:0x2768` | `[Established]` | Working palette sent to the DAC (256 x 3 bytes) |
| `DS:0x227A` | `[Supported Inference]` | Screen-faded flag; suppresses DAC writes while set |
| `DS:0x227B..0x227D` | `[Established]` | Cached brightness/saturation/sky inputs of the palette build |
| `CS:0x0FD2` | `[Established]` | Palette build from vars 13–15 (entries 0–239) |
| `CS:0x136F` | `[Established]` | Per-frame film-variable interpolation |
| `CS:0x3D54` | `[Established]` | `var_set` handler |
| `CS:0x7B70` | `[Established]` | VGA DAC upload (`0x3C8`/`0x3C9`), two retrace-gated halves |
| `DS:0x4888` | `[Supported Inference]` | Snapshot of the `0x474A` film state taken at `CS:0x39B0` and read by the frame routine `CS:0x0EE9`; `+0x7E` (`DS:0x4906`) holds the 16 variable copies, `+0x1A` (`DS:0x48A2`) a copy of `0x474A + 0x1A`, the current `view_obj` (written by the `0x90..0x97` handler at `CS:0x3D7F`) |
| `DS:0x4778 -> DS:0x48B6` | `[Supported Inference]` | Per-slot record pointers of the live and snapshot structs; `CS:0x39B0` copies 12 words per slot |
| `CS:0x3E6C` | `[Established]` | Per-frame slot interpolation between the start `[di + 0x32]` and end `[di + 0x34]` records by `DS:0x22E0`, gated by the record's flag byte `+1`: position `+0x04..+0x0F` (`0x08`), angles `+0x10..+0x14` (`0x10`), and the animate word `+0x16` (`0x20`) taken unsigned, never wrapping (`0x3EF8`) ([`sod-animate.md`](sod-animate.md) § 2) |
| `CS:0x3CF2` | `[Established]` | `create` handler (opcodes `0x00..0x3F`): stores the `type_flags` byte verbatim at slot `+1` (`0x3CFD`), then `0x3DDA` reads the shape, position and angles the flags call for _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ |
| `CS:0x1463`, `CS:0x240A` | `[Established]` | Per-frame slot update and its ground and collision probe: for each slot with `SIF_MOVES`, a shape, and `SIF_DRAW` or byte `+0` bit 3, `0x240A` walks the scenery tree through `DS:0x584`, storing the containing ground leaf's plane at slot `+0x1E` (`0x2631`, `0x26BE`) and a code-8 collision box's top at `+0x20/+0x22` (`0x2A5B`) ([`sod-vm.md` § 9.1](sod-vm.md#91-the-actor-shadow-draw)) _Source: [the #478 static read](../../work/2026-11/478_shadow-plane/journal.md#2026-11-14-the-shadow-plane-writer-the-view-slot-and-the-0x806c-readers-read-statically)._ |
| `CS:0x4C41` | `[Established]` | Resource cache lookup of the id in `AX`; returns its segment in `ES`, carry set when absent. A newly loaded chunk sits at segment offset 2 (`0x4CD3`, `0x4CE0`) |
| `CS:0x8073` | `[Established]` | `OP_ANIMATE` draw entry: looks the id up, centres a `DX`-pixel square on `CX`, `BX` and calls the blitter through `DS:0x2260` |
| `CS:0x7DE6` | `[Established]` | Scaled transparent blit: stretches the image at `es:8` (width `es:2`, height `es:4`) to the square, clips to `DS:0x2294..0x229A` and stores every non-zero byte ([`sod-animate.md`](sod-animate.md) § 3) |
| `CS:0x0EE9` | `[Supported Inference]` | Per-frame film render step (entered from `CS:0x4A35` with `BX = 0x4888`): sun vector, view matrix, one scene draw, credits string. `CS:0x0EE6` is the same step with `BX = 0x474A`; no static caller found |
| `CS:0x196C` | `[Established]` | World light from var 13: called from `CS:0x0F50` with `AX = [0x4888 + 0x98]` (var 13), `angle = var 13 - 0x4000`, stored at `DS:0x49EC..0x49F0` and negated at `[DS:0x542]:0x8078..0x807C`; `CS:0x908E` projects it through the camera matrix at `0x80C0`. Values observed live: [`terrain-shade.md`](terrain-shade.md) section 4.2 |
| `CS:0x21F9`, `CS:0x234B`, `CS:0x1D8D` | `[Bounded Observation]` | The three calls of the per-object light setup `0824:0EC0` (image `0x9100`): the first two pass `DS:0x49EC..0x49F0` unchanged, the third (after `CS:0x1CFB`) `R · L` doubled, with `R` the object's rotation from `0824:04E5` ([`terrain-shade.md`](terrain-shade.md) section 4.2) |
| `CS:0x23BF` | `[Established]` | Scenery-walker handler of node type 14 (ground leaf; dispatch `jmp [bx+0x554]`, type 12 at `CS:0x2360`): back-face test against the eye `DS:0x2A6A..0x2A72`, then `lcall 0824:3CE3` at `CS:0x23F6` with `ES = SS` on the leaf's polygon (colour word, count, anchor offsets `0x1C * n`). The tree is image paragraph `0x2286` (image `0x22860`, `SS = 0x2AAA` under DOSBox-X); its 146 leaves are `MAP.BIN`'s polygons and colours ([`world-scene.md`](world-scene.md) section 2) |
| image `0xBBD4`, `0x7FD2`, `0x7511` | `[Established]` | `ZLINETO`'s draw: the line routine clips both registers' screen points to `work:0x41C0..0x41C6`, the gateway `0:7FD2` loads the colour (`work:0x41EA`, or 0 in a shadow draw) and calls driver slot `DGROUP:[0x2244]`, `0x7511`, a one-pixel Bresenham line with both ends ([`sod-vm.md`](sod-vm.md) section 8.10) _Source: [the ZLINETO draw path read](../../work/2026-11/415_screen-space-lines/journal.md#2026-11-11-the-zlineto-draw-path-read-statically)._ |
| image `0x7571` | `[Established]` | Flat polygon filler (driver slot `DGROUP:[0x2246]`): fills from the top row to the bottom row and each span from its left end to its right end, both ends included, counting rows down in `DGROUP:0x10C6` and clipping spans to `[0x2294]`, `[0x2296]` ([`sod-vm.md`](sod-vm.md) section 8.11) _Source: [what thins the INTRO conifer field](../../work/2026-11/426_intro-conifers/journal.md#2026-11-12-what-thins-the-intro-conifer-field)._ |
| `CS:0xBF23` | `[Established]` | Ground-leaf polygon (VM `0x3CE3`, far): transforms stale anchors through VM `0x2C27`, copies them to `work:0x4450`, then draws flat at the stored colour through the raw gateway `lcall 0:8069` (`CX` = colour; driver `DGROUP:[0x2246]`). `0:8010` and `0:8040` are the gateways that read `CX = work:0x41E8` ([`world-scene.md`](world-scene.md) sections 2, 3) |
| `CS:0x11FC` | `[Established]` | View setup indexed by `AX = view_obj` (`[0x4888 + 0x1A]`, loaded at `CS:0x4A32`): film variable `view_obj` (`[BX + SI + 0x7E]`) times `DS:0x22B6` (set by `CS:0x11F8`, `0x7FFF` at `CS:0x4A29`), normalised into the mantissa `DS:0x229C`, the shift count `DS:0x229E` and `DS:0x22A4`; `[BX + SI + 0x2E]` is the camera's object pointer ([`lod.md`](lod.md) section 2.1) |
| `CS:0x12DC` | `[Established]` | Lens zoom of the view matrix: rows 0-1 (screen X, Y) times `0x229C / 0x8000`, row 2 (depth) `sar` by `0x229E`, so focal length scales by about `lens / 8192` ([`lod.md`](lod.md) section 2.2) |
| image `0x8725` (`0824:04E5`) | `[Established]` | Rotation-matrix builder: `BX`, `BP`, `SI` = angle words roll, pitch, yaw (actor slot `+0x10/+0x12/+0x14`, loaded at `CS:0x1D14`); writes `Ry(-yaw) · Rx(pitch) · Rz(roll)` as nine Q15 words, row by row, at `work:DI` ([`coordinates-and-units.md` § 3.4](../formats/concepts/coordinates-and-units.md#34-rotation-conventions--unit-quaternions-seam-2)) _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| image `0x884A` (`0824:060A`) | `[Established]` | 3×3 Q15 product `work:DI = work:SI · work:BX` (rows of `SI` times columns of `BX`) _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| image `0x88C1` (`0824:0681`) | `[Established]` | Transposed copy of a 3×3 matrix from `work:SI` to `work:DI` _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| image `0x895D` (`0824:071D`), image `0x88FB` (`0824:06BB`, inferred from the `0x8240` offset the other three share) | `[Established]` | Vector `AX, BX, CX` times the matrix at `work:SI`, one output per row, returned in `DX, BP, DI` _Source: [the 0x04E5 read](../../work/2026-11/274_actor-matrix-axes/journal.md#2026-11-09-the-actor-matrix-builder-0x04e5-read-statically)._ |
| `CS:0x1D96` | `[Established]` | Fills bank words `0x10`..`0x14`, `0x18`, `0x1A` (`0x15D4:0x811E`..`0x8128`) once per frame from the film clock and vars 10 and 12 of `DS:0x4888`; only caller `CS:0x1DD5` (from `CS:0x0F77`), before the object loop; `DS:0x22BC` keeps the previous frame's var 10 ([`angle-bank.md`](angle-bank.md)) |
| `DS:0x2275` | `[Supported Inference]` | Video-mode flag: `0` after `int 10h` mode `0x13` (`CS:0x737B`), `0xFF` on the alternate path (`CS:0x6E1B`); selects `0x824:0x07DC` over `0x824:0x0A05` in the frame routine |
| `CS:0x39D0` | `[Established]` | Copies the 16 live variables from `DS:0x47C8` to `DS:0x4906` (the checkpoint inside `0x39B0`) |
| `CS:0x42F5` | `[Supported Inference]` | Film recorder: compares the 16 live variables with `DS:0x49C6` and emits `var_set` bytes (`0x80 + n`, from `0x90 - CL` with `CL` counting 16 to 1) when they change |
| `0x1DEA:0x05B1` | `[Supported Inference]` | Resident PCM mixer setter: `AX = 1` stores `DX` in `cs:[0x49]`, otherwise `cs:[0xD7]` (var 11); channel blocks are 0x8E bytes apart and no reader of that field was found |
