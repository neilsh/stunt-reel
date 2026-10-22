# Technical Reference Specification: Stunt Island `.FLM` Choreography & Trajectory Format

## 1. Overview & File Identification

The `.FLM` file format is *Stunt Island*'s native cinematic film recording and flight choreography stream. It records deterministic, sample-accurate choreography timelines that drive 3D actor positions, orientations, articulated subobjects, camera tracking channels, Director event variables, on-screen credit banners, and synchronized digital audio triggers.

In the retail game, `.FLM` files reside in the `vault\` directory (e.g., `ACT1.FLM`, `INTRO.FLM`, `DESERT.FLM`) and are paired 1:1 with companion `<NAME>.ALL` scene packages selected through the modal film dialog (`0x0787` in `PLAYONE.EXE`).

### Key File Attributes

| Attribute | Specification | Evidentiary Tier | Authoritative Citation |
| :--- | :--- | :---: | :--- |
| **File Extension** | `.FLM` (typically uppercase DOS 8.3, e.g., `INTRO.FLM`, `ACT1.FLM`, `FOKKER.FLM`) | `[Established]` | `research/playone-exe/startup.md` |
| **Magic Signature** | 4-byte ASCII: `b"FILM"` (`0x46, 0x49, 0x4C, 0x4D`) at byte offset `0x0000` | `[Established]` | `sifilm.cpp:72`, `flm_extract.py:76`, `synthetic_minimal.flm` |
| **Extension Variants** | 132 corpus files under `corpus/si_archive/Misc/` use the `.TKE` extension but are byte-identical `FILM` streams: all 132 parse as films (17,585 slices) | `[Established]` | corpus census, `verify-corpus` |
| **Byte Endianness** | Mixed: 16-bit integers and 32-bit fixed-point scalars are Little-Endian; composite time-slice headers feature a 16-bit back-pointer | `[Established]` | `sifilm.cpp:43-58`, cross-corpus verification |
| **Container Pairing** | Paired 1:1 with `<NAME>.ALL` full-scene container in `VAULT\` directory | `[Established]` | `PLAYONE.EXE:0x0787`, `docs/SPEC.md § 3.5` |
| **Engine Role** | Deterministic playback stream driving camera channels, 6-DOF actor trajectories, subobject joints, and sound triggers | `[Established]` | `docs/SPEC.md § 1.1`, `crates/stunt-core/src/contracts/trajectory.rs` |
| **Paired Contract** | `Seam 2: TrajectoryRecord` (`crates/stunt-core/src/contracts/trajectory.rs`) | `[Established]` | `# [FMT-FLM-OPCODES]`, `# [MEM-FLM-TICK]`, `docs/ARCHITECTURE.md` |

---

## 2. Header & Memory Layout

A `.FLM` file consists of a 4-byte ASCII signature followed by a contiguous sequence of variable-length time slices and a 3-byte end-of-film epilogue:

```
+---------------------------------------------------------------------------------+
|                        .FLM FILE ON-DISK STREAM LAYOUT                          |
+---------------------------------------------------------------------------------+
| Bytes 0x0000 - 0x0003: ASCII Magic Signature "FILM" (0x46, 0x49, 0x4C, 0x4D)     |
+---------------------------------------------------------------------------------+
| TIME SLICE 0 (Initial Scene Setup & Keyframe)                                   |
| - Header (3 bytes): prev_slice_len (u16 = 0x0000), tick_duration (u8 = 0)       |
| - Bytecode Stream: create / var_set / view_obj / credits_set                    |
| - Terminator (1 byte): 0xFF                                                     |
+---------------------------------------------------------------------------------+
| TIME SLICE 1 .. N (Chronological Simulation Ticks)                              |
| - Header (3 bytes): prev_slice_len (u16), tick_duration (u8)                    |
| - Bytecode Stream: interp kinematic updates / event triggers / sound cues       |
| - Terminator (1 byte): 0xFF                                                     |
+---------------------------------------------------------------------------------+
```

A Kaitai schema covers one slice, not the stream: [`flm_slice.ksy`](flm_slice.ksy) parses a single slice given the three slot masks, threading `create`-driven flag changes through a recursive opcode chain. Slice-to-slice state cannot cross a Kaitai `repeat`, so [`python/stunt_reel/flm_walk.py`](../../python/stunt_reel/flm_walk.py) walks the slice chain and supplies those masks. Corpus measurements: 627,696 slices across 561 of 568 films, 2,278,626 `interp` opcodes that depend on a `create` earlier in the same slice, and 109,185 `create` opcodes that flip a slot's `SIF_MOVES`/`SIF_ROTATES`/`SIF_ANIMATES` bit.

### 2.1 The Solved 3-Byte Slice Header (Reverse-Engineering Breakthrough)

Historically, community source code (`sifilm.cpp`, `flm_extract.py`) parsed slice headers as `inctime: u8` followed by `declared_len: u16`, observing with confusion that `declared_len` was mysteriously an exact multiple of 256 in ~99% of all slices.

Rigorous byte-level disassembly and cross-corpus mathematical analysis across **15,544 authentic slices** (verified with 100.000% bit-exact fidelity across 50 corpus films) established the true physical layout:

| Byte Offset | Field Name | Type | Description | Evidentiary Tier |
| :---: | :--- | :---: | :--- | :---: |
| `+0x00` | `prev_slice_len_lo` | `u8` | Low 8 bits of previous slice byte length | `[Established]` |
| `+0x01` | `prev_slice_len_hi` | `u8` | High 8 bits of previous slice byte length | `[Established]` |
| `+0x02` | `tick_duration` | `u8` | Ticks elapsed since the previous slice, in 50 Hz ticks ($20.0\text{ ms}$ each); cumulative sum gives this slice's timestamp; $0$ = same tick as previous slice | `[Established]` |

Together:
$$\text{prev\_slice\_len} = \text{prev\_slice\_len\_lo} \mid (\text{prev\_slice\_len\_hi} \ll 8)$$

#### Why the Back-Pointer Exists:
- **Slice 0:** $\text{prev\_slice\_len} == 0\text{x}0000$ (no preceding slice exists).
- **Slice $i \ge 1$:** $\text{prev\_slice\_len}$ equals the exact byte distance from the start of slice $i-1$ to the start of slice $i$.
- **VCR Reverse Scrubbing:** This field is the **reverse-scrubbing back-pointer** used by the Stunt Island Editing Room VCR engine to execute frame-by-frame rewinding (`REVERSE STEP`) without requiring random-access disk index tables!
- **Resolution of Historical Anomaly:** Because $98.5\%$ of slices are $< 256$ bytes in length, `prev_slice_len_hi` is $0$. When previous tools read Byte 0 (`prev_slice_len_lo`) and then read a 16-bit word at Bytes 1..2 (`prev_slice_len_hi | (tick_duration << 8)`), the word naturally evaluated to `tick_duration * 256`!

### 2.1.1 `tick_duration` Semantics & Corpus Distribution

`tick_duration` is the wall-clock interval elapsed since the previous slice, not a count of keyframes or a per-slice constant. `PLAYONE.EXE` advances its 50 Hz PIT tick counter (see [`concepts/timeline-and-ticks.md` § 1.1](concepts/timeline-and-ticks.md#11-hardware-timer-principles-in-ms-dos)); while loading a slice, it reads this byte and adds it to the running start tick (`0x3B8D` → `0x3B19`) before the slice pose is applied. The timestamp of slice $i$ is therefore $\sum_{k \le i}\text{tick\_duration}_k$, and the renderer interpolates from the previous pose to the current one across that interval. Slice 0 carries duration 0 and establishes the initial pose at tick 0.

Measured over all 561 walkable retail films (627,696 slices, 4,843,398 ticks):

| Property | Value |
| :--- | :--- |
| Tick clock | $50\text{ Hz}$ ($20.0\text{ ms}$/tick) |
| Distinct authored durations | $0$–$127$ (all 128 values occur) |
| Zero-duration slices | 142,171 ($22.65\%$); applied at the same tick as the next slice |
| Most common durations | $10$ (194,761), $0$ (142,171), $11$ (64,302), $1$ (35,144), $12$ (34,697) |
| Total corpus duration | $4{,}843{,}398 / 50 = 96{,}868\text{ s} \approx 26.9\text{ h}$ |
| `CTRY.FLM` | 140 slices, 1,342 ticks, $26.84\text{ s}$ |
| `INTRO.FLM` | 538 slices, 3,822 ticks, $76.44\text{ s}$ |

The dominant 10–11 tick modes are 200–220 ms keyframe intervals. Zero-duration slices carry event bursts (credits, sound cues, camera switches) that must be processed in file order without advancing time. A consumer that emits one record per slice (rather than expanding by `tick_duration`) compresses `CTRY.FLM` to 140 ticks ($2.8\text{ s}$ at 50 Hz) and loses all sub-tick motion. `FilmTimeline` avoids this by placing each slice at its cumulative tick; `TrajectoryRecord.tick` is therefore always a cumulative 50 Hz tick, never a slice ordinal.

### 2.2 End-of-Film Epilogue (`[Established]`)

The final slice is followed by a 3-byte epilogue: the last slice's `prev_slice_len` plus an end-of-stream marker. In 554 of 561 walkable corpus films the marker is `0xFF`; `MAMMOTH.FLM` and `MAMMOTH2.FLM` use `0x00`, and five films append filler after the marker. The `prev_slice_len` field equals the preceding slice's length in all 556 epilogue-bearing films.

The epilogue is not a slice: it has no opcode payload and no terminator of its own. Detection rule:

1. A slice header immediately followed by end-of-file is a header-only trailer and terminates the stream.
2. A header whose `tick_duration` byte is `0xFF` terminates the stream; any trailing bytes are filler. No authored slice in the 627,696-slice corpus exceeds `tick_duration = 0x7F`, so the marker is unambiguous.
3. The back-pointer chain should be validated, but a mismatch is a warning rather than a fatal error.

`python/stunt_reel/flm_walk.py` has implemented (1) and (2) since inception; `FlmParser::parse_slice` gained the same rule after it misread `CTRY.FLM`'s epilogue as a 141st slice.

---

## 3. Data Structures & Opcode Table

### 3.1 The Film Timeline State Machine

Each time slice contains a variable sequence of byte-tagged opcodes terminated by `0xFF`. The upper two bits (`opcode >> 6`) divide opcodes into four major functional classes:

```
 7   6   5   4   3   2   1   0
+---+---+---+---+---+---+---+---+
| Class |   Payload / Slot / Sub-Opcode   |
+---+---+---+---+---+---+---+---+
  00 (0x00..0x3F): Object Lifecycle / Create (Slots 0..63)
  01 (0x40..0x7F): Dynamic Kinematic Interpolation / Update (Slots 0..63)
  10 (0x80..0xBF): Engine Events & Control Commands (0x80..0xBF)
  11 (0xC0..0xFF): Extended / Reserved (0xFF = Slice Terminator)
```

### 3.2 Object Type Flags (`type_flags: u8`)

Encountered in Object Lifecycle opcodes (`0x00..0x3F`):

| Bit Flag | Mask | Name | Description & Engine Behavior |
| :---: | :---: | :--- | :--- |
| **Bit 0** | `0x01` | `SIF_EXISTS` | Slot Allocation: Slot is active in the scene. If cleared, object is destroyed/culled. |
| **Bit 1** | `0x02` | `SIF_DRAW` | 3D Renderable Mesh: Object binds a 3D `.SOD` mesh (`shape_id: u16`). **If cleared, object is an invisible camera rig or spatial locator!** |
| **Bit 2** | `0x04` | `SIF_SHADOW` | Ground Shadow: Object casts a flat-shaded projected ground shadow polygon. |
| **Bit 3** | `0x08` | `SIF_MOVES` | Dynamic Translation: Position changes per-slice; evaluated via `interp` stream. If cleared, position is fixed static keyframe. |
| **Bit 4** | `0x10` | `SIF_ROTATES` | Dynamic Orientation: Rotation changes per-slice; evaluated via `interp` stream. If cleared, rotation is fixed static keyframe. |
| **Bit 5** | `0x20` | `SIF_ANIMATES`| Animation Input: Carries a per-slice `animate: u16` value. Its mapping to `OP_ANIMATE` resource selection is unresolved. |
| **Bit 6..7** | `0xC0`| *Reserved* | Unassigned bits (must be zero). |

### 3.3 Master Opcode Dispatch Table (`# [FMT-FLM-OPCODES]`)

| Opcode Range | Category | Mnemonic | Payload Data Structure | Engine State Transition | Evidentiary Tier |
| :---: | :---: | :--- | :--- | :--- | :---: |
| `0x00`–`0x3F` | Object | `create` | `type_flags: u8`<br>If `SIF_DRAW`: `shape_id: u16`<br>If `!SIF_MOVES`: `x: i32, y: i32, z: i32` ($16.16$ fixed-point)<br>If `!SIF_ROTATES`: `rz: u16, rx: u16, ry: u16` (BAM angles) | Allocates object slot `c & 0x3F`. If `!SIF_DRAW`, designates an invisible tracking camera rig. | `[Established]` |
| `0x40`–`0x7F` | Object | `interp` | If `SIF_MOVES`: `x: i32, y: i32, z: i32` ($16.16$, 12 bytes)<br>If `SIF_ROTATES`: `rx: u16, ry: u16, rz: u16` (BAM, 6 bytes)<br>If `SIF_ANIMATES`: `animate: u16` (2 bytes) | Updates kinematic channel for slot `c & 0x3F` for the current tick. | `[Established]` |
| `0x80`–`0x8F` | Control | `var_set` | `value: u16` (little-endian) | Writes variable `nextvar[c & 0x0F] = value`. Controls Director event triggers and choreography logic. | `[Established]` |
| `0x90`–`0x97` | Camera | `view_obj` | None (slot embedded in opcode) | Selects active camera viewpoint: `view_obj = c & 0x0F` ($0..7$). **Triggers instantaneous camera cut** (`cut_from_previous = true` per Invariant `[I4]`). | `[Established]` |
| `0x98` | UI | `credits_clear`| None | Clears active on-screen credit/title overlay text. | `[Established]` |
| `0x99` | UI | `credits_set` | `line1: cstr`, `line2: cstr` (null-terminated ASCII) | Renders two-line credit banner overlay on screen. | `[Established]` |
| `0x9B` | Object | `max_obj` | `max_obj: u8` | Sets maximum active object slot index to scan for rendering/updates. | `[Established]` |
| `0x9C` | Audio | `sound` | `arg1: u8` (volume/pan), `arg2: u16` (sample resource ID) | Dispatches sound trigger cue. `arg2` in `0xC000`–`0xCFFF` maps to sound asset in `.ALL`. | `[Established]` |
| `0xA0`–`0xBF` | Control | `before` | `before_value: u16` | Records previous value of `nextvar[c & 0x1F]`. Used during backward scrubbing in film editor. | `[Established]` |
| `0xFF` | Control | `slice_end` | None | Terminates current time slice and advances timeline state. | `[Established]` |

---

## 4. Architectural Invariants & Coordinate Mapping

### 4.1 Coordinate Space Normalization (`[I1]`)

- **Spatial Positions ($16.16$ Fixed-Point):**
  Original positions are signed 32-bit integers in $16.16$ fixed-point format:
  $$\mathbf{P}_{\text{raw}} = [x_{\text{raw}}, y_{\text{raw}}, z_{\text{raw}}]$$
  Converted to metric right-handed basis ($+X$ Right, $+Y$ Up, $+Z$ Backward toward viewer, $-Z$ Forward):
  $$x_{\text{meters}} = \frac{x_{\text{raw}}}{65536.0}, \quad y_{\text{meters}} = \frac{y_{\text{raw}}}{65536.0}, \quad z_{\text{meters}} = \frac{z_{\text{raw}}}{65536.0}$$
- **Binary Angular Measurement (BAM):**
  Rotation angles are unsigned 16-bit integers ($0..65535$):
  $$\theta_{\text{rad}} = \left(\frac{\text{raw\_u16}}{65536.0}\right) \times 2\pi, \quad \theta_{\text{deg}} = \left(\frac{\text{raw\_u16}}{65536.0}\right) \times 360.0$$
- **Rotation Endianness Difference:**
  - In `create` (`0x00..0x3F`), static rotations are streamed in **`rz, rx, ry`** order.
  - In `interp` (`0x40..0x7F`), dynamic rotations are streamed in **`rx, ry, rz`** order.
  - Parsers must respect this field order difference to avoid pitch/roll axis inversion.
- **Unit Quaternions:**
  Euler rotations $(r_x, r_y, r_z)$ evaluate in yaw-pitch-roll order into normalized unit quaternions $\mathbf{q} = [q_x, q_y, q_z, q_w]$ satisfying:
  $$\left|\|\mathbf{q}\| - 1.0\right| < 10^{-4}$$
  Affine model-to-world transform matrices are emitted column-major without shear tearing.

### 4.2 Camera Channel Architecture & Director Cuts (`[I4]`)

- **Camera Slot Allocation:** Slots 0 through 7 ($8$ slots) are reserved for recording-capable camera rigs and tracked vehicles.
- **Invisible Camera Rigs:** Pure camera rigs are characterized by `type_flags` having `SIF_EXISTS`, `SIF_MOVES`, `SIF_ROTATES`, but **`SIF_DRAW == 0`**. These slots represent virtual cameras (Pan, Tilt, Crane, Tracking, Dolly) placed in the world.
- **Instantaneous Director Cuts:**
  When `view_obj` switches or when camera displacement between consecutive ticks exceeds the continuity threshold ($\|\mathbf{P}_{t+1} - \mathbf{P}_t\| > 50.0\text{ m}$):
  $$\text{cut\_from\_previous} = \text{true}$$
  Sub-tick interpolation is suppressed ($\alpha_{\text{eff}} = 0.0$), holding position and rotation at tick $t$ until tick $t+1$ arrives, preventing unnatural camera swooping across the terrain.

### 4.3 Audio Cue Event Dispatch

Opcode `0x9C` emits an `AudioCue`:
- `tick`: Cumulative 50 Hz authored tick (never a slice ordinal).
- `sample_name`: Resolved from resource ID `arg2` in `0xC000`–`0xCFFF` (e.g., `0xC52C` $\to$ `"SND_C52C.VOC"`).
- `volume`: Derived from `(arg1 & 0x7F) / 127.0`.
- `pan`: Stereo position derived from bit 7 or channel nibble ($[-1.0, 1.0]$).

---

## 5. Open Questions & Reverse Engineering Backlog

The following backlog documents open questions and investigations regarding `.FLM` choreography streams:

| ID | Topic / Investigation Area | Current Evidence & Finding | Evidentiary Tier | Recommended Handling in Engine |
| :--- | :--- | :--- | :---: | :--- |
| **Q-FLM-01** | Opcode Class `0xF0` | Observed exclusively in corrupted tail of `CORSAIR.FLM`. Unclear whether this represents a valid extended opcode or EOF garbage. | `[Bounded Observation]` | Terminate parsing cleanly when `0xF0` is encountered at slice boundary. |
| **Q-FLM-02** | `arg1` Audio Bitmask Semantics | Values cluster around 12, 143, 128. High bit `0x80` appears to govern looped vs one-shot playback, with remaining bits controlling attenuation/stereo pan. | `[Supported Inference]` | Extract volume and pan; treat bit `0x80` as loop flag. |
| **Q-FLM-03** | `before` Opcode Delta Table | Confirmed across 7,933 occurrences to mirror prior variable states for reverse playback in the Editing Room. | `[Established]` | Ignored during forward playback; essential for backward scrubbing. |
| **Q-FLM-04** | Interpolation on Non-Existent Slots | Observed in `CORSAIR.FLM` (slot #56 updated before `create`). | `[Bounded Observation]` | Engine ignores update or creates stub slot without throwing fatal error. |
| **Q-FLM-05** | Slerp Antipodal Quaternions | When $\mathbf{q}_t \cdot \mathbf{q}_{t+1} < 0.0$, slerp traverses the long path on $S^3$. | `[Established]` | Negate target quaternion prior to spherical interpolation. |
| **Q-FLM-06** | Real-Mode Dynamic Buffer Allocation for Variable Slice Rates | In low-memory real-mode conditions, `PLAYONE.EXE` may have dynamically throttled slice ingestion buffers when `tick_duration` dropped to 1 tick. | `[Hypothesis]` | Modern stream parser processes variable slice durations with zero buffer reallocation. |
| **Q-FLM-07** | Kaitai encodability | `interp` widths depend on slot flags mutated by `create`, with 2,278,626 intra-slice dependencies and 109,185 slot flag changes across the 561 walkable films; the state cannot cross a Kaitai `repeat`. | `[Established]` | [`flm_slice.ksy`](flm_slice.ksy) plus `stunt_reel.flm_walk` masks; seven films outside the grammar are pinned as corpus anomalies. |

---

## 6. Attribution & Provenance

The reverse engineering of the `.FLM` format represents the culmination of deep community analysis:

### 6.1 Community Researchers & Tool Authors

- **Doug Armknecht**: Primary researcher of the `.FLM` binary stream. Authored `flm_extract.py`, `flm_compare.py`, `flm_corpus_analyze.py`, and `flm_trace_flags.py` in `corpus/si_archive/Developer/SI_FLM_Format/`. Decoded the 3-byte slice header and solved the reverse-scrubbing back-pointer across all 15,544 corpus slices.
- **FreeFlight Development Team**: Authors of `sifilm.h` and `sifilm.cpp` in `corpus/si_archive/Developer/FreeFlight/src/`, establishing initial opcode classifications (`create`, `interp`, `view_obj`, `sound`).
- **Dave Palmowski & Dean Newbury**: Authors of technical documentation on the Stunt Island Editing Room timeline mechanics, subobject animations, and actor slot constraints in `corpus/si_archive/SITools/Docs/`.
- **Adrian Stephens**: Original Assembly Line Developer; architected the choreography engine, fixed-point kinematics, and BAM angle system.
- **Chris Phillips**: Decoded `.SOD` subobject bindings driven by `.FLM` joint angles.
- **Neil Halelamien**: Author of `.SET` scenery format research (2004); documented world object coordinates, prop placements, and scene initialization referenced by `.FLM` choreography streams in `Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **Ángel Eduardo**: Documented actor slot allocation in Stunt Island Set Designer.
- **Alberto Marnetto**: Explored high-framerate `.FLM` trajectory interpolation in `SI-8x`.

### 6.2 Primary Reference Paths in `corpus/si_archive/`

- `Developer/SI_FLM_Format/FLM_NOTES.md` (Doug Armknecht's format specification)
- `Developer/SI_FLM_Format/CORPUS_FINDINGS.md` (Statistical analysis across 50 corpus films)
- `Developer/SI_FLM_Format/Source/flm_extract.py` (Python extraction script)
- `Developer/FreeFlight/src/sifilm.cpp` (C++ choreography player)
- `Developer/FreeFlight/src/sifilm.h` (C++ opcode and struct definitions)

---

## 7. Codebase Seam Contracts & Fixtures

### 7.1 Seam 2: `TrajectoryRecord` Contract

The `.FLM` choreography evaluator implements `Seam 2: TrajectoryRecord` defined in `crates/stunt-core/src/contracts/trajectory.rs`:

```rust
// contracts/trajectory.rs
pub struct CameraTransform {
    pub eye: [f32; 3],
    pub target: [f32; 3],
    pub fov_degrees: f32,
    pub roll_radians: f32,
    pub cut_from_previous: bool,
}

pub struct ActorTransform {
    pub actor_id: u32,
    pub model_name: String,
    pub world_matrix: [f32; 16],
    pub rotation_quat: [f32; 4],
    pub position_meters: [f32; 3],
    pub state_mask: u16,
    pub joint_angles_bam: Vec<(u16, u16)>,
}

pub struct AudioCue {
    pub tick: u32,
    pub sample_name: String,
    pub volume: f32,
    pub pan: f32,
}

pub struct TrajectoryRecord {
    pub tick: u32,
    pub camera: CameraTransform,
    pub actors: Vec<ActorTransform>,
    pub audio_cues: Vec<AudioCue>,
}
```

### 7.2 Native Rust Implementation & PythonTAC

- **Rust Evaluation Pipeline**: `crates/stunt-core/src/flm/`. `FilmTimeline` (`timeline.rs`) is the single public sampling interface (`from_bytes`, `sample(tick)`, `sample_at_seconds`, `cues_between`, `total_ticks`, `duration_seconds`, `slices()`, `truncated_to_ticks`, `warnings`, `stop_reason`); `FlmPlayer` and the interpolation helpers are crate-private.
- **Partial Films**: a slice decode error does not discard the film. Decoded slices are kept and `stop_reason()` reports why decoding stopped (the Partial SOD convention); only an invalid header is an error.
- **Python TAC Capture Streamer**: `python/stunt_reel/tac/streamer.py`
- **Memory Map Anchor**: `# [MEM-FLM-TICK]`, `# [MEM-CAMERA-RIG]`, `# [MEM-ACTOR-TABLE]` in `docs/MEMORY_MAP.md`

### 7.3 Cleanroom Synthetic Fixture: `synthetic_minimal.flm`

Located at `tests/fixtures/synthetic_minimal.flm` (17 bytes total):
- **Magic**: `b"FILM"` (`0x46, 0x49, 0x4C, 0x4D`)
- **Slice 0** (9 bytes, header at 0x0004): `prev_slice_len` `0x0000`, `tick_duration` `0x01`, bytecode `0x80, 0x90, 0x98` (`var_set 0 = 0x9890`), `0x90` (`view_obj 0`), `0x98` (`credits_clear`), `0xFF` (`slice_end`)
- **Slice 1** (4 bytes, header at 0x000D): `prev_slice_len` `0x0009` (9-byte back-pointer to slice 0), `tick_duration` `0x01`, bytecode `0xFF`

Both slices parse under [`flm_slice.ksy`](flm_slice.ksy) with the masks from [`python/stunt_reel/flm_walk.py`](../../python/stunt_reel/flm_walk.py); `verify_formats_docs.py` executes that pair on every run, so the schema is exercised without the corpus.

### 7.4 Golden Oracle Trajectory: `oracle_intro_trajectory.json`

Located at `tests/fixtures/oracle_intro_trajectory.json`:
- Full 600-tick golden trajectory stream validated against `TrajectoryRecord`; ticks are cumulative 50 Hz ticks sampled from `FilmTimeline`.
- Zero matrix tearing and zero quaternion normalization error ($|\|\mathbf{q}\| - 1.0| < 10^{-4}$).
- Positional parity threshold $\text{RMSE}_{\text{pos}} \le 0.01\text{ m}$.

### 7.5 Verification Test Suite

- `crates/stunt-core/tests/flm_test.rs`: 16 integration tests verifying camera cut detection, focal-to-FOV conversions, unit quaternion invariants, slerp antipodal paths, and synthetic fixture evaluation.
- `tests/test_harness.py`: Python TAC offline replay harness tests.
