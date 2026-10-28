# Trajectory records carry authored facts, not derived values

## Status

proposed; implemented by C1 of the architecture-deepening programme. On sign-off the
status becomes accepted and the implementation lands in `neilsh/arch-01-trajectory`.

## Context

`ActorTransform` (Seam 2, [`crates/stunt-core/src/contracts/trajectory.rs`](../../crates/stunt-core/src/contracts/trajectory.rs))
stores `world_matrix` beside `position_meters` and `rotation_quat`, the pose that
determines it. Each producer — [`flm/mod.rs`](../../crates/stunt-core/src/flm/mod.rs),
[`flm/interpolate.rs`](../../crates/stunt-core/src/flm/interpolate.rs) and the Python
reference in [`python/stunt_reel/tac/streamer.py`](../../python/stunt_reel/tac/streamer.py) —
constructs the record with zeros and then assigns `compute_world_matrix()`; tests fill
the field by hand. [`FilmScene::frame`](../../crates/stunt-core/src/scene.rs) copies it
unchecked into `ActorDraw`. One missed assignment draws every actor at the origin, and
nothing downstream can notice: the field is a cache every caller must remember to fill.

The same record's `fov_degrees` carries two meanings. In a `TrajectoryRecord` it is the
authored field of view at the default lens; `FilmScene::frame` copies the camera,
replaces `fov_degrees` with `lens_fov_degrees(...)`, and places it in `SceneFrame`.
Because both are `CameraTransform::fov_degrees`, a consumer cannot tell an authored
camera from a view camera; if the rewrite in `frame` were deleted, `lens_fov_degrees`
would spread to the renderer, the glTF exporter and the CLI.

## Decision

`ActorTransform` carries authored facts only: `actor_id`, `model_name`, `shape_id`,
`position_meters`, `rotation_quat`, `state_mask`, `joint_angles_bam`.
`compute_world_matrix()` is the only way to obtain the model-to-world matrix; the stored
field is deleted. `FilmScene::frame` calls it once per draw when it builds
`ActorDraw.world_matrix`, which stays because the renderer and glTF need the resolved
matrix per frame.

`CameraTransform` is the authored camera: `fov_degrees` is the field of view at the
default lens, `lens` is the authored zoom word, and `cut_from_previous` is authored
timing. A new `ViewCamera` value in
[`crates/stunt-core/src/scene.rs`](../../crates/stunt-core/src/scene.rs) holds `eye`,
`target`, `fov_degrees` and `roll_radians`; `ViewCamera::from_authored(&record.camera)`
applies `lens_fov_degrees`. `SceneFrame` carries `view: ViewCamera` instead of
`camera: CameraTransform`, and `FilmScene::frame` is the only place that builds it. The
renderer, glTF exporter, CLI and parity writer read `frame.view`; the renderer's
`set_authored_transform` takes a `ViewCamera` and the record's authored camera never
reaches it.

The G04 oracle and the Python mirror move in the same change: the two-record
[`tests/fixtures/oracle_intro_trajectory.json`](../../tests/fixtures/oracle_intro_trajectory.json)
is re-serialized without `world_matrix`,
[`tests/fixtures/README.md`](../../tests/fixtures/README.md) stops listing it, and
[`python/stunt_reel/tac/models.py`](../../python/stunt_reel/tac/models.py) /
[`streamer.py`](../../python/stunt_reel/tac/streamer.py) drop the stored field while
keeping their `compute_world_matrix()`. Rust serde ignores the unknown field when
reading an older record, and the Python reader ignores a legacy `world_matrix` key; no
migration is needed.

## Considered Options

- **Keep the field and add an assertion.** Rejected: a debug assertion still lets a
  release build draw at the origin, and every producer and test must keep filling it.
- **Remove the field but keep `SceneFrame.camera` as a rewritten `CameraTransform`.**
  Rejected: the record and the frame would still share a type whose `fov_degrees` means
  authored in one place and zoomed in another, and a consumer can pass the wrong camera
  with no help from the compiler.
- **Rename `CameraTransform.fov_degrees` to `base_fov_degrees`.** Rejected: it changes
  the wire key for a distinction `ViewCamera` already makes, while the fixture's camera
  is already the authored value.
- **Cache the matrix behind a `OnceCell`.** Rejected: `stunt-core` stays simple and the
  derivation is a handful of multiplies; `ActorDraw` needs a plain `[f32; 16]` for the
  GPU buffer anyway.
- **Regenerate the oracle with `stream_oracle_intro`.** Rejected: that writes 600 ticks,
  while the fixture is a hand-curated two-tick snapshot that
  `python/scripts/verify_formats_docs.py` pins to two records. Re-serialize the two
  ticks instead.

## Consequences

- A half-built `ActorTransform` is unrepresentable; the only matrix is a function of
  the pose, so "forgot to fill it" disappears rather than becoming a rarer bug.
- `SceneFrame.view` names the zoomed camera; `frame.camera` is gone, so every frame
  consumer updates mechanically. `TrajectoryRecord.camera` stays authored.
- The G04 oracle comparison and `flm_axes_test` now exercise the derivation rather than
  a stored value; a matrix regression appears as a diff in those tests.
- The wire change is a removal: new JSON has no `world_matrix`, old JSON still
  deserializes because serde ignores unknown fields, and the Python `from_dict` ignores
  the legacy key. The checked-in fixture and mirror move together.
- No new dependency and no change to `[I1]` or `[I4]`.
