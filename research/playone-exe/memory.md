# `PLAYONE.EXE`: Memory Architecture & Data Segment Layout

This document is the **evidence narrative** for `PLAYONE.EXE`'s real-mode memory: how offsets were found, what was observed live, and what is still unverified. It holds no offset tables. Every `DGROUP` offset, struct layout and `# [MEM-*]` anchor lives in [`docs/MEMORY_MAP.md`](../../docs/MEMORY_MAP.md); this file links to the rows it supports.

---

## 1. Segment Architecture & DGROUP Map

`PLAYONE.EXE` executes as a 16-bit MS-DOS real-mode application. Static variables, string literals, and system buffers reside within the primary data segment `DGROUP`.

* **Image Dump Base**: paragraph `0x0D51` (unpacked file offset `0xD910`). This is the snapshot base used by earlier dumps, not the runtime segment.
* **Runtime Register Context**: in the captured session `CS = 0x0F17` and `DS = 0x1575`; `MEMORY_MAP` offsets are `DS`-relative.
* **Offset table**: [`MEMORY_MAP.md` § 1](../../docs/MEMORY_MAP.md#1-dgroup-memory-reference-table).

---

## 2. Conventional Memory Organization & MCB Layout

Under MS-DOS, conventional memory (0 to 640 KB) is managed as a linked list of Memory Control Blocks (MCBs). Each block begins on a 16-byte paragraph boundary with a 16-byte header:

```
+-----------------------------------------------------------------------+
| Byte 0: Block Type ('M' = Member block, 'Z' = End of chain)           |
| Bytes 1-2: Owner PSP Segment address                                  |
| Bytes 3-4: Size of allocated memory block in paragraphs (1 para = 16B)|
| Bytes 5-7: Reserved                                                   |
| Bytes 8-15: Program or Block Name (DOS 4.0+)                          |
+-----------------------------------------------------------------------+
| Payload: Allocated memory paragraphs                                  |
+-----------------------------------------------------------------------+
```

### Runtime MCB Chain Analysis

When `PLAYONE.EXE` is loaded and running film playback, conventional memory is partitioned into the following primary blocks:

| Block Role | Typical Size | Relative Segment | Description |
|---|---|---|---|
| **Environment Block** | ~1,168 bytes | Base allocation | Holds DOS environment variables and execution paths |
| **Program Binary Block** | ~202,832 bytes | Executable base | Unpacked code, static `DGROUP` data, stack, and font buffers |
| **Dynamic Scene Graph Buffer** | ~419,408 bytes | Heap allocation | 3D world geometry, camera tracks, and actor motion vectors |
| **Upper Memory / Driver Blocks** | ~81,904 bytes | Upper memory | Audio driver buffers, hardware DMA buffers |

### Memory Requirement Rationale

During startup, `PLAYONE.EXE` explicitly checks for at least **570,000 bytes** (`0x8B29` paragraphs) of free conventional RAM:

$$\text{Required Free Memory} = 570{,}000\text{ bytes} \approx 556.6\text{ KB}$$

This requirement accounts for:
1. **The uncompressed executable image**: $\approx 203\text{ KB}$.
2. **The 3D scene and trajectory buffer**: $\approx 419\text{ KB}$ dynamically allocated when `.ALL` and `.FLM` assets are loaded into memory.
3. **DOS scratch structures and I/O buffers**: File handle tables and sound hardware buffers.

If total available conventional memory falls below this threshold, the application aborts prior to allocating the dynamic scene graph.

---

## 3. Runtime Kinematics Evidence

During film playback, `PLAYONE.EXE` updates world-space kinematics and camera parameters on a discrete simulation clock. The installed INT 8 handler runs at **50 Hz** (PIT divisor `0x5D38` = 23,864), not the 20/30 Hz previously assumed; see [`timeline-and-ticks.md` § 1.1](../formats/concepts/timeline-and-ticks.md#11-hardware-timer-principles-in-ms-dos). The structures themselves are specified in [`MEMORY_MAP.md`](../../docs/MEMORY_MAP.md).

### 3.1 Post-Retrace Vertical Blank Trap

Contract and the unresolved `0C5E` conflict: [`MEMORY_MAP.md` `# [MEM-VSYNC-03DA]`](../../docs/MEMORY_MAP.md#-mem-vsync-03da).

The primary rendering loop synchronizes with VGA vertical retrace via port `0x03DA`. The listing below is the reconstruction recorded when the trap was introduced. **It is unverified**: it places a `call render_frame_flush` at `0D51:0C5E`, which [`startup.md`](startup.md) gives as the unpacked entry point, and its `0C50` bytes overlap the `0C50` offset `MEMORY_MAP` uses for the actor pointer in a different segment base. Treat it as illustrative until the live re-verification described in `MEMORY_MAP` is done.

```assembly
; Vertical Blank Wait Loop in PLAYONE.EXE (UNVERIFIED reconstruction)
0D51:0C48  mov    dx, 03DAh            ; VGA Input Status Register 1
0D51:0C4B  in     al, dx
0D51:0C4C  test   al, 08h               ; Test Vertical Retrace bit (Bit 3)
0D51:0C4E  jnz    0C4B                  ; Wait if retrace is already active
0D51:0C50  in     al, dx
0D51:0C51  test   al, 08h
0D51:0C53  jz     0C50                  ; Wait until vertical blank begins
; Execution breakpoint set immediately post-retrace:
0D51:0C5E  call   render_frame_flush    ; Trap address for tear-free capture
```

**Runtime behaviour (`[Bounded Observation]`, `CTRY.FLM` only).** Against the pinned DOSBox-X build, `BP 0D51:0C5E` followed by `RUN` returns in $\approx 50\text{ ms}$ and stops the guest at the loop boundary; each hit yields a whole Mode 13h page, and consecutive distinct pages advance the film's on-screen timecode by $\approx 65\text{ ms}$. This is the capture primitive used by [`capture.md`](capture.md). Because the VGA refresh runs at $\approx 70.087\text{ Hz}$, one hit can span several simulation ticks; the tick gating that follows from this is in `# [MEM-FLM-TICK]`.

### 3.2 Tick-Counter Evidence

This is the **only** copy of the evidence for the two tick counters; the contract is `# [MEM-FLM-TICK]` in [`MEMORY_MAP.md`](../../docs/MEMORY_MAP.md#-mem-flm-tick).

*Static (`[Established]`).* The 50 Hz handler at `0x53AF` calls the engine tick routine at `0x43A5` on every interrupt. It executes `inc word ptr [0x22B8]` (at `0x43B0`) only while the playback flag `DS:0x2272` is non-zero. The film reader at `0x3A88` compares the active film clock (`[bx+0x0E]`, struct base `0x4888` -> `DS:0x4896`) with the current slice's start tick, reads the next slice's `tick_duration` at `0x3B8D`, adds it at `0x3B19`, and divides elapsed ticks by it (`0x3AE9`–`0x3AF7`) for the sub-tick interpolation factor (`[Supported Inference]`, see [`timeline-and-ticks.md`](../formats/concepts/timeline-and-ticks.md)).

*Live (`[Established]`, DOSBox-X, `CS = 0x0F17`, `DS = 0x1575`, `CTRY.FLM`).* Both counters advance at 50 Hz, and the film clock `0x4896` runs 5 ticks ahead of the global `0x22B8`: ≈31 on the first captured film frame (global 26) and ≈1355 at the last animated frame (global 1350). That is consistent with the film's 1,342 authored ticks plus a short static hold.

*Negative results.* `DS:0x4758` (sibling `0x474A` struct, `+0x0E`) reads 0 throughout playback and is not the active clock. The legacy label `0D51:0C60` read 0 in early captures, so those captures were keyed by capture order alone; no instruction references `DGROUP:0x0C60` as a word, so the label is retired (in the unpacked image that offset is the entry instruction `mov bx, ss`).

*Harness use.* `DS` is taken as `0x1575` because the debugger has no register read (`--dgroup-segment` overrides it); see [`capture.md` § 3](capture.md#3-working-protocol) for how `film_tick` / `global_tick` are recorded.

### 3.3 Camera Rig & Actor Table: Provenance

The layouts are in [`MEMORY_MAP.md`](../../docs/MEMORY_MAP.md#-mem-camera-rig) under `# [MEM-CAMERA-RIG]` and `# [MEM-ACTOR-TABLE]`. The evidence record is thin and is stated here once:

* Both layouts were written by the offline `MockTransport` and decoded by the streamer against the same mock. They were never read from a live `PLAYONE.EXE`: the capture loop deliberately skips them ([`capture.md` § 3](capture.md#3-working-protocol)).
* This file used to carry a second, different actor-entry layout (`3×3 i16` matrix at `+0x18`, state mask at `+0x2A`) next to `MEMORY_MAP`'s quaternion layout, both tagged `[Established]`. Neither is supported by disassembly, so both were downgraded to `[Hypothesis]` and the duplicate was removed.
* What would settle it: a `MEMDUMPBIN` of the camera and actor regions at the post-retrace trap during playback (after the unpack lockout in § 3.4), compared with the `.FLM` slot values for the same film clock.

### 3.4 LZEXE Unpack Lockout (`# [MEM-UNPACK-LOCKOUT]`)

`PLAYONE.EXE` is LZEXE-packed (see [`startup.md`](startup.md)); until the decompressor has finished, `DGROUP` is not yet a stable image and **no debugger command may touch the guest**:

| Probe | Observed result |
|---|---|
| `MEMDUMPBIN 0D51:0C60 0002` at $\approx 2\text{ s}$ | guest spins on `Illegal Unhandled Interrupt Called 6` (19,893 log lines in 50 retraces), never recovers |
| `MEMDUMPBIN 0000:0000 1000` at $\approx 2\text{ s}$ | same exception storm |
| Read of `0040:001A` at $\approx 12\text{ s}$ after a `VRT` | emulator exits with `0xC0000409` (`STATUS_STACK_BUFFER_OVERRUN`) |
| Framebuffer `MEMDUMPBIN A000:0000 FA00` from boot | safe; the only access the driver performs before the load finishes |

Practical rule for the harness: wait for the `LOAD FILM` dialog page to stop changing using framebuffer dumps only, then issue memory reads and breakpoints.
