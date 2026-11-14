---
summary: "`PLAYONE.EXE` runtime capture anchors: the per-frame retrace trap, the 50 Hz tick and film clock, and the unverified camera-rig and actor-table layouts."
---
# Memory Map: Runtime Capture Anchors

Part of the `PLAYONE.EXE` memory map: [`memory-map.md`](memory-map.md) lists its files and states the conventions every table uses (target binary, image base, linear address). Section numbers run across the files.

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
* **Scope**: Runtime `DS` offsets `0x22B8` (global 50 Hz tick), `0x4896` (active film clock, struct base `0x4888` + `0x0E`) and `0x2272` (playback flag); rows in [§ 1](memory-map.md#1-dgroup-memory-reference-table). `0x4758` and the retired `0x0C60` label are not the film clock.
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
