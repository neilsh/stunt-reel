# Synthetic Test Fixtures (`tests/fixtures/`)

This directory contains committed, cleanroom-synthesized minimal fixtures used by Rust and Python test suites. Because proprietary game data (`corpus/` and `target_bin/`) cannot be checked into the repository or downloaded in continuous integration environments, these mock fixtures ensure 100% offline, deterministic CI testing.

---

## Fixture Inventory

### 1. `synthetic_minimal.res` (72 bytes)
A synthetically constructed resource container conforming to `[fmt res]` and the binary offset layout discovered in `RIPRES.C`:
- **Header**: `RS` magic signature (2 bytes: `0x52, 0x53`) followed by a 16-bit version word (`0x0001`).
- **Offset Table**:
  - `ofs[0] = 20` (`0x14`): Offset to the name table.
  - `ofs[1] = 40` (`0x28`): Offset to `PLANE.SOD` payload (16 bytes).
  - `ofs[2] = 56` (`0x38`): Offset to `PROP.SOD` payload (16 bytes).
  - `ofs[3] = 72` (`0x48`): Offset marking end-of-file.
- **Name Table**: Null-separated ASCII string list (`"PLANE.SOD\0PROP.SOD\0\0"`).
- **Payloads**: Deterministic test bytes verifying container offsets and payload slicing.

### 2. `synthetic_minimal.flm` (15 bytes)
A minimal film stream conforming to `[fmt flm]`:
- **Header**: ASCII `FILM` magic signature (4 bytes).
- **Slice 0**:
  - `inctime`: `0x01` (1 tick).
  - `declared_len`: `0x0004` (4 bytes).
  - Opcodes: `0x80` (`var_set 0`), `0x90` (`view_obj 0`), `0x98` (`clear_credits`), `0xFF` (`end_slice`).
- **Slice 1**:
  - `inctime`: `0x01` (1 tick).
  - `declared_len`: `0x0001` (1 byte).
  - Opcodes: `0xFF` (`end_slice`).

### 3. `oracle_intro_trajectory.json`
Golden oracle trajectory snapshot conforming to `Seam 2: TrajectoryRecord` (`crates/stunt-core/src/contracts.rs`):
- Contains a sequence of discrete simulation ticks (ticks 0 and 1).
- Evaluates `CameraTransform` (`eye`, `target`, `fov_degrees`, `roll_radians`).
- Evaluates `ActorTransform` (`actor_id`, `model_name`, `world_matrix`, `rotation_quat`, `position_meters`, `state_mask`).
- Evaluates `AudioCue` events (`tick`, `sample_name`, `volume`, `pan`).
- Used to test serialization/deserialization and golden trajectory regression comparisons.
