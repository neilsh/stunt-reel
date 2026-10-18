# Runtime Memory Map & Real-Mode Offsets

* **Target Binary**: `PLAYONE.EXE` (Unpacked LZEXE 0.91 image)
* **Base Load Data Segment (`DGROUP`)**: Segment `0x0D51` (file offset `0xD910` in unpacked image)
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
| `0x0C10` | `[Established]` | Struct (32B) | Active camera rig descriptor | `# [MEM-CAMERA-RIG]` |
| `0x0C50` | `[Established]` | Far Pointer (32b) | Heap pointer to dynamic actor channel table | `# [MEM-ACTOR-TABLE]` |
| `0x0C5E` | `[Established]` | Code Offset | Post-0x03DA vertical retrace breakpoint trap target | |
| `0x0C60` | `[Established]` | `u16` | Monotonic simulation tick counter | `# [MEM-FLM-TICK]` |
| `0x2263` | `[Established]` | `u8` | Active display mode flag | |
| `0x2264` | `[Established]` | `u8` | Sound hardware driver mode | |
| `0x2265` | `[Established]` | `u8` | Audio playback channel flag | |

---

## 2. Runtime Dynamic Capture Anchors

### # [MEM-VSYNC-03DA]
* **I/O Port**: `0x03DA` (VGA Input Status Register 1)
* **Routine**: Vertical retrace polling loop (`in al, dx; test al, 08h`).
* **Protocol**: A one-time breakpoint `BPIO 03DA` isolates the polling loop address; execution breakpoint `BP <CS:IP>` is then set immediately *after* the vertical blank loop completes (`0D51:0C5E`) to capture fully rendered frame state without mid-frame tearing.
* **Evidentiary Tier**: `[Established]`.

### # [MEM-FLM-TICK]
* **Segment / Scope**: `DGROUP` (Segment `0x0D51`, Offset `0x0C60`, Linear `0x0E170`)
* **Data Type**: 16-bit unsigned integer (`u16`)
* **Behavior**: Advances strictly once per unique simulation time slice (20 Hz or 30 Hz). Because Mode 13h refreshes at 70 Hz, the streamer gates snapshot capture on:
  $$\text{current\_tick} > \text{last\_captured\_tick}$$
  preventing duplicate frame capture.
* **Evidentiary Tier**: `[Established]`.

### # [MEM-CAMERA-RIG]
* **Segment / Scope**: `DGROUP` (Segment `0x0D51`, Offset `0x0C10`, Linear `0x0E120`)
* **Evidentiary Tier**: `[Established]`.
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
* **Segment / Scope**: Dynamic Heap Buffer addressed by Far Pointer at `0x0D51:0C50` (or local stage block `0x0D51:0CA0`)
* **Evidentiary Tier**: `[Established]`.
* **Byte Layout Specification (64 bytes per actor entry)**:
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
