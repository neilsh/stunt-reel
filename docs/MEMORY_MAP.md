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
| `0x2263` | `[Established]` | `u8` | Active display mode flag | |
| `0x2264` | `[Established]` | `u8` | Sound hardware driver mode | |
| `0x2265` | `[Established]` | `u8` | Audio playback channel flag | |

---

## 2. Runtime Dynamic Capture Anchors

### # [MEM-VSYNC-03DA]
* **I/O Port**: `0x03DA` (VGA Input Status Register 1)
* **Routine**: Vertical retrace polling loop (`in al, dx; test al, 08h`).
* **Protocol**: A one-time breakpoint `BPIO 03DA` isolates the polling loop address; execution breakpoint `BP <CS:IP>` is then set immediately *after* the vertical blank loop completes to capture fully rendered frame state without mid-frame tearing.
* **Evidentiary Tier**: `[Established]`.

### # [MEM-FLM-TICK]
* **Segment / Scope**: `DGROUP`
* **Data Type**: 16-bit unsigned integer (`u16`)
* **Behavior**: Advances strictly once per unique simulation time slice (20 Hz or 30 Hz). Because Mode 13h refreshes at 70 Hz, the streamer gates snapshot capture on:
  $$\text{current\_tick} > \text{last\_captured\_tick}$$
  preventing duplicate frame capture.
* **Evidentiary Tier**: `[Established]`.

### # [MEM-CAMERA-RIG]
* **Segment / Scope**: `DGROUP`
* **Structure Layout**:
  * Eye World Position: $(X, Y, Z)$ 32-bit fixed-point / float meters.
  * Look-At Target Position: $(X, Y, Z)$ 32-bit fixed-point / float meters.
  * Zoom / Focal Distance: 16-bit integer scalar converted to vertical $\text{FOV}_y$ via:
    $$\text{FOV}_y = 2 \arctan\left(\frac{120.0}{\text{focal\_dist}}\right) \times \frac{180}{\pi}$$
  * View Roll: 16-bit BAM angle converted via $\theta = (\text{raw\_u16} / 65536.0) \times 2\pi$.
  * Camera Rig Mode ID: Integer identifier tracking active camera rig.
* **Evidentiary Tier**: `[Supported Inference]`.

### # [MEM-ACTOR-TABLE]
* **Segment / Scope**: Dynamic Heap / `DGROUP`
* **Structure Layout**:
  * Model Identifier: Null-terminated string or 16-bit resource index (e.g. `"FOKKER"`).
  * World Position: $(X, Y, Z)$ metric meters `[I1]`.
  * Rotation: $3 \times 3$ direction cosine matrix or Euler BAM angles converted to unit quaternion `[x, y, z, w]`.
  * State Mask: 16-bit bitmask (visibility, smoke, gear state).
  * Joint BAM Angles: Slice of child subobject rotation angles `(joint_index, bam_u16)`.
* **Evidentiary Tier**: `[Supported Inference]`.
