# `PLAYONE.EXE`: Memory Architecture & Data Segment Layout

This document details the real-mode x86 memory layout, static data segment (`DGROUP`) pointers, dynamic heap allocations, and Memory Control Block (MCB) structure of `PLAYONE.EXE`.

---

## 1. Segment Architecture & DGROUP Map

`PLAYONE.EXE` executes as a 16-bit MS-DOS real-mode application. Static variables, string literals, and system buffers reside within the primary data segment `DGROUP`.

* **Image Dump Base**: paragraph `0x0D51` (unpacked file offset `0xD910`). This is the snapshot base used by earlier dumps, not the runtime segment.
* **Runtime Register Context**: in the captured session `CS = 0x0F17` and `DS = 0x1575`; table offsets below are `DS`-relative.

### DGROUP Offset Reference Table

| Offset in `DS` | Data Type | Value / Purpose |
|---|---|---|
| `0x05AC` | Null-terminated string | `"game.cfg"` — Hardware and sound driver configuration file |
| `0x05B5` | Null-terminated string | `"game.var"` — Game variables and runtime state definition |
| `0x05BE` | Null-terminated string | `"install.exe"` — Configuration installer executable |
| `0x05CA` | Null-terminated string | `"pfont.bin"` — Proportional UI font metrics and bitmap data |
| `0x05D4` | Null-terminated string | `"pilots"` — Pilot profile folder path |
| `0x05DB` | Null-terminated string | `"res\*.res"` — Core resource archive wildcard pattern |
| `0x065D` | DOS String (`$`-terminated) | `"Not enough memory.  Stunt Island requires 570,000 bytes free."` |
| `0x069B` | DOS String (`$`-terminated) | `"Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."` |
| `0x0A58` | Null-terminated string | `"VAULT\*.*"` — Search pattern for film loading dialog |
| `0x0A62` | Null-terminated string | `"LOAD FILM"` — Title string rendered on file dialog header |
| `0x0AAB` | Character Buffer | Destination buffer storing the selected film relative path |
| `0x0C10` | 32-byte Struct | Active camera rig descriptor (`# [MEM-CAMERA-RIG]`) |
| `0x0C50` | 32-bit Far Pointer | Dynamic actor channel table heap pointer (`# [MEM-ACTOR-TABLE]`) |
| `0x0C5E` | Code Offset | Post-0x03DA vertical retrace breakpoint trap target |
| `0x0C60` | — | Historic tick-counter label; no code reference exists in the unpacked image (see § 3.1) |
| `0x2263` | 8-bit Byte | Active video/display mode flag |
| `0x2264` | 8-bit Byte | Sound driver hardware mode |
| `0x2265` | 8-bit Byte | Audio playback channel flag |
| `0x22B8` | 16-bit Word (`u16`) | Monotonic 50 Hz global timer tick |
| `0x22C4` | 16-bit Word | Stored PSP segment address |
| `0x22CE` | 16-bit Word | Preserved `SS` register during `INSTALL.EXE` child execution |
| `0x22D0` | 16-bit Word | Preserved `SP` register during `INSTALL.EXE` child execution |
| `0x4758` | 16-bit Word (`u16`) | Sibling `0x474A` struct field; reads 0 during live playback, not the active clock |
| `0x4896` | 16-bit Word (`u16`) | Active film playback clock (struct base `0x4888` + `0x0E`), in 50 Hz ticks (`# [MEM-FLM-TICK]`) |

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

## 3. Runtime Kinematics, Camera Rig & Actor Table Layouts

During film playback, `PLAYONE.EXE` updates world-space kinematics and camera parameters on a discrete simulation clock. The installed INT 8 handler runs at **50 Hz** (PIT divisor `0x5D38` = 23,864), not the 20/30 Hz previously assumed; see [`../formats/concepts/timeline-and-ticks.md` § 1.1](../formats/concepts/timeline-and-ticks.md#11-hardware-timer-principles-in-ms-dos). These structures reside at fixed `DGROUP` locations and dynamically allocated heap blocks.

### 3.1 Post-Retrace Vertical Blank Trap (`# [MEM-VSYNC-03DA]`)

The primary rendering loop synchronizes with VGA vertical retrace via port `0x03DA`:

```assembly
; Vertical Blank Wait Loop in PLAYONE.EXE
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

Because the hardware VGA refresh runs at $\approx 70.087\text{ Hz}$, the active film clock at `DS:0x4896` (`# [MEM-FLM-TICK]`) can be checked at each trap hit. Capturing only when `current_tick > last_captured_tick` prevents duplicate frames.

**Runtime confirmation (`[Established]`).** Against the pinned DOSBox-X build, `BP 0D51:0C5E` followed by `RUN` returns in $\approx 50\text{ ms}$ during `CTRY.FLM` playback and stops the guest at the loop boundary; each hit yields a whole Mode 13h page, and consecutive distinct pages advance the film's on-screen timecode by $\approx 65\text{ ms}$. This trap is the capture primitive used by [`capture.md`](capture.md); `VRT` cannot substitute for it (the emulator exits with `0xC0000409` once playback starts).

**Tick gating (`[Established]`).** The legacy `0x0D51:0C60` reads returned `0`, so early captures were keyed by capture order alone. The capture now reads `DS:0x4896` (and `DS:0x22B8` for diagnosis) while the guest is halted at the trap and stores them as `film_tick` / `global_tick` in each `meta.json` frame; `stuntreel parity` matches on `film_tick`. `DS` is taken as `0x1575` (the T11 live observation) because the debugger has no register read; `--dgroup-segment` overrides it.

**Runtime tick counters (`[Established]`).** In the captured session the executable runs with `CS = 0x0F17` and `DS = 0x1575`; the image dump starts at segment `0x0D51`, which is a snapshot base, not `DS`. Live sampling during `CTRY.FLM` playback gives:
- `DS:0x22B8` — monotonic global 50 Hz timer tick, incremented by `inc word ptr [0x22B8]` at `0x43B0` while the playback flag `DS:0x2272` is set.
- `DS:0x4896` — active film clock (struct base `0x4888` + `0x0E`), advancing in lockstep with `0x22B8` while running 5 ticks ahead: ≈31 on the first captured film frame (global 26) and ≈1355 at the last animated frame (global 1350), consistent with the 1,342-tick authored span plus a short static hold.

`DS:0x4758` (sibling `0x474A` struct, `+0x0E`) reads 0 throughout live playback and is not the active clock. No instruction references `DGROUP:0x0C60` as a word; that label is retired.

### 3.2 Camera Rig Memory Structure (`# [MEM-CAMERA-RIG]`)

The active camera rig is stored at `DS:0x0C10` as a contiguous 32-byte descriptor:

| Offset in Rig | Field Name | Type | Scaling / Representation |
|---|---|---|---|
| `+0x00` | `eye_x` | `i32` LE | $16.16$ fixed-point / float meters per `[I1]` |
| `+0x04` | `eye_y` | `i32` LE | $16.16$ fixed-point / float meters (`+Y` up) |
| `+0x08` | `eye_z` | `i32` LE | $16.16$ fixed-point / float meters (`+Z` backward) |
| `+0x0C` | `target_x` | `i32` LE | Look-at target world X (meters) |
| `+0x10` | `target_y` | `i32` LE | Look-at target world Y (meters) |
| `+0x14` | `target_z` | `i32` LE | Look-at target world Z (meters) |
| `+0x18` | `focal_dist` | `u16` LE | Focal distance scalar $\to \text{FOV}_y = 2 \arctan\left(\frac{120.0}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$ |
| `+0x1A` | `roll_bam` | `u16` LE | View Roll angle $\to \theta = (\text{raw\_u16} / 65536.0) \times 2\pi\text{ rad}$ |
| `+0x1C` | `rig_mode_id` | `u16` LE | Active camera mode (cut flag set if mode changes or $\|\Delta\mathbf{eye}\| > 50\text{ m}$) |
| `+0x1E` | `reserved` | `u16` LE | Structure alignment padding (0x0000) |

### 3.3 Dynamic Actor Table (`# [MEM-ACTOR-TABLE]`)

The scene's active aircraft, vehicles, and props are tracked in a dynamic heap buffer referenced by a 32-bit far pointer at `DS:0x0C50` (or the default stage table at `DS:0x0CA0`). Each entry is 64 bytes:

```
+0x00: [u32] Actor Channel ID (0 = hero plane, 1..N = choreo channels)
+0x04: [char[8]] Bound .SOD model tag (null-padded ASCII, e.g. "FOKKER\0\0")
+0x0C: [i32 x 3] Metric World Position (X, Y, Z meters in 16.16 / IEEE float)
+0x18: [i16 x 9] 3x3 Direction Cosine Rotation Matrix (or unit quaternion [x, y, z, w])
+0x2A: [u16] Dynamic state bitmask (Bit 0: Visible, Bit 1: Smoke, Bit 2: Gear Down, Bit 3: Destroyed)
+0x2C: [u16] Articulated subobject count (M)
+0x2E: [u16 x 2 x M] Joint BAM angle array [(subobject_id, raw_bam_u16), ...]
+0x3C: [u32 far*] Pointer to next actor node (0x00000000 = end of list)
```

During streamer extraction, linked-list traversal enforces a maximum node depth (128 actors) and cycle detection to prevent infinite loops on corrupted memory blocks.

### 3.4 LZEXE Unpack Lockout (`# [MEM-UNPACK-LOCKOUT]`)

`PLAYONE.EXE` is LZEXE-packed (see [`startup.md`](startup.md)); until the decompressor has finished, `DGROUP` is not yet a stable image and **no debugger command may touch the guest**:

| Probe | Observed result |
|---|---|
| `MEMDUMPBIN 0D51:0C60 0002` at $\approx 2\text{ s}$ | guest spins on `Illegal Unhandled Interrupt Called 6` (19,893 log lines in 50 retraces), never recovers |
| `MEMDUMPBIN 0000:0000 1000` at $\approx 2\text{ s}$ | same exception storm |
| Read of `0040:001A` at $\approx 12\text{ s}$ after a `VRT` | emulator exits with `0xC0000409` (`STATUS_STACK_BUFFER_OVERRUN`) |
| Framebuffer `MEMDUMPBIN A000:0000 FA00` from boot | safe; the only access the driver performs before the load finishes |

Practical rule for the harness: wait for the `LOAD FILM` dialog page to stop changing using framebuffer dumps only, then issue memory reads and breakpoints.
