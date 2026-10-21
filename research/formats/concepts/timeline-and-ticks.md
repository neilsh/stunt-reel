# Stunt Island Technical Reference: Timeline Mechanics, Simulation Ticks & Kinematic Interpolation

**Document Identifier:** `research/formats/concepts/timeline-and-ticks.md`  
**Author:** `worker_fmt_concepts`  
**Governing Invariant:** `[I4]` (Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation), `[I1]` (Metric Right-Handed Coordinates)  
**Status:** Cleanroom Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

*Stunt Island*'s cinematic replay engine (`PLAYONE.EXE`, `MAKEONE.EXE`) executes deterministic choreography streams recorded in `.FLM` files. Unlike interactive game engines that integrate physics dynamically per frame with variable time deltas ($\Delta t$), Stunt Island films operate as discrete, pre-recorded animation timelines running at fixed simulation clock frequencies.

```
+-------------------------------------------------------------------------------+
| Discrete Simulation Clock (20 Hz / 30 Hz) [I4]                                |
| - Fixed step: delta_t = 50.0 ms (20 Hz) or 33.33 ms (30 Hz)                   |
| - Keyframe state: CameraTransform, ActorTransform[], AudioCue[]               |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼
+-------------------------------------------------------------------------------+
| Presentation Loop (Unlocked Framerate >= 60 FPS)                              |
| - Fractional sub-tick parameter: alpha = (t_render - t_cur) / delta_t in [0..1)|
| - Continuity evaluation: cut_from_previous flag or ||P_{t+1} - P_t|| > 50 m   |
+-------------------------------------------------------------------------------+
                  │                                           │
       (Continuous Motion)                            (Director Cut)
                  ▼                                           ▼
+-----------------------------------+       +-----------------------------------+
| Sub-Tick Kinematic Interpolation  |       | Instantaneous Cut Suppression     |
| - Position: Linear Lerp           |       | - alpha_eff = 0.0                 |
| - Orientation: Spherical Slerp    |       | - Hold frame until t+1 arrives    |
| - Antipodal quaternion handling   |       | - Zero camera swooping            |
+-----------------------------------+       +-----------------------------------+
```

### 1.1 Hardware Timer Principles in MS-DOS
In 1992 IBM PC-compatibles, fixed simulation timing was governed by the Intel 8253/8254 Programmable Interval Timer (PIT) driving hardware Interrupt Request 0 (`IRQ0` / `INT 08h`):
- **Base Oscillator Frequency:** $1.193182\text{ MHz}$ ($1{,}193{,}182\text{ ticks/second}$).
- **Standard DOS Tick:** Pit divisor `0x0000` (65,536) yields the default $\approx 18.2065\text{ Hz}$ timer tick.
- **Stunt Island Reprogrammed Divisors:**
  - **$20\text{ Hz}$ Mode ($\Delta t = 50.0\text{ ms}$):** Divisor $1193182 / 20 = 59659$ (`0xE90B`).
  - **$30\text{ Hz}$ Mode ($\Delta t = 33.33\text{ ms}$):** Divisor $1193182 / 30 = 39773$ (`0x9B5D`).
- **Display Retrace Decoupling:** The VGA cathode-ray tube raster beam refreshed at $70\text{ Hz}$ (vertical retrace every $14.28\text{ ms}$, monitored on I/O port `0x03DA`). Because $70\text{ Hz}$ is not an integer multiple of $20\text{ Hz}$ or $30\text{ Hz}$, the engine updated simulation state inside the PIT timer interrupt while the rendering loop polled port `0x03DA` for vertical blanking (`[MEM-VSYNC-03DA]`).

---

## 2. Memory Layout & Bitfield Representations

### 2.1 The 3-Byte Time Slice Header (`.FLM`)

Each discrete time slice in a `.FLM` choreography stream begins with a compact 3-byte header:

```
Byte:    +0x00                 +0x01                 +0x02
Field:  [ prev_slice_len_lo ] [ prev_slice_len_hi ] [ tick_duration ]
Type:    u8                    u8                    u8
        <-------- prev_slice_len (u16 LE) --------->
```

#### Field Semantics
1. **`prev_slice_len` (`u16`, Little-Endian):** The exact physical byte distance from the start of the previous slice to the start of the current slice.
   - For Slice 0: `prev_slice_len == 0x0000`.
   - For Slice $i \ge 1$: `prev_slice_len == &slice[i] - &slice[i-1]`.
   - **Editing Room Back-Pointer:** Enables the Stunt Island VCR editor to execute instantaneous reverse stepping (`REVERSE STEP`) without maintaining random-access index tables in conventional memory.
2. **`tick_duration` (`u8`):** The number of simulation ticks that elapse during this slice. A value of $10$ indicates $10$ ticks (e.g. $10 \times 50\text{ ms} = 0.5\text{ s}$ at $20\text{ Hz}$).

### 2.2 Object Lifecycle Bitfield (`type_flags: u8`)

Encountered in Object Lifecycle opcodes (`0x00`–`0x3F`):

```
Bit:   7     6     5          4          3          2          1          0
      [  Reserved ] [ANIMATES] [ROTATES ] [ MOVES  ] [ SHADOW ] [  DRAW  ] [ EXISTS ]
```

| Bit | Mask | Flag Name | Description | Engine Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Bit 0** | `0x01` | `SIF_EXISTS` | Active Slot | Slot is allocated in the scene. If cleared, actor is destroyed/culled. |
| **Bit 1** | `0x02` | `SIF_DRAW` | 3D Renderable Mesh | Binds a 3D `.SOD` mesh (`shape_id: u16`). If cleared, designates an **invisible tracking camera rig**! |
| **Bit 2** | `0x04` | `SIF_SHADOW` | Casts Shadow | Projects a flat-shaded ground shadow polygon beneath the actor. |
| **Bit 3** | `0x08` | `SIF_MOVES` | Dynamic Translation | Position updates per slice via `interp` stream. If cleared, position is a static keyframe. |
| **Bit 4** | `0x10` | `SIF_ROTATES` | Dynamic Orientation | Rotation updates per slice via `interp` stream. If cleared, rotation is a static keyframe. |
| **Bit 5** | `0x20` | `SIF_ANIMATES` | Animation Input | Carries a per-slice `animate: u16` value. Its mapping to `.SOD` resource selection is unresolved; it is not established as a BAM joint angle. |
| **Bits 6..7**| `0xC0` | `RESERVED` | Unassigned | Reserved bits (must be zero). |

### 2.3 Opcode Classification Architecture

Opcode bytes are partitioned into four functional classes by their upper two bits (`opcode >> 6`):

```
+---------------+---------------------+---------------------------------------------------------+
| Opcode Range  | Class Name          | Functional Scope                                        |
+---------------+---------------------+---------------------------------------------------------+
| `0x00`–`0x3F` | Object Lifecycle    | Allocates slots 0..63 (`create`, `shape_id`, flags)    |
| `0x40`–`0x7F` | Channel Updates    | Dynamic translation, BAM rotation, raw animation input (`interp`) |
| `0x80`–`0xBF` | Event & Control     | Variable sets (`var_set`), camera switches (`view_obj`), audio (`sound`) |
| `0xC0`–`0xFF` | Extended / Control  | Extended events, slice terminator (`0xFF`)              |
+---------------+---------------------+---------------------------------------------------------+
```

---

## 3. Data Structures, Tables & Conversion Algorithms

### 3.1 Sub-Tick Kinematic Interpolation Algorithm (`[I4]`)

To render smooth 60+ FPS motion without stepping or jitter, the presentation engine computes continuous actor and camera transforms between discrete simulation ticks $t$ and $t+1$.

Given continuous wall-clock presentation time $T_{\text{render}}$:
$$\alpha = \frac{T_{\text{render}} - T_t}{T_{t+1} - T_t} \in [0.0, 1.0)$$

#### 1. Position Linear Interpolation (Lerp)
$$\mathbf{P}_{\text{render}}(\alpha) = (1.0 - \alpha)\mathbf{P}_t + \alpha \mathbf{P}_{t+1}$$

#### 2. Spherical Linear Rotation Interpolation (Slerp)
Unit quaternions $\mathbf{q}_t$ and $\mathbf{q}_{t+1}$ are interpolated across the 4D hypersphere $S^3$:

$$\mathbf{q}_{\text{render}}(\alpha) = \text{slerp}(\mathbf{q}_t, \mathbf{q}_{t+1}, \alpha) = \frac{\sin((1 - \alpha)\Omega)}{\sin\Omega}\mathbf{q}_t + \frac{\sin(\alpha\Omega)}{\sin\Omega}\mathbf{q}_{t+1}$$
where $\cos\Omega = \mathbf{q}_t \cdot \mathbf{q}_{t+1}$.

#### Antipodal Quaternion Handling
Because quaternions represent rotations double-covered ($\mathbf{q} \equiv -\mathbf{q}$), if $\mathbf{q}_t \cdot \mathbf{q}_{t+1} < 0.0$, the target quaternion must be negated prior to slerping:
$$\mathbf{q}'_{t+1} = -\mathbf{q}_{t+1}$$
This guarantees interpolation takes the shortest geodesic path on $S^3$, preventing unnatural $360^\circ$ spins across tick boundaries.

### 3.2 Director Cut Suppression

In cinematic replays, instantaneous cuts between cameras must never be smoothly interpolated; doing so would produce a disorienting swoop across the island terrain.

#### Cut Trigger Conditions
The camera cut flag `cut_from_previous` is set to `true` at tick $t+1$ if ANY of the following occur:
1. **Camera Switch Opcode (`view_obj` `0x90`–`0x97`):** The film script switches active viewpoints.
2. **Explicit Director Cut:** Set in the timeline metadata.
3. **Spatial Continuity Threshold Exceeded:** The distance between consecutive camera positions exceeds the maximum continuous flight displacement:
   $$\left\| \mathbf{P}_{t+1} - \mathbf{P}_t \right\|_2 > 50.0\text{ meters}$$

#### Suppression Enforcement
When `cut_from_previous == true`:
$$\alpha_{\text{eff}} = 0.0$$
The presentation engine holds the camera transform at $\mathbf{P}_t, \mathbf{q}_t$ for the entire duration of interval $[T_t, T_{t+1})$, cutting instantaneously to $\mathbf{P}_{t+1}, \mathbf{q}_{t+1}$ only when tick $t+1$ arrives.

### 3.3 Audio Cue Event Synchronization

Audio cue events (`AudioCue`) are dispatched synchronously with simulation ticks:

```rust
pub struct AudioCue {
    pub tick: u32,             // Authored tick timestamp
    pub sample_name: String,   // E.g. "SND_C52C.VOC"
    pub volume: f32,           // Factor in [0.0, 1.0]
    pub pan: f32,              // Stereo pan in [-1.0, 1.0]
}
```

#### Opcode `0x9C` Bytecode Decoding
Opcode `0x9C` payload consists of 3 bytes: `[arg1: u8, arg2_lo: u8, arg2_hi: u8]`:
1. **Sample Resource ID:** `resource_id = arg2_lo | (arg2_hi << 8)`.
   - Falls in range `0xC000`–`0xCFFF`.
   - Resolves to audio asset in `.ALL` (e.g. `0xC52C` $\implies$ `"SND_C52C.VOC"`).
2. **Volume Factor:** `volume = (arg1 & 0x7F) / 127.0`.
3. **Stereo Panning:** Derived from MSB or channel nibbles:
   $$\text{pan} = \begin{cases} +1.0 & \text{if } (\text{arg1} \ \& \ 0x80) \ne 0 \text{ (Right)} \\ -1.0 & \text{otherwise (Left)} \end{cases}$$

---

## 4. Architectural Invariants & Coordinate Mapping

| Invariant | System Rule | Concrete Implementation |
| :--- | :--- | :--- |
| **`[I4]`** | Discrete Simulation Ticks | Ticks evaluate at fixed $20\text{ Hz}$ / $30\text{ Hz}$ clock. Unlocked rendering uses sub-tick $\alpha$. |
| **`[I4]`** | Instantaneous Cut Suppression | $\alpha_{\text{eff}} = 0.0$ when `cut_from_previous == true` or $\|\Delta\mathbf{P}\| > 50.0\text{ m}$. |
| **`[I1]`** | Metric Coordinates & Unit Quaternions | Trajectory positions in meters; rotations converted to normalized unit quaternions ($\pm 10^{-4}$). |
| **`[I7]`** | Cleanroom Asset Isolation | All choreography evaluation tests run 100% offline using `oracle_intro_trajectory.json`. |

---

## 5. Open Questions & Reverse Engineering Backlog

1. **`[BK-TIME-01]` Opcode Class `0xF0` in Film File Tails** (`[Bounded Observation]`): Observed in corrupted trailing bytes of `CORSAIR.FLM`. Unclear whether this represents an unmapped extended opcode or an uninitialized write buffer artifact.
2. **`[BK-TIME-02]` Variable Table Register Depth** (`[Supported Inference]`): Slices update `nextvar[0..15]` registers via opcodes `0x80`–`0x8F`. Whether more than 16 registers exist in `PLAYONE.EXE`'s runtime state table remains under investigation.
3. **`[BK-TIME-03]` Propeller Subobject Blur Transition Threshold** (`[Established]`): Confirmed from Adrian Stephens' 1997 notes that parameter `9` controls propeller angular velocity, triggering visual substitution of 3D blades with a semi-transparent disc when speed exceeds threshold.
4. **`[BK-TIME-04]` Variable Frame Rate Throttle Under Heavy Polygon Loads** (`[Hypothesis]`): Hypothesis that original real-mode `PLAYONE.EXE` dropped internal tick evaluation below $20\text{ Hz}$ when scene rendering exceeded a threshold count of 8254 PIT timer ticks.

---

## 6. Attribution & Provenance

- **Doug Armknecht (2002):** Reverse engineering of `.FLM` timeline structure, opcode classifications, and extraction scripts in `corpus/si_archive/Developer/SI_FLM_Format/` (`FLM_FORMAT_DOUG_NOTES.txt`, `FLM_NOTES.md`, `flm_extract.py`).
- **FreeFlight Development Team:** Reverse engineering of `.FLM` playback state machines in `corpus/si_archive/Developer/FreeFlight/src/sifilm.cpp` and `sifilm.h`.
- **Adrian Stephens (1997):** Analysis of subobject animation timing, propeller rotation parameters, and landing gear state transitions (`corpus/si_archive/SITools/Docs/Adrian_Subobjects.txt`).
- **Neil Halelamien (2004):** Reverse engineering of stage event trigger timing, prop script clocks, and tick counters in `corpus/si_archive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **Dave Palmowski & Dean Newbury:** Documentation of timeline mechanics, subobject hierarchies, and flight playback tools in `corpus/si_archive/SITools/Docs/`.
- **StuntReel Teamwork Team (2026):** Discovery of the 3-byte slice header back-pointer resolution, director cut suppression rules, and Seam 2 contracts (`spec_miner_fmt_flm_all/analysis.md`, `crates/stunt-core/src/contracts/trajectory.rs`).

---

## 7. Codebase Seam Contracts & Fixtures

### 7.1 Seam Contracts
- **`crates/stunt-core/src/contracts/mod.rs`**: Invariant `[I4]` declaration (Discrete simulation ticks with sub-tick interpolation).
- **`crates/stunt-core/src/contracts/trajectory.rs`**:
  - `CameraTransform`: `cut_from_previous: bool` gating sub-tick lerp.
  - `ActorTransform`: Evaluated 6-DOF entity state at tick $t$.
  - `AudioCue`: Discrete sound trigger event.
  - `TrajectoryRecord`: Simulation snapshot at tick $t$.
  - `FilmCapture`: Full multi-tick film container.

### 7.2 Cleanroom Synthetic Fixtures
- **`tests/fixtures/synthetic_minimal.flm`**: 15-byte minimal film fixture demonstrating slice headers, `var_set` (`0x80`), `view_obj` (`0x90`), and `slice_end` (`0xFF`).
- **`tests/fixtures/oracle_intro_trajectory.json`**: Golden oracle recording 600 continuous ticks validating zero matrix tearing and quaternion normalization.
