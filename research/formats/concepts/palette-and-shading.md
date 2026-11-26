---
summary: "[I3] palette model: DAC scalings, palettes 0x8042 and 0x801E, colour groups and 32-level ramps, an unlit ground, `SHADES` lit by film variable 13's light, the sky drawer's bands 224-238, 256x32 LUT."
sidebar_label: "Palette, shading ramps & VGA"
---
# Stunt Island Technical Reference: Palette Architecture, Shading Ramps & VGA Color Management

**Document Identifier:** `research/formats/concepts/palette-and-shading.md`  
**Author:** Stunt Reel contributors  
**Governing Invariant:** `[I3]` (VGA Mode 13h 256-Color Palette Indexing, Flat Facet Shading, $256 \times 32$ LUT), `[I5]` (Coplanar Decals), `[I6]` (Visual Parity & 4:3 Aspect Ratio)  
**Status:** Asset-Isolated Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

*Stunt Island* (1992) targets the IBM Video Graphics Array (VGA) hardware running in standard Mode 13h ($320 \times 200$ pixels, 8 bits per pixel, 256 simultaneous colors chosen from an 18-bit hardware palette of $262{,}144$ colors).

In standard 1992 PC hardware, per-pixel floating-point lighting calculations (such as Phong or Blinn-Phong shading) and Gouraud interpolation were computationally prohibitive for complex 3D flight scenes at interactive framerates.
To achieve rich surface illumination, atmospheric depth, and material distinctions across aircraft fuselages, terrain, and cockpits, The Assembly Line designed an authentic table-driven lighting architecture:

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
The VGA Digital-to-Analog Converter (DAC, typically an Inmos INMOS G171 or compatible chip) features $256$ color registers.
Each register comprises three 6-bit digital intensity channels: Red, Green, and Blue ($R, G, B \in [0, 63]$):
- **Hardware Precision:** $6\text{ bits per channel} \implies 64\text{ discrete levels per primary} \implies 64^3 = 262{,}144\text{ total colors}$.
- **I/O Ports:**
  - `0x03C8` (PEL Address Write Mode Register): Sets starting palette index ($0..255$).
  - `0x03C9` (PEL Data Register): Three consecutive byte writes stream Red, Green, and Blue intensities (auto-incrementing to next palette index).
- **Modern 8-Bit Normalization (the single definition; other documents link here):** three 6-bit to 8-bit scalings appear in this project.
  They agree at `0` and `63` only by construction, so the code that uses each is named:

  | Name | Formula ($c \in [0, 63]$) | White ($c = 63$) | Used by |
  | :--- | :--- | :--- | :--- |
  | **Capture scaling** (canonical for DAC reads) | $\lfloor (255c + 31) / 63 \rfloor$ | `255` | `parse_dac_palette` in the retired `transport.py` (formerly `_scale_6bit` in `framebuffer.py`; the same rule now lives in the generated Lua and `plan.py`), applied to every `VGA DACPAL` read of the reference capture ([`capture.md`](../../playone-exe/capture.md)) |
  | Bit replication | $(c \ll 2) \mid (c \gg 4)$ | `255` | none; an approximation of the capture scaling that differs by 1 at $c \in \{11..15, 48..52\}$ |
  | **Authored table** | $c \ll 2$ | `252` | `MODE_13H_PALETTE` in `crates/stunt-core/src/contracts/palette/mod.rs` (every stored channel is a multiple of 4; the test pins index 255 to `(252, 252, 252)`) and, through it, the `stunt-render` LUT |

  Normalized division $c / 63.0$ is the same quantity as the capture scaling before rounding.
  Consequence: the native renderer's palette tops out at `252` while the captured reference reaches `255`, a $\le 3/255$ channel offset.
  Its effect on the `[I6]` SSIM scores has not been measured; treat it as a known discrepancy, not an equivalence.
  Whether the authored table should store capture-scaled values is an open decision `[Hypothesis]`; the table's literals are the Stunt Island master palette (240 scene entries plus 16 UI entries), transcribed from the community SODParse `pal.h` in the Stunt Island Central archive.
  They are game-derived, not the IBM VGA default and not a synthetic construction, and were not re-derived from a DAC read.

**Governing invariants:** [`[I3]`](../../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading), [`[I5]`](../../../docs/SPEC.md#i5-coplanar-decal-resolution), [`[I6]`](../../../docs/SPEC.md#i6-visual-parity-acceptance-thresholds--vga-112-aspect-ratio-correction).
**Contract and code:** [`contracts/`](../../../crates/stunt-core/src/contracts/mod.rs).
Fixtures: [`tests/fixtures/README.md`](../../../tests/fixtures/README.md).

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

In `crates/stunt-core/src/contracts/shape/mod.rs`, vertices emitted by `.SOD` display lists store their authentic Mode 13h palette correspondence in an aligned 28-byte GPU vertex layout:

```rust
#[repr(C)]
pub struct SodVertex {
    pub position: [f32; 3],  // Offset +0x00 (12 bytes)
    pub normal: [f32; 3],    // Offset +0x0C (12 bytes)
    pub palette_index: u8,   // Offset +0x18 (1 byte: 0..=255)
    pub flags: u8,           // Offset +0x19 (1 byte: bitflags)
    pub scenery_class: u8,   // Offset +0x1A (1 byte: 1 ocean, 2 terrain, 3 prop; 0 elsewhere)
    pub decal_tie: u8,       // Offset +0x1B (1 byte: 1 in a decal tie, else 0)
}
```

#### Vertex Flag Bitfield (`flags: u8`)
- **Bit 0 (`0x01`) — Coplanar Decal (`is_decal`):** Identifies coplanar surface markings (runway stripes, aircraft insignias, wing stars).
  Drawn in `wgpu`'s ordered decal pass (depth bias, no depth write), and moved $\epsilon = 0.001\text{ m}$ toward its front only by the glTF exporter (`[I5]`).
- **Bit 1 (`0x02`) — Two-Sided Facet:** Disables back-face culling for this polygon.
- **Bit 2 (`0x04`) — Emissive / Unshaded:** Bypasses directional lighting table; renders at full unshaded diffuse brightness (used for landing lights and muzzle flares).
  The parity look draws every polygon at the full-brightness row whatever this bit says; the modern look lights a bit-2 face by its normal like any other (the world's ground and ocean carry it), exempting only bit 7.
- **Bits 3..5 (`0x08`, `0x10`, `0x20`) — Screen-space line corner:** a one-pixel line's corner, its side and its end; the vertex's `normal` is then the vector to the segment's other endpoint (`VERTEX_FLAG_LINE`, `VERTEX_FLAG_LINE_SIDE`, `VERTEX_FLAG_LINE_END`).
- **Bit 6 (`0x40`) — Disc rim vertex:** a vertex of an `OP_PERFDISK` disc's outline; its `normal` is then the vector to the disc's centre, about which the renderer squeezes the disc along the view's depth by the lens zoom and moves it onto the pixels `0xD11D` fills (`VERTEX_FLAG_DISC`, [`sod-vm-generators.md` § 8.8](../../playone-exe/sod-vm-generators.md#88-model-frame-the-other-generators)).
- **Bit 7 (`0x80`) — Pre-shaded:** the vertex's palette index already carries its light, because the decoder coloured it from a `SHADE*` ramp or shaded it per vertex with `GVPOLY`/`GVPOLY16`, or because it belongs to an `OP_ANIMATE` sprite's drawn art (`VERTEX_FLAG_PRESHADED`, [`terrain-shade.md` § 3](../../playone-exe/terrain-shade.md#3-per-vertex-shade-shades-opcode-0x0156)).
  The parity look ignores it and the decoder's weld key leaves it out.
  The viewer-only modern look draws such a vertex unlit, so its light is not applied twice.

`decal_tie` is 1 on a filled decal's vertices, and on those of each earlier coplanar polygon it overlaps within their plane, so a world prop's decal keeps its tie on a steep facet ([`sod-vm-lines-spans.md` § 8.14](../../playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)).

A world prop vertex carries no record of its shape: the world lists its prop vertices as runs with each run's shape (`World::prop_runs`), and the renderer looks a vertex up there for the parity plane's shape word ([`attribution.md`](../../parity/attribution.md) § 1).

### 2.3 Transparency Keys

1. **Color Index `0x00` (`#000000`):** Transparent key for `.SPR` sprite bitmaps, 2D UI decals, font characters, and billboard smoke particles.
   During rasterization, pixels with index `0` write neither color nor depth.
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

#### What the Capture Shows About Lighting
`[Bounded Observation]` Unlit palette colours match the original.
In `CTRY.FLM` capture ordinal 41 (tick 448) the airfield ground is index 196, $(69, 121, 45)$, over 43k of the 59k viewport pixels.
A sun-vector shader (`ambient + (1 - ambient) * max(n . sun, 0)`, ambient 0.25) drew it at 41% brightness.
`mean_ssim_scored` on `CTRY` (114 frames): lit 0.689, two-sided lit 0.764, constant lighting row 31 (palette colour as is) **0.766**, row 26 0.760, row 22 0.745, row 16 0.700; across four capture sets row 31 scores 0.766, 0.767, 0.767, 0.766.
Full brightness is best and dimming is worse, so the ground takes no sun-derived level: 162 and 163 beside 196 are themselves ground-leaf colours ([`world-scene.md` § 2](../../playone-exe/world-scene.md#2-the-ground-leaves-and-their-colour)), and `OP_SHADES` lights the shapes that use it (`[BK-PAL-03]`, § 4).
`mode13h.wgsl` draws every fragment at row 31; its camera uniform carries no sun-direction or ambient-intensity term.
_Found 2026-10-22; see the [parity log](../../../work/2026-10/parity-log/log.md)._

#### Sky Bands
`[Established]` for the law, read from the sky drawer `0x8C45` (`0824:0A05`) and its helpers, and matched live on `BALLOON.FLM` (below).
Before the scene, `PLAYONE` paints the view with up to 16 flat polygons: sky bands of indices 224 to 238 and, below the last, `0xD0` (208).
Their edges are 15 points it projects straight ahead in heading: edge `j` (0 to 14) passes through `j · 1024` along the unit horizontal of the view's depth row and `2048 - 128 j` up (`0x8E02`, accumulators `work:0x41B0..0x41B4` stepped by `0x41B6`, `0x80`, `0x41BA`), so its elevation is `atan((16 - j) / 8j)`:

| Edge `j` | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Elevation (degrees) | 90 | 61.9 | 41.2 | 28.4 | 20.6 | 15.4 | 11.8 | 9.1 | 7.1 | 5.6 | 4.3 | 3.3 | 2.4 | 1.7 | 1.0 |

* **Each edge is a straight screen line parallel to the horizon**, through the edge point's projection, perpendicular to the screen direction of world vertical (the two screen rows' vertical components `work:0x80C2`, `0x80C8`, halved until the larger is at most `0x200`, give the segment's half-length).
  It is not the curve of constant elevation, so off the heading a band edge sits at a lower elevation than its table value, and the curvature our old per-pixel elevation rule drew never appears.
* **The walk** goes from the zenith down.
  It skips edges until one is on screen: an edge is off when its depth word is under `0x100` (the depth row is shifted right by the lens shift `work:0x810C`) or its segment misses the view (`0xBBF3`).
  The screen beyond the first edge on screen takes colour `224 + j` of that edge; each later edge starts colour `224 + j + 1`; the first edge off screen after that ends the walk, its own colour `224 + j` filling the rest; a walk that draws edge 14 fills below it with `0xD0` (`0x8E6C`, colour `0xEF - k` with `k = 15 - j`, and `0xD0` at `k = 0`).
  So 224 is the sky beyond the zenith, 225 to 227 the bands from 90 down to 28.4 degrees, 228 to 238 the rest, and `0xD0` the strip below 1.0 degree.
* **With no edge on screen** the view is one fill: 224 when the view looks up (the depth row's vertical component points up, `0x8DF2`), `0xD0` when it looks down; a view whose screen rows have no vertical component at all takes the same fill (`0x8DCC`).
* **Rows**: an edge's row belongs to the band below it, since each fill spans the rows from the previous edge to one above this edge (`0x8EB2`).
* **The last band runs to the view's edge**: when the walk ends, its closing edge is the view's bottom row `work:0x41C6` (its top row `0x41C4` when `work:0x80C8` is negative), so the band after the last edge drawn, the `0xD0` fill after edge 14, reaches the last row of the view (`0x8D94..0x8DB9`; the fill to one row above the closing edge read in `0x8E6C`'s branch `0x8EA4..0x8EB3`, both `work:0x80C2` and `0x80C8` non-negative, its branches at `0x8F22` and `0x8F99` not read).
  The drawer computes no horizon row: the strip a capture shows ends where the scene, drawn after the sky, covers it, and where that scene is the 208 ocean, strip and ocean meet with no other index between them.
  `[Established]`, static, unpatched image, not traced live.
  _Source: [where the sky drawer stops the `0xD0` fill](../../../work/2026-11/893_sky-fill-strip/journal.md#2026-11-22-where-the-sky-drawer-stops-the-0xd0-fill-read-statically)._
* **The sun** is drawn after the bands, or before the `0xD0` fill when the walk reached edge 14, which covers it; never in a view looking down with no edge on screen ([`palette-fade.md` § 3.2](../../playone-exe/palette-fade.md#32-other-readers-of-the-live-variables)).

`[Bounded Observation]` for the live match: on `BALLOON.FLM`, Patch #3, DOSBox-X 2026.10.01, a model of this walk fed the view matrix logged at the loop start `0x8D36` reproduced the edge rows (`0x8D64`) and fill colours (`0x8E86`) of all 17 frames logged in full, ticks 223 to 267, to the pixel.
It also accounts for the `vault-balloon` capture: the sky of ticks 12 to 200 is all 224 because the view (76.6 degrees up, zoom 1.9) has the zenith edge above the screen and edge 1 below it, and that of ticks 276 to 298 is all 208 because the view looks down with no edge on screen.
The edge medians measured earlier on `CTRY.FLM` captures through our camera (2.14 to 20.23 degrees, 238 at the horizon to 228) are edges 13 to 4.
Captures show 224 to 226 as shape paint too, so parity counts them as sky only by position ([`method.md`](../../parity/method.md) section 2.0).
_Source: [the sky drawer, the sun disc and the var-13 light read live on BALLOON](../../../work/2026-11/617_zenith-bands-sun-disc/journal.md#2026-11-20-the-sky-drawer-the-sun-disc-and-the-var-13-light-read-live-on-balloon)._

The renderer lays the walk out per view on the CPU from its own camera (`crates/stunt-render/src/sky.rs`) and the sky pass picks each pixel's band and tests the disc (`sky_index` in `mode13h.wgsl`), at the same pixel rules.

### 3.3 The Modern GPU Palette Lookup Texture (LUT)

Modern GPU pipelines (`crates/stunt-render/`) cannot emulate VGA DAC registers directly.
Under invariant **`[I3]`**, authentic visual reproduction is achieved via an uncompressed **$256 \times 32$ 2D Palette Lookup Texture (LUT)**:

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

## 4. Open Questions & Analysis Backlog

1. **`[BK-PAL-01]` Dynamic Palette Rotation in Night Scenes** (`[Bounded Observation]`): Disassembly of `PLAYONE.EXE` indicates timer-driven palette cycling for runway approach lights and lightning flashes.
   Precise register cycling ranges remain to be verified.
2. **`[BK-PAL-02]` CRT Phosphor Gamma vs sRGB Transfer** (`[Supported Inference]`): Vintage 1990s cathode-ray tube (CRT) monitors exhibited a native gamma curve of $\gamma \approx 2.4$.
   The current $256 \times 32$ LUT outputs linear sRGB values; an optional post-processing toggle is reserved for future milestones.
3. **`[BK-PAL-03]` Opcode `0x0156` `OP_SHADES` Bytecode Behavior**: `[Established]`, static: it stores `-clamp((N . L) >> 16, ±0x3FFF)` per normal for the shade opcodes ([`terrain-shade.md` § 3](../../playone-exe/terrain-shade.md#3-per-vertex-shade-shades-opcode-0x0156)).
   `L` is the world light at `DS:0x49EC`, written by the film-variable-13 handler `0x196C` (`[Bounded Observation]`: the one writer found; indirect stores unchecked), turned for a rotated object ([§ 4.2](../../playone-exe/terrain-shade.md#42-who-hands-it-the-light)); no reading so far ties it to the `.SET` `time_of_day`.
   _Source: [SHADES lights from film variable 13](../../../work/2026-11/472_research-contradictions/journal.md#2026-11-13-shades-lights-from-film-variable-13-not-from-the-set-time-of-day)._
4. **`[BK-PAL-04]` Undocumented DAC Shimmer in 70 Hz Vertical Blank** (`[Hypothesis]`): Hypothesis that high-frequency palette register modification during active scan lines produced intentional horizontal gradient banding on authentic CRT monitors.

---

## 5. Attribution & Provenance

- **Dave Palmowski & Dean Newbury:** Comprehensive documentation of Stunt Island color groups, 16/32-level lighting ramps, and preservation of `si.pal`, `si.act`, and `shading.doc` in `corpus/siarchive/SITools/SpriteMaker/` and `corpus/siarchive/SITools/Docs/`.
- **Adrian Stephens (1997):** Analysis of subobject palette index mapping, conditional color substitution, and translucent propeller disc rendering (`corpus/siarchive/SITools/Docs/Adrian_Subobjects.txt`).
- **Doug Armknecht (2002):** Analysis of `.FLM` timeline horizon and sky palette indices (`horizon_sky_palette`) and color state tracking in `corpus/siarchive/Developer/SI_FLM_Format/` (`FLM_NOTES.md`, `FLM_FORMAT_DOUG_NOTES.txt`).
- **Neil Halelamien (2004):** Analysis of `.SET` time-of-day simulation scalars modulating palette lighting levels in `corpus/siarchive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **FreeFlight Development Team:** Analysis of `.ALL` palette container chunks (`0x8042` and `0x801E`) in `corpus/siarchive/Developer/FreeFlight/src/sires.cpp` and `SIPAL.H`.
- **Stunt Reel contributors (2026):** Milestone 1 & 2 $256 \times 32$ GPU LUT architecture, `@interpolate(flat)` pipeline design, and visual parity specification (`crates/stunt-render/`).

---
