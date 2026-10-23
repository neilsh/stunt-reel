# Stunt Island Technical Reference: Palette Architecture, Shading Ramps & VGA Color Management

**Document Identifier:** `research/formats/concepts/palette-and-shading.md`  
**Author:** `worker_fmt_concepts`  
**Governing Invariant:** `[I3]` (VGA Mode 13h 256-Color Palette Indexing, Flat Facet Shading, $256 \times 32$ LUT), `[I5]` (Coplanar Decals), `[I6]` (Visual Parity & 4:3 Aspect Ratio)  
**Status:** Cleanroom Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

*Stunt Island* (1992) targets the IBM Video Graphics Array (VGA) hardware running in standard Mode 13h ($320 \times 200$ pixels, 8 bits per pixel, 256 simultaneous colors chosen from an 18-bit hardware palette of $262{,}144$ colors).

In standard 1992 PC hardware, per-pixel floating-point lighting calculations (such as Phong or Blinn-Phong shading) and Gouraud interpolation were computationally prohibitive for complex 3D flight scenes at interactive framerates. To achieve rich surface illumination, atmospheric depth, and material distinctions across aircraft fuselages, terrain, and cockpits, The Assembly Line designed an authentic table-driven lighting architecture:

```
+-------------------------------------------------------------------------------+
| Light Vector L & Surface Normal N                                             |
| 1. Compute dot product: intensity = clamp(dot(N, L), 0.0, 1.0)                 |
| 2. Quantize into discrete lighting level: level in [0..31]                     |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼
+-------------------------------------------------------------------------------+
| Palette Grouping & Shading Ramps                                              |
| - 256 colors partitioned into 16 groups of 16 colors                          |
| - Primary materials paired into 32-level composite ramps (Gray, Sand, Olive)  |
| - Discrete index lookup: shaded_index = ShadingTable[base_color][level]       |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼
+-------------------------------------------------------------------------------+
| Framebuffer Rasterization (VGA Mode 13h / Modern GPU LUT)                     |
| - DOS: Write 8-bit shaded_index to VGA VRAM at 0xA000:0000                    |
| - Modern GPU (stunt-render): Sample 256x32 RGBA LUT with @interpolate(flat)   |
| - Invariant [I3]: Zero bilinear color bleeding across hard facet boundaries   |
+-------------------------------------------------------------------------------+
```

### 1.1 VGA Hardware DAC Principles
The VGA Digital-to-Analog Converter (DAC, typically an Inmos INMOS G171 or compatible chip) features $256$ color registers. Each register comprises three 6-bit digital intensity channels: Red, Green, and Blue ($R, G, B \in [0, 63]$):
- **Hardware Precision:** $6\text{ bits per channel} \implies 64\text{ discrete levels per primary} \implies 64^3 = 262{,}144\text{ total colors}$.
- **I/O Ports:**
  - `0x03C8` (PEL Address Write Mode Register): Sets starting palette index ($0..255$).
  - `0x03C9` (PEL Data Register): Three consecutive byte writes stream Red, Green, and Blue intensities (auto-incrementing to next palette index).
- **Modern 8-Bit Normalization (the single definition; other documents link here):** three 6-bit to 8-bit scalings appear in this project. They agree at `0` and `63` only by construction, so the code that uses each is named:

  | Name | Formula ($c \in [0, 63]$) | White ($c = 63$) | Used by |
  | :--- | :--- | :--- | :--- |
  | **Capture scaling** (canonical for DAC reads) | $\lfloor (255c + 31) / 63 \rfloor$ | `255` | `_scale_6bit` in `python/stunt_reel/tac/framebuffer.py`, applied to every `VGA DACPAL` read of the reference capture ([`capture.md`](../../playone-exe/capture.md)) |
  | Bit replication | $(c \ll 2) \mid (c \gg 4)$ | `255` | none; an approximation of the capture scaling that differs by 1 at $c \in \{11..15, 48..52\}$ |
  | **Authored table** | $c \ll 2$ | `252` | `MODE_13H_PALETTE` in `crates/stunt-core/src/contracts/palette.rs` (every stored channel is a multiple of 4; the test pins index 255 to `(252, 252, 252)`) and, through it, the `stunt-render` LUT |

  Normalized division $c / 63.0$ is the same quantity as the capture scaling before rounding. Consequence: the native renderer's palette tops out at `252` while the captured reference reaches `255`, a $\le 3/255$ channel offset. Its effect on the `[I6]` SSIM scores has not been measured; treat it as a known discrepancy, not an equivalence. Whether the authored table should store capture-scaled values is an open decision `[Hypothesis]`; the table's literals came from `pal.h` and were not re-derived from a DAC read.

**Governing invariants:** [`[I3]`](../../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading), [`[I5]`](../../../docs/SPEC.md#i5-coplanar-decal-resolution), [`[I6]`](../../../docs/SPEC.md#i6-visual-parity-acceptance-thresholds--vga-112-aspect-ratio-correction). **Contract and code:** [`contracts/`](../../../crates/stunt-core/src/contracts/mod.rs). Fixtures: [`tests/fixtures/README.md`](../../../tests/fixtures/README.md).

---

## 2. Memory Layout & Bitfield Representations

### 2.1 The Master Palette Chunks (`.ALL` Archive Container)

In *Stunt Island* scene packages (`.ALL`), color tables are packaged as raw binary chunks indexed by permanent 16-bit resource identifiers:

```
+-------------------------------------------------------------------------------+
| Master Palette (Chunk ID 0x8042): 240 Colors (720 Bytes)                      |
| Indices 0..239: 240 x 3-byte RGB triplets (6-bit DAC values or 8-bit expanded) |
| Matches community reference si.pal bit-for-bit.                               |
+-------------------------------------------------------------------------------+
| UI & Highlight Sub-Palette (Chunk ID 0x801E): 16 Colors (48 Bytes)            |
| Indices 240..255: 16 x 3-byte RGB triplets (UI buttons, HUD, bright keys)      |
+-------------------------------------------------------------------------------+
```

#### Chunk Memory Layout

| Chunk ID | Resource Name | Offset Range | Total Bytes | Color Indices | Payload Description |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x8042` | Master Palette | `+0x0000`–`0x02CF` | $720\text{ bytes}$ | `0`–`239` | 240 RGB triplets forming the base 15 material groups. Bit-exact match with `si.pal`. |
| `0x801E` | UI / Highlight | `+0x0000`–`0x002F` | $48\text{ bytes}$ | `240`–`255` | 16 RGB triplets defining fixed UI borders, green transparency key, cockpit HUD lines. |

### 2.2 Vertex Palette Index & Decal Flags (`SodVertex`)

In `crates/stunt-core/src/contracts/scene.rs`, vertices emitted by `.SOD` display lists store their authentic Mode 13h palette correspondence in an aligned 28-byte GPU vertex layout:

```rust
#[repr(C)]
pub struct SodVertex {
    pub position: [f32; 3],  // Offset +0x00 (12 bytes)
    pub normal: [f32; 3],    // Offset +0x0C (12 bytes)
    pub palette_index: u8,   // Offset +0x18 (1 byte: 0..=255)
    pub flags: u8,           // Offset +0x19 (1 byte: bitflags)
    pub _padding: [u8; 2],   // Offset +0x1A (2 bytes: alignment padding)
}
```

#### Vertex Flag Bitfield (`flags: u8`)
- **Bit 0 (`0x01`) — Coplanar Decal (`is_decal`):** Identifies coplanar surface markings (runway stripes, aircraft insignias, wing stars). Requires outward normal displacement ($\epsilon = 0.001\text{ m}$) under glTF export or hardware depth biasing in `wgpu` (`[I5]`).
- **Bit 1 (`0x02`) — Two-Sided Facet:** Disables back-face culling for this polygon.
- **Bit 2 (`0x04`) — Emissive / Unshaded:** Bypasses directional lighting table; renders at full unshaded diffuse brightness (used for landing lights and muzzle flares).
- **Bits 3..7 (`0xF8`):** Reserved (must be zero).

### 2.3 Transparency Keys

1. **Color Index `0x00` (`#000000`):** Transparent key for `.SPR` sprite bitmaps, 2D UI decals, font characters, and billboard smoke particles. During rasterization, pixels with index `0` write neither color nor depth.
2. **Color Index `0xF0` / `240` (`#00FF00`, Pure Green):** Transparent key marker in authoring tools (PCX import) and chroma-key matte plates in the Film Editor.
3. **Color Index `0xFF` / `255` (`#FFFFFF`, Pure White):** Full-bright emissive overlay indicator, reserved for heads-up display (HUD) reticles and text banners.

---

## 3. Data Structures, Tables & Conversion Algorithms

### 3.1 The 16 Functional Color Groups

The 256 palette entries are partitioned into 16 logical groups of 16 contiguous colors each ($16 \times 16 = 256$):

```
Group:  0    1    2    3    4    5    6    7    8    9    10   11   12   13   14   15
Index: [000..015][016..031][032..063][064..095][096..127][128..159][160..191][192..207][208..239][240..255]
       | Ambient | Crimson | Neutral | Desert  | Olive   | Metal / | Grass / | Earth / | Sky /   | UI /   |
       | Shadow  | Insignia| Gray    | Sand    | Camo    | Twilight| Meadow  | Dirt    | Water   | System |
```

#### Full Palette Group Structure & Material Classification

| Group | Index Range | Color Domain / Material Theme | Darkest Index | Brightest Index | Shading Dynamics |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Group 0** | `0`–`15` | Monochrome Shadow / Ambient Floor | `0` (`#000000`) | `15` (`#837373`) | 16-level ambient occlusion & shadow ramp |
| **Group 1** | `16`–`31` | Crimson Red / Insignias / Fire | `16` (`#3F0F1B`) | `31` (`#FF9FDF`) | 16-level aircraft insignia and explosion ramp |
| **Group 2+3**| `32`–`63` | Neutral Gray & Pure White | `32` (`#534343`) | `63` (`#F7F7F7`) | **32-level composite ramp**: Fuselages, concrete, clouds |
| **Group 4+5**| `64`–`95` | Desert Tan & Sandstone | `64` (`#3F3723`) | `95` (`#FFDB8B`) | **32-level composite ramp**: Sand dunes, rocks, canyons |
| **Group 6+7**| `96`–`127`| Dark Olive & Camouflage Drab | `96` (`#2B271B`) | `127` (`#A79F63`) | **32-level composite ramp**: Military armor, olive drab |
| **Group 8** | `128`–`143`| Night Sky / Deep Twilight Violet | `128` (`#000000`)| `143` (`#7387DB`)| 16-level atmospheric dusk/night sky dome |
| **Group 9** | `144`–`159`| Slate Gray / Cold Steel | `144` (`#73574F`)| `159` (`#BBBFCB`)| 16-level gunmetal and prop blades |
| **Group 10+11**|`160`–`191`| Island Grassland & Forest Green | `160` (`#536353`)| `191` (`#BBBB67`)| **32-level composite ramp**: Island vegetation, trees |
| **Group 12**| `192`–`207`| Earth Brown & Terracotta Brick | `192` (`#274717`)| `207` (`#97006F`)| 16-level building roofs and plowed soil |
| **Group 13+14**|`208`–`239`| Sky Blue & Ocean Water | `208` (`#134B7B`)| `239` (`#FFFB97`)| **32-level composite ramp**: Sea surface, horizon haze |
| **Group 15**| `240`–`255`| UI Chrome / HUD / System Keys | `240` (`#00FF00`)| `255` (`#FFFFFF`)| Fixed interface buttons, reticles, text overlays |

### 3.2 32-Level Composite Shading Ramps

For prominent materials (aircraft fuselages, desert terrain, military olive camouflage, island grass, ocean water), the engine combines two adjacent 16-color groups into a seamless **32-level continuous luminance ramp**:
- **Lower Half (Indices $0..15$ of the 32-level ramp):** Corresponds to deep shade and cast shadow.
- **Midpoint (Index $16$):** Nominal unshaded diffuse surface color.
- **Upper Half (Indices $17..31$):** Sunlit specular highlight and atmospheric glare.

```
Composite Ramp (32 Levels):
Level: 0 ........... 8 ........... 16 ........... 24 ........... 31
Color: [  Deep Shadow  ] -------- [ Diffuse Base ] -------- [ High Glare ]
       <-- Low 16 Group ->        <-- High 16 Group ->
```

### 3.3 The Modern GPU Palette Lookup Texture (LUT)

Modern GPU pipelines (`crates/stunt-render/`) cannot emulate VGA DAC registers directly. Under invariant **`[I3]`**, authentic visual reproduction is achieved via an uncompressed **$256 \times 32$ 2D Palette Lookup Texture (LUT)**:

```
                  256 Base Palette Indices (X axis: 0..255)
      0 ---------------------------------------------------- 255
    0 +------------------------------------------------------+ (Full Shadow)
      |                                                      |
L   8 |                                                      |
i     |                                                      |
g  16 |=================== NOMINAL DIFFUSE ==================|
h     |                                                      |
t  24 |                                                      |
    31 +------------------------------------------------------+ (Sun Glare)
```

- **Texture Dimensions:** Width = $256$ texels, Height = $32$ texels.
- **Texture Format:** `wgpu::TextureFormat::Rgba8Unorm` ($256 \times 32 \times 4 = 32{,}768\text{ bytes}$).
- **Row Index ($Y \in [0, 31]$):** Quantized directional lighting level, evaluated from $\mathbf{n} \cdot \mathbf{l}$.
- **Column Index ($X \in [0, 255]$):** Base palette index stored in `SodVertex::palette_index`.

#### WGSL Flat Shading & LUT Sampling Implementation
To prevent bilinear color bleeding across hard polygonal facet edges, the vertex shader outputs the palette index using the `@interpolate(flat)` attribute:

```wgsl
struct VertexOutput {
    @builtin(position) clip_position: vec4<f32>,
    @location(0) @interpolate(flat) palette_index: u32,
    @location(1) @interpolate(flat) light_level: u32,
};

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    // Exact texel coordinate lookup: no bilinear filtering between adjacent indices!
    let tex_coord = vec2<i32>(i32(in.palette_index), i32(in.light_level));
    return textureLoad(t_palette_lut, tex_coord, 0);
}
```

---

## 4. Open Questions & Reverse Engineering Backlog

1. **`[BK-PAL-01]` Dynamic Palette Rotation in Night Scenes** (`[Bounded Observation]`): Disassembly of `PLAYONE.EXE` indicates timer-driven palette cycling for runway approach lights and lightning flashes. Precise register cycling ranges remain to be verified.
2. **`[BK-PAL-02]` CRT Phosphor Gamma vs sRGB Transfer** (`[Supported Inference]`): Vintage 1990s cathode-ray tube (CRT) monitors exhibited a native gamma curve of $\gamma \approx 2.4$. The current $256 \times 32$ LUT outputs linear sRGB values; an optional post-processing toggle is reserved for future milestones.
3. **`[BK-PAL-03]` Opcode `0x0156` `OP_SHADES` Bytecode Behavior** (`[Established]`): Confirmed across `.SOD` models that `OP_SHADES` dynamically recalculates polygon facet lighting levels based on the sun direction vector loaded from `.SET` `time_of_day`.
4. **`[BK-PAL-04]` Undocumented DAC Shimmer in 70 Hz Vertical Blank** (`[Hypothesis]`): Hypothesis that high-frequency palette register modification during active scan lines produced intentional horizontal gradient banding on authentic CRT monitors.

---

## 5. Attribution & Provenance

- **Dave Palmowski & Dean Newbury:** Comprehensive documentation of Stunt Island color groups, 16/32-level lighting ramps, and preservation of `si.pal`, `si.act`, and `shading.doc` in `corpus/si_archive/SITools/SpriteMaker/` and `corpus/si_archive/SITools/Docs/`.
- **Adrian Stephens (1997):** Analysis of subobject palette index mapping, conditional color substitution, and translucent propeller disc rendering (`corpus/si_archive/SITools/Docs/Adrian_Subobjects.txt`).
- **Doug Armknecht (2002):** Reverse engineering of `.FLM` timeline horizon and sky palette indices (`horizon_sky_palette`) and color state tracking in `corpus/si_archive/Developer/SI_FLM_Format/` (`FLM_NOTES.md`, `FLM_FORMAT_DOUG_NOTES.txt`).
- **Neil Halelamien (2004):** Reverse engineering of `.SET` time-of-day simulation scalars modulating palette lighting levels in `corpus/si_archive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **FreeFlight Development Team:** Reverse engineering of `.ALL` palette container chunks (`0x8042` and `0x801E`) in `corpus/si_archive/Developer/FreeFlight/src/sires.cpp` and `SIPAL.H`.
- **Alberto Marnetto (2024):** Color palette and memory patching research in `corpus/si_archive/Developer/SI-8x/si-8x-notes.txt`.
- **StuntReel Teamwork Team (2026):** Milestone 1 & 2 $256 \times 32$ GPU LUT architecture, `@interpolate(flat)` pipeline design, and visual parity specification (`explorer_fmt_aux_concepts/analysis.md`, `crates/stunt-render/`).

---
