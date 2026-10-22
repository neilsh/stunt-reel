# Stunt Island Technical Reference: Coordinates, Units & Spatial Mathematics

**Document Identifier:** `research/formats/concepts/coordinates-and-units.md`  
**Author:** `worker_fmt_concepts`  
**Governing Invariant:** `[I1]` (Metric Right-Handed Coordinate Basis, Attribute-Preserving Vertex Welding, BAM Angles, Vertical $\text{FOV}_y$)  
**Status:** Cleanroom Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

The 1992 *Stunt Island* flight simulation and film playback engine executes spatial mathematics across multiple distinct coordinate frames. Designed for IBM PC-compatible systems featuring 16-bit x86 microprocessors (Intel 80286 / 80386SX) running MS-DOS in real mode without guaranteed floating-point hardware (80287/80387 FPUs), the engine relies extensively on signed and unsigned fixed-point integer arithmetic.

Modern presentation engines and interchange formats (glTF 2.0, WebGPU) mandate IEEE 754 32-bit floating-point metrics and standard Cartesian coordinate conventions. To bridge legacy 16-bit DOS simulation records and modern GPUs without accumulated drift or matrix tearing, the StuntReel architecture establishes invariant **`[I1]`**: all spatial representations are ingested, transformed, and validated against a unified right-handed metric basis.

### 1.1 The Coordinate Hierarchy

Spatial computation in *Stunt Island* is decomposed into four hierarchical coordinate domains:

```
+-------------------------------------------------------------------------------+
| 1. Model Space (.SOD / .SIO)                                                  |
|    - 16-bit signed integer offsets (dx, dy, dz in [-32768, +32767])           |
|    - Scaled by per-model power-of-two decay table: sod_scale_table[scale]    |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼  (Articulated joints & model transform)
+-------------------------------------------------------------------------------+
| 2. World / Stage Space (.SET / .FLM)                                          |
|    - 32-bit fixed-point 16.16 signed meters relative to island origin         |
|    - Island center anchor: (100000, 0, 100000) editor units (10 EU = 1 meter) |
|    - Rotations: 16-bit Binary Angular Measurement (BAM: 0..65535 = 0..360°)   |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼  (Camera eye, target, roll matrix)
+-------------------------------------------------------------------------------+
| 3. View / Eye Space (Presentation Camera)                                     |
|    - Right-handed metric: +X Right, +Y Up, +Z Toward Viewer, -Z Forward       |
|    - Vertical Field of View (FOVy) derived from integer focal distance        |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼  (Perspective projection & 1:1.2 aspect)
+-------------------------------------------------------------------------------+
| 4. Screen Space (VGA Mode 13h)                                                |
|    - 320 x 200 pixels, non-square pixel aspect ratio (PAR = 1.2)              |
|    - Normalized to 4:3 display (320 x 240 effective resolution) [I6]          |
+-------------------------------------------------------------------------------+
```

### 1.2 Right-Handed Metric Basis (`[I1]`)

Under invariant **`[I1]`**, world and model coordinates adhere strictly to the standard right-handed Cartesian coordinate system adopted by glTF 2.0 and modern robotics:
- **$+X$ Axis:** Points horizontally to the **Right** (corresponds to **East** in island world space).
- **$+Y$ Axis:** Points vertically **Upward** (corresponds to **Altitude** above sea level).
- **$+Z$ Axis:** Points **Backward**, out of the screen toward the viewer (corresponds to **South** in island world space).
- **$-Z$ Axis:** Points **Forward**, into the screen away from the viewer (corresponds to **North** in island world space).

```
          +Y (Up / Altitude)
           │
           │
           │
           └─────── +X (Right / East)
          ╱
         ╱
        +Z (Backward / South / Toward Viewer)
       [-Z is Forward / North / Into Screen]
```

**DOS axes `[Bounded Observation]`:** The raw frame of `.FLM` slots and anchor points (`GLOSSARY.md`) maps to `[I1]` by a $180^\circ$ rotation about $Z$. Positions: $(x, y, z) \rightarrow (-x, -y, z)$. Orientations: $\mathbf{q}' = \mathbf{q}_{z180} \cdot \mathbf{q}$ with $\mathbf{q}_{z180} = [0, 0, 1, 0]$ in $[x, y, z, w]$ order, so a zero raw rotation evaluates to $\mathbf{q}_{z180}$, not the identity. Camera-local `roll_radians` is unchanged. The `.FLM` evaluator applies this to every slot, so evaluated `TrajectoryRecord`s are always `[I1]`. Evidence: the `CTRY.FLM` tick 1 view slot has raw $y = -14.0$ (negative altitude), terrain applies $(-x, -y, z)$ to `ANCHORPT.DAT` anchor points, and `docs/SPEC.md` § 3.8; the orientation rule is the same rigid rotation and has not been checked independently.

**Open question:** the evaluator negates the stored pitch `rx` before building the quaternion (`docs/SPEC.md` § 3.7), which hints that the raw rotation convention may differ in handedness from `[I1]`, beyond the $180^\circ$ Z rotation above. Not resolved here; see `Q-FLM-08` in [`flm.md`](../flm.md).

---

## 2. Memory Layout & Bitfield Representations

### 2.1 Fixed-Point Integer Bitfields

The engine employs two primary integer fixed-point layouts:

#### 1. 32-Bit Signed Fixed-Point ($16.16$ Format)
Encountered in `.SET` prop coordinates and `.FLM` kinematic update streams:

```
Bit:  31 30 29 ... 17 16 15 14 13 ... 1  0
     [      Integer      |    Fractional   ]
      <-- Signed 16-bit -> <-- Unsigned 16-bit
```

- **Integer Component (Bits 16..31):** Signed 16-bit two's complement integer representing whole meters (range: $[-32768, +32767]\text{ m}$).
- **Fractional Component (Bits 0..15):** Unsigned 16-bit fraction representing increments of $\frac{1}{65536}\text{ m} \approx 1.52588 \times 10^{-5}\text{ m}$ ($15.26\ \mu\text{m}$).
- **Byte Ordering:** Little-endian (LSB first: fractional low byte, fractional high byte, integer low byte, integer high byte).

#### 2. 16-Bit Signed Model Space Integers
Encountered in `.SOD` vector operations (`OP_VECTORS` `0x0075`, `OP_PUTV` `0x0012`) and `.SIO` slice geometry (`TAG_VERTEX` `0x12`):

```
Bit:  15 14 13 12 11 10 9  8  7  6  5  4  3  2  1  0
     [ S |                 Signed Magnitude          ]
```
- Range: $[-32768, +32767]$ model units.
- Evaluated against `sod_scale_table` to establish physical metric dimensions.

### 2.2 Binary Angular Measurement (BAM)

Angular values in *Stunt Island*—including aircraft flight attitude (Pitch, Roll, Yaw), camera look vectors, and rotating subobject joints (propellers, flaps, landing gear)—are strictly represented as **16-bit unsigned integers** ($\text{BAM} \in [0, 65535]$):

```
Bit:  15   14   13   12   11   10   9    8    7    6    5    4    3    2    1    0
     [180°|90° |45° |22.5| ...                                              | LSB ]
```

Each bit in a BAM word represents a binary subdivision of a complete $360^\circ$ circle ($2\pi\text{ radians}$):
- **Bit 15:** $180.0^\circ$ ($\pi\text{ rad}$)
- **Bit 14:** $90.0^\circ$ ($\pi/2\text{ rad}$)
- **Bit 13:** $45.0^\circ$ ($\pi/4\text{ rad}$)
- **Bit 12:** $22.5^\circ$ ($\pi/8\text{ rad}$)
- **Bit 0 (LSB):** $\frac{360^\circ}{65536} \approx 0.00549316^\circ$ ($\approx 9.58738 \times 10^{-5}\text{ rad}$).

#### Exact BAM Equivalence Table

| BAM Value (Hex) | BAM Value (Dec) | Fraction of Circle | Angle (Degrees) | Angle (Radians) | Geometric Interpretation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x0000` | `0` | $0/65536$ | $0.0^\circ$ | $0.0$ | Neutral / Forward Facing |
| `0x2000` | `8192` | $1/8$ | $45.0^\circ$ | $\pi / 4 \approx 0.785398$ | Eighth Turn (Half-Right) |
| `0x4000` | `16384` | $1/4$ | $90.0^\circ$ | $\pi / 2 \approx 1.570796$ | Quarter Turn (East / Pitch Up) |
| `0x8000` | `32768` | $1/2$ | $180.0^\circ$ | $\pi \approx 3.141593$ | Half Turn (South / Inverted) |
| `0xC000` | `49152` | $3/4$ | $270.0^\circ$ | $3\pi / 2 \approx 4.712389$ | Three-Quarter Turn (West / Pitch Down) |
| `0xFFFF` | `65535` | $65535/65536$ | $359.9945^\circ$ | $2\pi - \epsilon$ | Maximum Representable BAM Step |

---

## 3. Data Structures, Tables & Conversion Algorithms

### 3.1 The SOD Model Scale Factor Table

In `.SOD` geometry files, raw 16-bit integer vertices are multiplied by a scalar selected via a 16-bit scale exponent index stored in the model header (Word offset `+0x06`). This scalar is defined in community reverse-engineering archives (`corpus/si_archive/Developer/SODParse/SOD.H`):

```c
static float sod_scale_table[] = {
    10.0,              // scale = 0
    5.0,               // scale = 1
    5.0 / 2.0,         // scale = 2  (2.5)
    5.0 / 4.0,         // scale = 3  (1.25)
    5.0 / 8.0,         // scale = 4  (0.625)
    5.0 / 16.0,        // scale = 5  (0.3125)
    5.0 / 32.0,        // scale = 6  (0.15625)
    5.0 / 64.0,        // scale = 7  (0.078125)
    5.0 / 128.0,       // scale = 8  (0.0390625)
    5.0 / 256.0,       // scale = 9  (0.01953125)
    5.0 / 512.0,       // scale = 10 (0.009765625)
    5.0 / 1024.0,      // scale = 11 (0.0048828125)
    5.0 / 2048.0,      // scale = 12 (0.00244140625)
    5.0 / 4096.0,      // scale = 13 (0.001220703125)
    5.0 / 8192.0,      // scale = 14 (0.0006103515625)
    5.0 / 16384.0,     // scale = 15 (0.00030517578125)
    5.0 / 32768.0,     // scale = 16 (0.000152587890625)
    5.0 / 65536.0,     // scale = 17 (0.0000762939453125)
};
```

#### Analytical Formula for Model Scaling
For scale index $s \in [0, 17]$:
$$\text{ScaleFactor}(s) = \begin{cases} 10.0 & \text{if } s = 0 \\ 5.0 \times 2^{-(s - 1)} & \text{if } 1 \le s \le 17 \end{cases}$$

Given a raw vertex $[x_{\text{raw}}, y_{\text{raw}}, z_{\text{raw}}] \in \mathbb{Z}^3$, the metric model coordinates $[x_{\text{m}}, y_{\text{m}}, z_{\text{m}}]$ are evaluated as:
$$\mathbf{v}_{\text{m}} = \mathbf{v}_{\text{raw}} \times \text{ScaleFactor}(s)$$

### 3.2 World Space Conversion (.SET & .FLM)

World-space scenery layout (`.SET`) and film choreography (`.FLM`) anchor the simulation domain to a $20\text{ km} \times 20\text{ km}$ island bounding square.

#### The Island Center Offset Discovery
In `.SET` files, prop positions are specified in editor units ($EU \in [0, 200000]$), where the origin $(0, 0, 0)$ of the metric simulation world is positioned at editor coordinate $(100000, 0, 100000)$.

As confirmed empirically by Neil Halelamien (2004) in `corpus/si_archive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`, changing editor units produces $16.16$ fixed-point increments scaled by a factor of 10:

```
Editor Coordinate -> Hexadecimal 16.16 Bytes (LE) -> Metric Meters
  100000 (Origin) -> 00 00 00 00                 -> 0.00 m
  100001 (+1 EU)  -> 99 19 00 00 (0x00001999)    -> 0.10 m  (6553.6 / 65536)
  100005 (+5 EU)  -> 00 80 00 00 (0x00008000)    -> 0.50 m  (32768 / 65536)
  100010 (+10 EU) -> 00 00 01 00 (0x00010000)    -> 1.00 m  (65536 / 65536)
  100100 (+100 EU)-> 00 00 0A 00 (0x000A0000)    -> 10.00 m (655360 / 65536)
  099990 (-10 EU) -> 00 00 FF FF (0xFFFFFFFF)    -> -1.00 m
```

#### Analytical Conversion Formula
Given editor units $[X_{\text{ed}}, Y_{\text{ed}}, Z_{\text{ed}}]$:
$$X_{\text{meters}} = \frac{X_{\text{ed}} - 100000.0}{10.0}, \quad Y_{\text{meters}} = \frac{Y_{\text{ed}}}{10.0}, \quad Z_{\text{meters}} = \frac{Z_{\text{ed}} - 100000.0}{10.0}$$

In `.FLM` binary streams, positions are already serialized as raw 32-bit $16.16$ fixed-point integers:
$$X_{\text{dos}} = \frac{X_{\text{fixed32}}}{65536.0}, \quad Y_{\text{dos}} = \frac{Y_{\text{fixed32}}}{65536.0}, \quad Z_{\text{dos}} = \frac{Z_{\text{fixed32}}}{65536.0}$$

These are meters in DOS axes; the evaluator then applies $(x, y, z) \rightarrow (-x, -y, z)$ to reach `[I1]` (see § 1.2).

### 3.3 Angular Conversions & Natural Modular Arithmetic

Conversion between 16-bit BAM and floating-point radians/degrees is defined as:
$$\theta_{\text{radians}} = \left(\frac{\text{BAM}}{65536.0}\right) \times 2\pi, \quad \theta_{\text{degrees}} = \left(\frac{\text{BAM}}{65536.0}\right) \times 360.0^\circ$$

#### Zero-Cost Modulo Wrapping
A major architectural advantage of BAM in real-mode 16-bit software is that native 16-bit unsigned integer addition and subtraction automatically compute modulo $2\pi$ rotations with zero branch penalties and zero floating-point drift:
$$(65530 + 10) \pmod{65536} = 4 \equiv (359.967^\circ + 0.055^\circ = 0.022^\circ)$$

### 3.4 Rotation Conventions & Unit Quaternions (Seam 2)

Actor transforms in `Seam 2: TrajectoryRecord` decompose Euler rotations into normalized unit quaternions $\mathbf{q} = [q_x, q_y, q_z, q_w] \in \mathbb{H}$ satisfying:
$$\left| \|\mathbf{q}\| - 1.0 \right| < 10^{-4}$$

The engine evaluates Euler rotations in **Yaw $(\psi)$, Pitch $(\theta)$, Roll $(\phi)$** order:
1. **Yaw ($\psi$, Heading):** Rotation around the $+Y$ vertical axis.
2. **Pitch ($\theta$, Elevation):** Rotation around the $+X$ lateral axis.
3. **Roll ($\phi$, Bank):** Rotation around the $-Z$ longitudinal forward axis.

#### Column-Major World Matrix Generation
Given position $\mathbf{t} = [t_x, t_y, t_z]$ and normalized quaternion $\mathbf{q} = [q_x, q_y, q_z, q_w]$, the $4 \times 4$ affine transform matrix is computed per `ActorTransform::compute_world_matrix`:

$$M = \begin{bmatrix}
1 - 2(y^2 + z^2) & 2(xy + wz) & 2(xz - wy) & 0 \\
2(xy - wz) & 1 - 2(x^2 + z^2) & 2(yz + wx) & 0 \\
2(xz + wy) & 2(yz - wx) & 1 - 2(x^2 + y^2) & 0 \\
t_x & t_y & t_z & 1
\end{bmatrix}$$

### 3.5 Camera Focal Distance & Vertical Field of View ($\text{FOV}_y$)

In *Stunt Island*'s DOS rasterizer, zoom is parameterized by an integer focal distance (`focal_dist` in `[MEM-CAMERA-RIG]`). Under invariant **`[I1]`**, this is converted to physical vertical field of view ($\text{FOV}_y$) in degrees.

Mode 13h framebuffers render at $320 \times 200$, but are stretched vertically by $1.2$ on physical $4:3$ CRT displays to an effective height of $240$ lines. The half-height of this projection plane is $H_{\text{half}} = 120.0$.

$$\text{FOV}_y = 2 \arctan\left(\frac{120.0}{\text{focal\_dist}}\right) \times \frac{180^\circ}{\pi}$$

#### Sample Camera Focal Length Conversions

| Focal Distance (`focal_dist`) | Calculated $\text{FOV}_y$ | Lens Equivalent | Typical Usage |
| :--- | :--- | :--- | :--- |
| `69` | $120.2^\circ$ | Ultra-wide / Fisheye | Cockpit high-speed flyby |
| `120` | $90.0^\circ$ | Wide angle | Chase plane camera |
| `289` | $45.0^\circ$ | Normal lens (Default) | Standard cinematic view |
| `600` | $22.6^\circ$ | Telephoto lens | Tracking camera from control tower |
| `1200` | $11.4^\circ$ | Extreme telephoto | Long-distance runway spotter |

### 3.6 Attribute-Preserving Vertex Welding

Fixed-point calculations can introduce sub-millimeter precision mismatches at polygon junctions, causing T-junction raster cracks. Invariant **`[I1]`** requires vertex snapping within $\epsilon_{\text{weld}} = 10^{-4}\text{ m}$.

However, to strictly preserve *Stunt Island*'s hard facet normals under flat shading and prevent color bleeding across adjacent facets, vertices cannot be welded by spatial position alone. Instead, vertex deduplication in `SodModelIr` keys on the full attribute tuple:

$$\text{WeldKey} = \left(\text{quantize}(\mathbf{position}, 10^{-4}\text{ m}),\; \text{quantize}(\mathbf{normal}, 10^{-3}),\; \text{palette\_index},\; \text{flags}\right)$$

---

## 4. Architectural Invariants & Coordinate Mapping

| Invariant | System Rule | Mathematical Implementation |
| :--- | :--- | :--- |
| **`[I1]`** | Right-Handed Metric Basis | $+X$ Right, $+Y$ Up, $+Z$ Backward, $-Z$ Forward. Model vertices scaled by `sod_scale_table`. |
| **`[I1]`** | 16-bit BAM Angles | $\theta = (\text{BAM} / 65536.0) \times 2\pi$. Automatic modulo $2\pi$ wrap-around. |
| **`[I1]`** | Vertical Field of View | $\text{FOV}_y = 2 \arctan(120.0 / \text{focal\_dist}) \times (180/\pi)$. |
| **`[I1]`** | Attribute Welding | Position snapped at $10^{-4}\text{ m}$; hard facet normals and palette indices preserved. |
| **`[I2]`** | Arena Node Hierarchy | All transform matrices stored column-major in flat `Vec<SodNode>` indexed by `NodeId(u32)`. |
| **`[I5]`** | Decal Normal Nudging | Decal vertices displaced outward along surface normal: $\mathbf{v}' = \mathbf{v} + 0.001\hat{\mathbf{n}}$. |

---

## 5. Open Questions & Reverse Engineering Backlog

1. **`[BK-COORD-01]` Collision Bounding Box Rounding** (`[Bounded Observation]`): In `STUNT.EXE`, spatial collision checks round prop coordinates to nearest 8-unit boundaries. Verification is required to determine whether `.FLM` choreography playback honors these bounding boxes or operates entirely unconstrained.
2. **`[BK-COORD-02]` Spotter Plane Camera Offset** (`[Supported Inference]`): In `.SET` files, the spotter plane camera (View Mode 6) stores view pitch at offset `0xFF..0x100`. Evidence suggests the camera target is locked to the player aircraft with a trailing displacement of $150\text{ m}$.
3. **`[BK-COORD-03]` Single-Precision Floating Point Roundoff at Island Edges** (`[Established]`): World coordinates near extreme island borders ($X, Z \approx \pm 10{,}000\text{ m}$) maintain $\sim 7$ decimal digits of precision in IEEE 754 32-bit floats, providing sub-millimeter resolution ($< 0.5\text{ mm}$), confirming that 32-bit floats are fully sufficient for zero-loss reproduction of 16-bit DOS simulation data.
4. **`[BK-COORD-04]` Coprocessor Auto-Detection & Trig Table Resolution** (`[Hypothesis]`): Hypothesis that the simulation executable detects an 80287/80387 FPU at runtime to bypass 16-bit integer BAM sine/cosine lookup tables in favor of `FSIN`/`FCOS` instructions during interactive flight.

---

## 6. Attribution & Provenance

- **Neil Halelamien (2004):** Reverse engineering of `.SET` file structures, 16.16 fixed-point coordinate discovery, editor-to-world origin shift (`100000, 0, 100000`), and BAM facing angles in `corpus/si_archive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt` and `SET_File_Email_Thread.txt`.
- **Adrian Stephens (1997):** First documented analysis of subobject rotational joints, propeller animation parameters, and landing gear angular indices during SIFA IRC discussions in `corpus/si_archive/SITools/Docs/Adrian_Subobjects.txt`.
- **Doug Armknecht (2002):** Reverse engineering of `.FLM` trajectory streaming, binary angle parsing, and position extraction scripts in `corpus/si_archive/Developer/SI_FLM_Format/` (`FLM_FORMAT_DOUG_NOTES.txt`, `FLM_NOTES.md`).
- **Dave Palmowski (1999–2001):** Author of SLICE and SODParse, establishing `sod_scale_table` constants and 16-bit integer model vertex definitions in `corpus/si_archive/Developer/SODParse/SOD.H` and `corpus/si_archive/SITools/Slice/`.
- **StuntReel Teamwork Team (2026):** Milestone 1 & 2 mathematical synthesis, glTF 2.0 basis alignment, attribute-preserving vertex welding, and Seam 1–4 contracts (`explorer_fmt_aux_concepts/analysis.md`, `crates/stunt-core/src/contracts/trajectory.rs`).

---

## 7. Codebase Seam Contracts & Fixtures

### 7.1 Seam Contracts
- **`crates/stunt-core/src/contracts/mod.rs`**: System invariant declarations (`[I1]` Metric right-handed coordinate basis).
- **`crates/stunt-core/src/contracts/trajectory.rs`**:
  - `CameraTransform`: `eye: [f32; 3]`, `target: [f32; 3]`, `fov_degrees: f32`, `roll_radians: f32`, `cut_from_previous: bool`.
  - `ActorTransform`: `position_meters: [f32; 3]`, `rotation_quat: [f32; 4]`, `world_matrix: [f32; 16]`, `compute_world_matrix()`, `joint_angles_bam: Vec<(u16, u16)>`.
  - `TrajectoryRecord`: Master simulation snapshot at tick $t$.
- **`crates/stunt-core/src/contracts/scene.rs`**:
  - `SodVertex`: 28-byte GPU vertex layout (`position: [f32; 3]`, `normal: [f32; 3]`, `palette_index: u8`, `flags: u8`).
  - `SodModelIr`: Flat arena model container.

### 7.2 Cleanroom Synthetic Fixtures
- **`tests/fixtures/oracle_intro_trajectory.json`**: Golden oracle recording 600 continuous ticks adhering to metric right-handed basis and unit quaternion normalization.
- **`tests/fixtures/synthetic_minimal.flm`**: 15-byte choreography stream validating BAM angles and 16.16 fixed-point coordinate decoding.
- **`tests/fixtures/synthetic_minimal.sod`**: 76-byte procedural bytecode model exercising `sod_scale_table` scale 1 ($5.0 / 2^0 = 5.0$).
