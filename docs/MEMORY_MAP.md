# Runtime Memory Map & Real-Mode Offsets

**This file owns every `DGROUP` / work-segment offset table and every `# [MEM-*]` anchor.** The evidence behind a row (disassembly, live samples, provenance) lives in [`research/playone-exe/`](../research/playone-exe/) and is linked from the row; it is not restated here. Tier names come from the enum owned by [`python/scripts/verify_formats_docs.py`](../python/scripts/verify_formats_docs.py) (`EVIDENTIARY_TIERS`) and defined in [`SPEC.md` § 2.4](SPEC.md#24-evidentiary-tiers--contract-anchor-system).

* **Target Binary**: `PLAYONE.EXE` (Unpacked LZEXE 0.91 image)
* **Image Dump Base**: paragraph `0x0D51` (file offset `0xD910` in the unpacked image). This is the snapshot base used by earlier dumps, **not** the runtime `DS`. In the captured session `CS = 0x0F17` and `DS = 0x1575`; table offsets are `DS`-relative. See [`memory.md` § 1](../research/playone-exe/memory.md#1-segment-architecture--dgroup-map).
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
| `0x22C4` | `[Supported Inference]` | `u16` | Stored PSP segment address | |
| `0x22CE` | `[Supported Inference]` | `u16` | Preserved `SS` register during `INSTALL.EXE` child execution | |
| `0x22D0` | `[Supported Inference]` | `u16` | Preserved `SP` register during `INSTALL.EXE` child execution | |
| `0x4758` | `[Established]` | `u16` | Field `+0x0E` of the sibling `0x474A` struct; reads 0 during playback — **not** the film clock | `# [MEM-FLM-TICK]` |
| `0x4896` | `[Established]` | `u16` | Active film clock in 50 Hz ticks (struct base `0x4888` + `0x0E`); ends at the film's authored total and holds there; offset from `0x22B8` varies, see below | `# [MEM-FLM-TICK]` |

Rows `0x22C4`, `0x22CE` and `0x22D0` were untiered in the former `memory.md` table; `[Supported Inference]` was assigned when the tables were merged, pending a pointer to the disassembly that sets them.

---

## 2. Runtime Dynamic Capture Anchors

### # [MEM-VSYNC-03DA]
* **I/O Port**: `0x03DA` (VGA Input Status Register 1)
* **Routine**: Vertical retrace polling loop (`in al, dx; test al, 08h`).
* **Protocol** (`[Bounded Observation]`, one film, `CTRY.FLM`): a one-time breakpoint `BPIO 03DA` isolates the polling loop address; execution breakpoint `BP <CS:IP>` is set immediately *after* the loop. The harness uses `BP 0D51:0C5E` plus `RUN`, which returns once per rendered frame, so one `MEMDUMPBIN A000:0000` per hit is a whole frame. `VRT` cannot substitute for it (stepping a Mode 13h guest exits the emulator with `0xC0000409`). Run-by-run evidence: [`capture.md`](../research/playone-exe/capture.md) and [`memory.md` § 3.1](../research/playone-exe/memory.md#31-post-retrace-vertical-blank-trap).
* **Evidentiary Tier**: runtime behaviour `[Bounded Observation]`; static identification of the trap address `[Hypothesis]` (conflict below).

> [!WARNING]
> **Unresolved conflict — needs live re-verification.** The address `0C5E` is described three incompatible ways:
> 1. [`startup.md`](../research/playone-exe/startup.md) § 1 gives the unpacked **entry point** as `CS:IP = 0000:0C5E` (executed once, followed by the command-tail parser at `0x0C7C`).
> 2. The capture harness uses `BP 0D51:0C5E` as a **per-frame** loop boundary, and 140 consecutive `CTRY.FLM` frames were captured that way.
> 3. [`memory.md` § 3.1](../research/playone-exe/memory.md#31-post-retrace-vertical-blank-trap) lists a polling loop at `0D51:0C48..0C5E` ending in `call render_frame_flush`, which cannot also be the entry point.
>
> The segment is also suspect: `0x0D51` is the image-dump base, while the captured session ran at `CS = 0x0F17`, so `0D51:0C5E` (linear `0xE16E`) is not `CS:0C5E` (linear `0xFDCE`). The breakpoint demonstrably stops once per frame, but the static meaning of that address is unproven. To resolve: with the guest running film playback, run `BPIO 03DA`, record the `CS:IP` it reports, disassemble around it, and compare its linear address to `0D51:0C5E`. Until then, cite the harness behaviour, not the address's meaning.

### # [MEM-FLM-TICK]
* **Scope**: Runtime `DS` offsets `0x22B8` (global 50 Hz tick), `0x4896` (active film clock, struct base `0x4888` + `0x0E`) and `0x2272` (playback flag); rows in § 1. `0x4758` and the retired `0x0C60` label are not the film clock.
* **Data Type**: 16-bit unsigned integer (`u16`).
* **Contract**: the INT 8 path increments `0x22B8` once per 20 ms tick while `0x2272` is set; the film clock `0x4896` advances with it during the film, stops at the authored total (`1342` for `CTRY.FLM`) and holds, while `0x22B8` keeps counting. The film clock's offset from `0x22B8` is `[Bounded Observation]` and its sign differs between two samples (2–3 behind, or 5 ahead), so it is not a constant. A rendered frame may advance several ticks (Mode 13h refreshes at 70 Hz and rendering can drop frames), so the streamer gates snapshot capture on:
  $$\text{current\_tick} > \text{last\_captured\_tick}$$
  preventing duplicate frame capture.
* **Evidence**: the only copy of the static-handler and live-sampling evidence is [`memory.md` § 3.2](../research/playone-exe/memory.md#32-tick-counter-evidence). Other documents link there instead of restating it.
* **Evidentiary Tier**: `[Established]` (static disassembly plus live DOSBox-X sampling).

### # [MEM-CAMERA-RIG]
* **Segment / Scope**: Runtime `DS` offset `0x0C10` (the concrete `DS` value depends on the load base; in the captured session `DS = 0x1575`).
* **Evidentiary Tier**: `[Hypothesis]`. The layout below is what `MockTransport._write_tick_state` writes and `TrajectoryStreamer.decode_camera_from_memory` reads ([`transport.py`](../python/stunt_reel/tac/transport.py), [`streamer.py`](../python/stunt_reel/tac/streamer.py)); it has been decoded only against that offline mock. The capture loop never reads the camera rig from a live `PLAYONE.EXE` ([`capture.md` § 3](../research/playone-exe/capture.md#3-working-protocol)), and no disassembly of a consumer exists. The harness also addresses it as `0D51:0C10` although `0x0D51` is not the runtime `DS`. Treat offsets, field types (`f32` vs `16.16 i32`) and the `+0x1C` cut rule as unverified.
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
* **Byte Layout Specification, Layout A (64 bytes per actor entry)**:
  * `+0x00` (`u32` LE, 4B): Actor Channel ID (unique index within `.FLM` choreography).
  * `+0x04` (`char[8]`, 8B): Bound `.SOD` asset name (null-terminated ASCII, e.g. `"FOKKER\0"`).
  * `+0x0C` (`f32` / `16.16 i32` LE, 4B): World Position X in meters `[I1]`.
  * `+0x10` (`f32` / `16.16 i32` LE, 4B): World Position Y in meters.
  * `+0x14` (`f32` / `16.16 i32` LE, 4B): World Position Z in meters.
  * `+0x18` (`4 x f32` LE, 16B): Normalized rotation quaternion $[q_x, q_y, q_z, q_w]$ ($|\|\mathbf{q}\| - 1.0| < 10^{-4}$).
  * `+0x28` (`u16` LE, 2B): Dynamic state bitmask (visibility, damage, gear state, smoke).
  * `+0x2A` (`u16` LE, 2B): Articulated joint count $N$.
  * `+0x2C` (`N x (u16, u16)`, up to 16B): Articulated subobject BAM rotation angle pairs `(subobject_id, raw_bam_u16)`.
  * `+0x3C` (`u32` LE, 4B): Next actor chain link pointer (or null `0x00000000`).
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
| `0x41C8`, `0x41CA` | `[Established]` | `u16` | Screen-projection center offsets | |
| `0x41D4..0x41DA` | `[Established]` | `i32[3]` | Model→view translation | |
| `0x4450 + n*12` | `[Established]` | 12-byte vertex | Vertex register arena (1024 entries): `x/y/z` and projection/flag fields | `# [MEM-SOD-VM]` |
| `0x806C` | `[Bounded Observation]` | `u8` | `OP_ANIMATE` mode gate; nonzero takes the variable-width skip path | `# [FMT-SOD-ANIMATE]` |
| `0x806E` | `[Established]` | `u8` | Fixed-point arithmetic shift applied by `OP_TAP` | |
| `0x806F` | `[Bounded Observation]` | `u8` | High-byte shift count used to derive the `OP_ANIMATE` projection-scale term | `# [FMT-SOD-ANIMATE]` |
| `0x8070` | `[Bounded Observation]` | `u16` | Projection-scale term consumed by `OP_ANIMATE`; derived from `0x8108` shifted by `0x806F` | `# [FMT-SOD-ANIMATE]` |
| `0x8082` | `[Established]` | `u16` | Special model selector (`0x1AB1` enables TAP screen projection) | |
| `0x8084`, `0x8086`, `0x8088` | `[Established]` | `i16` | View-origin subtraction terms applied by `OP_TAP` | |
| `0x80C0..0x80CA` | `[Established]` | `i16[9]` | 3×3 model→view rotation matrix | |
| `0x8108` | `[Bounded Observation]` | `u16` | Base scale input read by the observed projection setup; its wider role is unknown | `# [FMT-SOD-ANIMATE]` |

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

The anchor table is the `0x0000` header and `0x0004 + n*0x1C` records in the work-segment table above, invalidated per frame by `CS:0x492D` over 231 records; `OP_TAP` copies records from it into the vertex register arena. The fields are not restated here: see that table and the cache walk-through in [`sod-vm.md`](../research/playone-exe/sod-vm.md).

See [`research/playone-exe/sod-vm.md`](../research/playone-exe/sod-vm.md) for `OP_TAP` and [`research/playone-exe/sod-animate.md`](../research/playone-exe/sod-animate.md) for `OP_ANIMATE` disassembly and operand evidence.

### # [MEM-FLM-VARS]

### # [MEM-PALETTE]

`DS`-relative data and code in the segment that runs at `CS = 0x0824` (load-image segment `0x0000`). Evidence: [`research/playone-exe/palette-fade.md`](../research/playone-exe/palette-fade.md).

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
