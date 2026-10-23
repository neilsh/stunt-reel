# Stunt Island Technical Reference: Timeline Mechanics, Simulation Ticks & Kinematic Interpolation

**Document Identifier:** `research/formats/concepts/timeline-and-ticks.md`  
**Author:** `worker_fmt_concepts`  
**Governing Invariant:** `[I4]` (Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation), `[I1]` (Metric Right-Handed Coordinates)  
**Status:** Cleanroom Technical Reference Specification  

---

## 1. Overview & Mathematical / Hardware Principles

*Stunt Island*'s cinematic replay engine (`PLAYONE.EXE`, `MAKEONE.EXE`) executes deterministic choreography streams recorded in `.FLM` files. Unlike interactive game engines that integrate physics dynamically per frame with variable time deltas ($\Delta t$), Stunt Island films operate as discrete, pre-recorded animation timelines running at a fixed simulation clock frequency. **`PLAYONE.EXE` programs the 8254 PIT at 50 Hz for playback (`[Established]`); the earlier 20/30 Hz figures in this document were inferred from render-loop timing and are superseded by the disassembly evidence in § 1.1.**

```
+-------------------------------------------------------------------------------+
| Discrete Simulation Clock (50 Hz) [I4]                                        |
| - Fixed step: delta_t = 20.0 ms                                               |
| - Keyframe state: CameraTransform, ActorTransform[], AudioCue[]               |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼
+-------------------------------------------------------------------------------+
| Presentation Loop (Unlocked Framerate >= 60 FPS)                              |
| - Fractional sub-tick parameter: alpha = (t_render - t_slice) / (20 ms * tick_duration)|
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
- **Standard DOS Tick:** Pit divisor `0x0000` (65,536) yields the default $\approx 18.2065\text{ Hz}$ timer tick. `PLAYONE.EXE` restores this divisor on exit (`0x0EB6`, `0x0EC5`).
- **Stunt Island Playback Divisor:** The installed INT 8 handler is programmed with divisor `0x5D38` = $23{,}864$ (`0x5189`, `0x51CC` load `cx = 0x5D38` and jump to the PIT setter at `0x36F7`):
  $$\frac{1{,}193{,}182}{23{,}864} = 49.9992\text{ Hz} \approx 50\text{ Hz} \qquad \Delta t = 20.0\text{ ms}$$
  No `0xE90B` (20 Hz) or `0x9B5D` (30 Hz) divisor exists in the unpacked image. The earlier 20/30 Hz figures were inferred from the render loop's observed frame cadence, not from the programmed timer.
- **Interrupt Path and Film Clock:** the 50 Hz handler, the global tick `DGROUP:0x22B8`, and the active film clock `DGROUP:0x4896` are specified in [`MEMORY_MAP.md` `# [MEM-FLM-TICK]`](../../../docs/MEMORY_MAP.md#-mem-flm-tick); the disassembly and live-sampling evidence is in [`memory.md` § 3.2](../../playone-exe/memory.md#32-tick-counter-evidence).
- **Film Advancement (`[Supported Inference]`):** when the film clock passes the current slice's interval, the next slice's `tick_duration` byte is read and added to the start tick; elapsed ticks divided by `tick_duration` give the sub-tick interpolation factor. Addresses: [`memory.md` § 3.2](../../playone-exe/memory.md#32-tick-counter-evidence).
- **Display Retrace Decoupling:** The VGA cathode-ray tube raster beam refreshed at $70\text{ Hz}$ (vertical retrace every $14.28\text{ ms}$, monitored on I/O port `0x03DA`). Presentation and simulation are decoupled: the rendering loop polls `0x03DA` for vertical blanking, while simulation time advances in the 50 Hz PIT interrupt (`[MEM-VSYNC-03DA]`). When rendering cannot keep up, a frame advances several simulation ticks at once; this is why capture timing alone overestimates the tick interval.

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization), [`[I4]`](../../../docs/SPEC.md#i4-discrete-simulation-ticks--cut-aware-sub-tick-interpolation), [`[I7]`](../../../docs/SPEC.md#i7-cleanroom-asset-isolation--small-pure-rust-core-dependencies). **Contract and code:** [`contracts/`](../../../crates/stunt-core/src/contracts/mod.rs). Fixtures: [`tests/fixtures/README.md`](../../../tests/fixtures/README.md).

---

## 2. Memory Layout & Bitfield Representations

The `.FLM` byte-level structures are specified once, in [`flm.md`](../flm.md) and [`flm_slice.ksy`](../flm_slice.ksy); this concept document covers only how their fields drive playback timing (§ 3). It does not re-tabulate them:

* **3-byte slice header** (`prev_slice_len: u16`, `tick_duration: u8`): [`flm.md` § 2.1](../flm.md#21-the-solved-3-byte-slice-header-reverse-engineering-breakthrough). `tick_duration` counts 50 Hz ticks since the previous slice, so slice $i$'s timestamp is the cumulative sum $\sum_{k \le i} \text{tick\_duration}_k$ (slice 0 at tick 0). Its semantics and corpus distribution: [`flm.md` § 2.1.1](../flm.md#211-tick_duration-semantics--corpus-distribution).
* **Object `type_flags` bitfield** (`SIF_*`): [`flm.md` § 3.2](../flm.md#32-object-type-flags-type_flags-u8).
* **Opcode classes and dispatch** (`opcode >> 6`): [`flm.md` § 3.3](../flm.md#33-master-opcode-dispatch-table--fmt-flm-opcodes).

---

## 3. Data Structures, Tables & Conversion Algorithms

### 3.1 Sub-Tick Kinematic Interpolation Algorithm (`[I4]`)

To render smooth 60+ FPS motion without stepping or jitter, the presentation engine computes continuous actor and camera transforms between discrete simulation ticks $t$ and $t+1$.

Given continuous wall-clock presentation time $T_{\text{render}}$:
$$\alpha = \frac{T_{\text{render}} - T_{\text{slice}}}{20\text{ ms} \times \text{tick\_duration}} \in [0.0, 1.0)$$

`tick_duration` varies per slice, so the interval $T_{t+1} - T_t$ is not a constant; it is the slice's authored duration in 50 Hz ticks. A zero-duration slice has no interval to interpolate and must be applied at the same timestamp as its successor.

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

#### Sampling Interface & Record Tick Semantics
`FilmTimeline` (`crates/stunt-core/src/flm/timeline.rs`) is the single public interface for turning a `.FLM` film into `TrajectoryRecord`s: `from_bytes`, `sample(tick)`, `sample_at_seconds`, `cues_between`, `total_ticks`, `duration_seconds`, `slices()`, `truncated_to_ticks`, `warnings`, and `stop_reason`. It places slice $i$ at the cumulative tick $\sum_{k \le i}\text{tick\_duration}_k$ and applies the lerp/slerp and cut suppression described here. The earlier ordinal-based path (`FlmPlayer::step_tick`, `evaluate_all`, `evaluate_film`, `evaluate_sub_tick`) is removed, and `FlmPlayer` and the interpolation helpers are crate-private.

`TrajectoryRecord.tick` (and `AudioCue.tick`) is always the cumulative 50 Hz authored tick, never a slice ordinal; a slice's ordinal is only its index in the timeline. Zero-duration slices share a tick with their predecessor, so ordinals and ticks diverge for real films.

#### Partial Films
A slice that fails to decode does not discard the film. The slices decoded before the failure are kept, and `stop_reason()` reports why decoding stopped, mirroring the Partial SOD convention (`GLOSSARY.md`). Only an invalid header is an error. Sampling operates over the decoded slices only.

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
    pub tick: u32,             // Cumulative 50 Hz authored tick (never a slice ordinal)
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

## 4. Open Questions & Reverse Engineering Backlog

1. **`[BK-TIME-01]` Opcode Class `0xF0` in Film File Tails** (`[Bounded Observation]`): Observed in corrupted trailing bytes of `CORSAIR.FLM`. Unclear whether this represents an unmapped extended opcode or an uninitialized write buffer artifact.
2. **`[BK-TIME-02]` Variable Table Register Depth** (`[Supported Inference]`): Slices update `nextvar[0..15]` registers via opcodes `0x80`–`0x8F`. Whether more than 16 registers exist in `PLAYONE.EXE`'s runtime state table remains under investigation.
3. **`[BK-TIME-03]` Propeller Subobject Blur Transition Threshold** (`[Established]`): Confirmed from Adrian Stephens' 1997 notes that parameter `9` controls propeller angular velocity, triggering visual substitution of 3D blades with a semi-transparent disc when speed exceeds threshold.
4. **`[BK-TIME-04]` Render Frame Drops Do Not Slow Simulation** (`[Supported Inference]`): The 50 Hz PIT interrupt continues to advance the tick counters while the VGA-synchronized render loop draws; a slow renderer therefore advances several simulation ticks between frames rather than reducing the tick rate. Direct measurement of ticks-per-rendered-frame under emulated load remains open.

---

## 5. Attribution & Provenance

- **Doug Armknecht (2002):** Reverse engineering of `.FLM` timeline structure, opcode classifications, and extraction scripts in `corpus/si_archive/Developer/SI_FLM_Format/` (`FLM_FORMAT_DOUG_NOTES.txt`, `FLM_NOTES.md`, `flm_extract.py`).
- **FreeFlight Development Team:** Reverse engineering of `.FLM` playback state machines in `corpus/si_archive/Developer/FreeFlight/src/sifilm.cpp` and `sifilm.h`.
- **Adrian Stephens (1997):** Analysis of subobject animation timing, propeller rotation parameters, and landing gear state transitions (`corpus/si_archive/SITools/Docs/Adrian_Subobjects.txt`).
- **Neil Halelamien (2004):** Reverse engineering of stage event trigger timing, prop script clocks, and tick counters in `corpus/si_archive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`.
- **Dave Palmowski & Dean Newbury:** Documentation of timeline mechanics, subobject hierarchies, and flight playback tools in `corpus/si_archive/SITools/Docs/`.
- **StuntReel Teamwork Team (2026):** Discovery of the 3-byte slice header back-pointer resolution, director cut suppression rules, and Seam 2 contracts (`spec_miner_fmt_flm_all/analysis.md`, `crates/stunt-core/src/contracts/trajectory.rs`).

---
