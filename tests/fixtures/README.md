# Synthetic Test Fixtures (`tests/fixtures/`)

This directory contains committed, cleanroom-synthesized minimal fixtures used by Rust and Python test suites. Because proprietary game data (`corpus/` and `target_bin/`) cannot be checked into the repository or downloaded in continuous integration environments, these mock fixtures ensure 100% offline, deterministic CI testing.

---

## Fixture Inventory

### 1. `synthetic_minimal.res` (72 bytes)
A synthetically constructed resource container conforming to `[fmt res]` and the binary offset layout discovered in `RIPRES.C`:
- **Header**: `RS` magic signature (2 bytes: `0x52, 0x53`) followed by `res_index` (`0x01`) and `item_count` (`0x03`); `item_count` equals `ofs_data / 4 - 2`.
- **Offset Table**:
  - `ofs[0] = 20` (`0x14`): Offset to the name table.
  - `ofs[1] = 40` (`0x28`): Offset to `PLANE.SOD` payload (16 bytes).
  - `ofs[2] = 56` (`0x38`): Offset to `PROP.SOD` payload (16 bytes).
  - `ofs[3] = 72` (`0x48`): Offset marking end-of-file.
- **Name Table**: Null-separated ASCII string list (`"PLANE.SOD\0PROP.SOD\0\0"`).
- **Payloads**: Deterministic test bytes verifying container offsets and payload slicing.

### 2. `synthetic_minimal.flm` (17 bytes)
A minimal film stream conforming to `[fmt flm]`:
- **Header**: ASCII `FILM` magic signature (4 bytes).
- **Slice 0** (header at 0x0004): `prev_slice_len` `0x0000`, `tick_duration` `0x01`, opcodes `0x80` (`var_set 0 = 0x9890`), `0x90` (`view_obj 0`), `0x98` (`clear_credits`), `0xFF` (`end_slice`).
- **Slice 1** (header at 0x000D): `prev_slice_len` `0x0009`, `tick_duration` `0x01`, opcode `0xFF` (`end_slice`).

### 3. `oracle_intro_trajectory.json`
Golden oracle trajectory snapshot conforming to `Seam 2: TrajectoryRecord` (`crates/stunt-core/src/contracts.rs`):
- Contains a sequence of discrete simulation ticks (ticks 0 and 1).
- Evaluates `CameraTransform` (`eye`, `target`, `fov_degrees`, `roll_radians`).
- Evaluates `ActorTransform` (`actor_id`, `model_name`, `world_matrix`, `rotation_quat`, `position_meters`, `state_mask`).
- Evaluates `AudioCue` events (`tick`, `sample_name`, `volume`, `pan`).
- Used to test serialization/deserialization and golden trajectory regression comparisons.

### 4. `synthetic_minimal.sod` (76 bytes)
A cleanroom-synthesized minimal `.sod` bytecode model conforming to `[fmt sod]`:
- **Header**: 10 bytes (`OP_ID = 0x000c`, `bounding_size = 100`, `yoff = 0`, `scale = 1` ($0.5\text{ m}$), `collision = 0`).
- **Opcodes**:
  - `OP_VECTORS` (`0x0075`): 5 vertices uploading base triangular wing and inner coplanar decal triangle.
  - `OP_COLOR` (`0x0129`) + `OP_POLYZ` (`0x00f3`): Base facet (palette index 40).
  - `OP_COLOR` (`0x0129`) + `OP_POLYZ` (`0x00f3`): Overlapping coplanar decal facet (palette index 15) testing Invariant `[I5]`.
  - `OP_RETURN` (`0x0195`): Clean bytecode termination.

### 5. `synthetic_minimal.all` (84 bytes)
A cleanroom-synthesized full-movie archive container conforming to `# [FMT-ALL-CHUNKS]` and `[fmt all]`:
- **Header**: 8 bytes (`num = 1`, `ids = [0x0001]`, `offsets = [0x00000008]`).
- **Payload**: Bundles `synthetic_minimal.sod` (76 bytes) as chunk `0x0001` (`MODEL_0001.SOD`).
- Used to verify end-to-end `.ALL` archive parsing, scene bundle assembly, and headless trajectory evaluation offline without requiring proprietary assets.

