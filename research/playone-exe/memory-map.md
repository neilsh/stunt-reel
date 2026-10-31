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
| `0x05AC` | `[Established]` | String (null-term) | `"game.cfg"` — Hardware configuration file | |
| `0x05B5` | `[Established]` | String (null-term) | `"game.var"` — Game variables definition | |
| `0x05BE` | `[Established]` | String (null-term) | `"install.exe"` — Setup utility executable | |
| `0x05CA` | `[Established]` | String (null-term) | `"pfont.bin"` — UI font bitmap and metrics | |
| `0x05D4` | `[Established]` | String (null-term) | `"pilots"` — Pilot profiles directory | |
| `0x05DB` | `[Established]` | String (null-term) | `"res\*.res"` — Core resource archive wildcard | |
| `0x065D` | `[Established]` | String (`$`-term) | `"Not enough memory.  Stunt Island requires 570,000 bytes free."` | |
| `0x069B` | `[Established]` | String (`$`-term) | `"Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."` | |
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
| `0x22B8` | `[Established]` | `u16` | Global 50 Hz timer tick (incremented by the INT 8 path while `0x2272` is set) | `# [MEM-FLM-TICK]` |
| `0x22C4` | `[Established]` | `u16` | Stored PSP segment address: written at image `0x0C78` (`mov [0x22C4], es`, right after `DS` is set to `0x0D51`); read at `0x0CF2`/`0x0CFA` for the free-memory check against `PSP:[2]` | |
| `0x22CA`, `0x22CC` | `[Supported Inference]` | `u16` x 2 | Segments of the two composed pages, swapped every render; after a finished copy, rows 0–191 of `A000` equal one of them (rows 192–199, the button bar, are drawn on `A000` directly). A page with bands from each is torn ([`capture-dosbox-automation.md` § 4.5](capture-dosbox-automation.md#45-torn-pages-and-the-dac-lag)) | |
| `0x22CE` | `[Established]` | `u16` | Preserved `SS` register during `INSTALL.EXE` child execution: written at image `0x0C94`, restored at `0x0CC4` around the `int 21h AX=4B00h` EXEC of `DS:0x05BE` (`install.exe`) at `0x0CBD` | |
| `0x22D0` | `[Established]` | `u16` | Preserved `SP` register during `INSTALL.EXE` child execution: written at image `0x0C98`, restored at `0x0CC8` around the same EXEC | |
| `0x4758` | `[Established]` | `u16` | Field `+0x0E` of the sibling `0x474A` struct; reads 0 during playback — **not** the film clock | `# [MEM-FLM-TICK]` |
| `0x4896` | `[Established]` | `u16` | Active film clock in 50 Hz ticks (struct base `0x4888` + `0x0E`); ends at the film's authored total and holds there; equals `0x22B8` on every frame-locked read until it holds, see below | `# [MEM-FLM-TICK]` |
| image offset + `0x8240` | `[Bounded Observation]` | Rule | Relocation: `runtime_linear = image_offset + 0x8240` (`DGROUP` image `0xD510` -> segment `0x1575`); VM `CS:IP` = image - `0x8240`; see [`memory.md` § 4](memory.md#4-image-to-memory-relocation-and-a-candidate-embedded-data-region) | |

Rows `0x22C4`, `0x22CE` and `0x22D0` were promoted from `[Supported Inference]` to `[Established]` on 2026-10-23. A Capstone 16-bit decode of the whole unpacked image found exactly those instructions referencing them, all inside the entry routine `0x0C5E`, and raw word matches elsewhere are not instruction operands. Offsets are load-image offsets (see [`startup.md` § 5](startup.md#5-reproducing-the-static-analysis)). The EXEC runs when the command line starts with `?` (`0x0C90`) or when opening `game.cfg` (`DS:0x05AC`, call at `0x0CD2`) fails. The `entry` listing in rea/Ghidra matches the same instructions at analysis address `0x10000 +` image offset.

### 1.1 Patch #3 build

Every row above is for the unpatched 1992 `PLAYONE.EXE` (102,703 bytes, sha256 `3c93493c…`). Patch #3's `PLAYONE.EXE` (97,790 bytes, `fc532c94…`) is relinked: `DGROUP` is paragraph `0x0C71`, so `DS = 0x0E66` under dosbox-automation. Data from `0x2200` up sits `0x67A` lower, including every row the capture harness reads; the strings near `0x0600` sit `0x7C` higher. Evidence: [`patch3.md` § 2](patch3.md#2-patched-playoneexe-offsets). Other rows are not mapped for the patched build.

| Unpatched `DS` offset | Patched `DS` offset | Evidentiary Tier | Row | Anchor |
|---|---|---|---|---|
| `0x05AC` | `0x0628` | `[Supported Inference]` | `"game.cfg"` (operand of the paired entry-routine instruction) | |
| `0x05BE` | `0x063A` | `[Supported Inference]` | `"install.exe"` (same) | |
| `0x2263`, `0x2264`, `0x2265` | `0x1BE9`, `0x1BEA`, `0x1BEB` | `[Supported Inference]` | Display mode, sound driver mode, audio channel flags (same) | |
| `0x22B8` | `0x1C3E` | `[Supported Inference]` | Global 50 Hz timer tick | `# [MEM-FLM-TICK]` |
| `0x22C4` | `0x1C4A` | `[Established]` | Stored PSP segment (`mov [0x1C4A], es` in the patched entry routine) | |
| `0x22CA`, `0x22CC` | `0x1C50`, `0x1C52` | `[Bounded Observation]` | Composed-page segments, inferred from the uniform shift; a live `CTRY.FLM` capture on the patched build flagged 72 of 1,906 frames torn (3.8%, against 66 of 1,908 unpatched), which wrong words could not produce ([`patch3.md`](patch3.md)) | |
| `0x22CE`, `0x22D0` | `0x1C54`, `0x1C56` | `[Supported Inference]` | Saved `SS`, `SP` around the `INSTALL.EXE` EXEC (same) | |
| `0x2768` | `0x20EE` | `[Supported Inference]` | Working palette, 768 bytes of 6-bit DAC values | |
| `0x4896` | `0x421C` | `[Supported Inference]` | Active film clock | `# [MEM-FLM-TICK]` |

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
* **Evidentiary Tier**: `[Hypothesis]`. The layout below is what `MockTransport._write_tick_state` writes and `TrajectoryStreamer.decode_camera_from_memory` reads ([`transport.py`](../../python/stunt_reel/tac/transport.py), [`streamer.py`](../../python/stunt_reel/tac/streamer.py)); it has been decoded only against that offline mock. The capture loop never reads the camera rig from a live `PLAYONE.EXE` ([`capture.md` § 3](capture.md#3-working-protocol)), and no disassembly of a consumer exists. The harness also addresses it as `0D51:0C10` although `0x0D51` is not the runtime `DS`. Treat offsets, field types (`f32` vs `16.16 i32`) and the `+0x1C` cut rule as unverified.
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
  * Layout A is retained below because it is the one executable code and tests assume, but its only source is the offline mock (`tests/test_harness.py`, `tests/test_tac_adversarial.py` build their fixtures from the same layout). Nothing in `research/playone-exe/` records a read of the real table (`capture.md` § 3 states the capture loop deliberately never reads it), and the stored film rotation is BAM-valued (`SPEC.md` § 3.7), so a quaternion field is itself doubtful. Promote only after a live `MEMDUMPBIN` of a populated entry.
* **Byte layout, Layout A (64 bytes per actor entry)**: defined only by [`actor_record.ksy`](../formats/memory/actor_record.ksy) (spike; see [`kaitai-memory-spike.md`](../formats/memory/kaitai-memory-spike.md)). Meaning of the fields: `+0x00` channel id; `+0x04` bound `.SOD` name (NUL-padded); position in signed 16.16 metres `[I1]`; rotation quaternion (normalised, `|‖q‖ - 1| < 1e-4`); state bitmask (visibility, damage, gear, smoke); joint count `N` and `(subobject_id, raw_bam_u16)` pairs; next-actor far pointer as `off:u16, seg:u16`, both zero ends the chain.
* **Traversal guard**: the streamer enforces a bounded node count and cycle detection when following `+0x3C`.

---

## 3. SOD Display-List VM Work Segment (`# [MEM-SOD-VM]`)

The display-list VM runs against a dedicated 64 KB work segment (`0x1DF8` in the captured `CTRY.FLM` session). Offsets are stable; the segment base is runtime-selected. `ES:SI` addresses the bytecode, `DS` the work segment.

| Offset in work segment | Evidentiary Tier | Data Type | Purpose / Value | Anchor |
|---|---|---|---|---|
| `0x0000` | `[Established]` | 4-byte header | Anchor-table header (record 0 starts at `+0x04`) | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x0004 + n*0x1C` | `[Established]` | 28-byte record | Anchor point `n`: `x/y/z` at `+0x00/+0x02/+0x04`; cache at `+0x06..+0x10`; fields `+0x12/+0x16/+0x1A`; frame stamp `+0x1B` | `# [MEM-SOD-ANCHOR-TABLE]` |
| `0x19A8` | `[Established]` | `u8` | Per-frame transform cache counter; incremented by `CS:0x492D` | |
| `0x41B8` | `[Established]` | `u16` | `OP_TAP` remaining-count scratch | |
| `0x41C8`, `0x41CA` | `[Established]` | `u16` | Screen-projection center offsets; live `CTRY` session reads 160 and 92 (3D viewport is 185 rows; see `capture.md` § 4) | |
| `0x41D4..0x41DA` | `[Established]` | `i32[3]` | Model→view translation | |
| `0x4450 + n*12` | `[Established]` | 12-byte vertex | Vertex register arena (1024 entries): `x/y/z` and projection/flag fields | `# [MEM-SOD-VM]` |
| `0x806C` | `[Bounded Observation]` | `u8` | `OP_ANIMATE` mode gate; nonzero takes the variable-width skip path | `# [FMT-SOD-ANIMATE]` |
| `0x806E` | `[Established]` | `u8` | Fixed-point arithmetic shift applied by `OP_TAP` | |
| `0x806F` | `[Bounded Observation]` | `u8` | High-byte shift count used to derive the `OP_ANIMATE` projection-scale term | `# [FMT-SOD-ANIMATE]` |
| `0x8070` | `[Bounded Observation]` | `u16` | Projection-scale term consumed by `OP_ANIMATE`; derived from `0x8108` shifted by `0x806F` | `# [FMT-SOD-ANIMATE]` |
| `0x8082` | `[Established]` | `u16` | Special model selector (`0x1AB1` enables TAP screen projection) | |
| `0x8084`, `0x8086`, `0x8088` | `[Established]` | `i16` | View-origin subtraction terms applied by `OP_TAP` | |
| `0x80C0..0x80CA` | `[Established]` | `i16[9]` | 3×3 model→view rotation matrix | |
| `0x8108` | `[Established]` | `u16` | Lens mantissa, a copy of `DS:0x229C` (image `0x122E`); Q15 factor on the view matrix's two screen rows (image `0x12E3`), also read by the sun-disc drawer and `OP_ANIMATE` ([`lod.md`](lod.md) section 2.2) | `# [FMT-SOD-ANIMATE]` |
| `0x810A` | `[Established]` | `u16` | `0x229C² × 2 >> 16` (image `0x1238`); reader not traced | |
| `0x810C` | `[Established]` | `u16` | Lens shift count, a copy of `DS:0x229E` (image `0x123D`); arithmetic right shift on the view matrix's depth row (image `0x12F8`). Zoom is `0x8108 / 0x8000 × 2^0x810C`, about `lens / 8192` | |

Code anchors (segment-relative; `CS = 0x0F17` in the captured session):

| Code offset | Purpose | Anchor |
|---|---|---|
| `0x1316 + opcode` | Opcode dispatch table, 9-byte pitch | `# [MEM-SOD-VM]` |
| `0x150E` | `[Established]` `OP_ANIMATE` dispatch entry; jumps to `CS:0x3AAC` | `# [FMT-SOD-ANIMATE]` |
| `0x3AAC` | `[Established]` `OP_ANIMATE` handler for variable-width resource selection and raster draw | `# [FMT-SOD-ANIMATE]` |
| `0x3E58` | `OP_TAP` (`0x022E`) handler | `# [MEM-SOD-VM]` |
| `0x3F36` | `OP_HUGETAP` (`0x0237`) entry: `int3` (unimplemented) | `# [MEM-SOD-VM]` |
| `0x492D` | Per-frame anchor cache invalidation (`DS=0x1DF8`, 231 records) | `# [MEM-SOD-ANCHOR-TABLE]` |

### 3.1 Anchor Table Cache (`# [MEM-SOD-ANCHOR-TABLE]`)

The anchor table is the `0x0000` header and `0x0004 + n*0x1C` records in the work-segment table above, invalidated per frame by `CS:0x492D` over 231 records; `OP_TAP` copies records from it into the vertex register arena. The fields are not restated here: see that table and the cache walk-through in [`sod-vm.md`](sod-vm.md).

See [`research/playone-exe/sod-vm.md`](sod-vm.md) for `OP_TAP` and [`research/playone-exe/sod-animate.md`](sod-animate.md) for `OP_ANIMATE` disassembly and operand evidence.

### # [MEM-FLM-VARS]

### # [MEM-PALETTE]

`DS`-relative data and code in the segment that runs at `CS = 0x0824` (load-image segment `0x0000`). Evidence: [`research/playone-exe/palette-fade.md`](palette-fade.md).

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
| `CS:0x0EE9` | `[Supported Inference]` | Per-frame film render step (entered from `CS:0x4A35` with `BX = 0x4888`): sun vector, view matrix, one scene draw, credits string. `CS:0x0EE6` is the same step with `BX = 0x474A`; no static caller found |
| `CS:0x196C` | `[Supported Inference]` | Sun or moon direction from var 13: `angle = var 13 - 0x4000`, stored at `DS:0x49EC..0x49F0` and negated at `[DS:0x542]:0x8078..0x807C`; `CS:0x908E` projects it through the camera matrix at `0x80C0` |
| `CS:0x11FC` | `[Established]` | View setup indexed by `AX = view_obj` (`[0x4888 + 0x1A]`, loaded at `CS:0x4A32`): film variable `view_obj` (`[BX + SI + 0x7E]`) times `DS:0x22B6` (set by `CS:0x11F8`, `0x7FFF` at `CS:0x4A29`), normalised into the mantissa `DS:0x229C`, the shift count `DS:0x229E` and `DS:0x22A4`; `[BX + SI + 0x2E]` is the camera's object pointer ([`lod.md`](lod.md) section 2.1) |
| `CS:0x12DC` | `[Established]` | Lens zoom of the view matrix: rows 0-1 (screen X, Y) times `0x229C / 0x8000`, row 2 (depth) `sar` by `0x229E`, so focal length scales by about `lens / 8192` ([`lod.md`](lod.md) section 2.2) |
| `CS:0x1D96` | `[Bounded Observation]` | Stores var 12 and its negation at `0x15D4:0x8126`/`0x8128`, var 10 (with change sign and low byte) at `0x15D4:0x8120`/`0x8122`; `DS:0x22BC` keeps the previous var 10 |
| `DS:0x2275` | `[Supported Inference]` | Video-mode flag: `0` after `int 10h` mode `0x13` (`CS:0x737B`), `0xFF` on the alternate path (`CS:0x6E1B`); selects `0x824:0x07DC` over `0x824:0x0A05` in the frame routine |
| `CS:0x39D0` | `[Established]` | Copies the 16 live variables from `DS:0x47C8` to `DS:0x4906` (the checkpoint inside `0x39B0`) |
| `CS:0x42F5` | `[Supported Inference]` | Film recorder: compares the 16 live variables with `DS:0x49C6` and emits `var_set` bytes (`0x80 + n`, from `0x90 - CL` with `CL` counting 16 to 1) when they change |
| `0x1DEA:0x05B1` | `[Supported Inference]` | Resident PCM mixer setter: `AX = 1` stores `DX` in `cs:[0x49]`, otherwise `cs:[0xD7]` (var 11); channel blocks are 0x8E bytes apart and no reader of that field was found |
