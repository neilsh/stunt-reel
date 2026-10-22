# Stunt Reel

Cleanroom reconstruction of *Stunt Island* (1992) film playback: formats, evaluator, renderer, and parity tooling. This file is the canonical vocabulary. Implementation lives in [`docs/SPEC.md`](docs/SPEC.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Film playback

**Film**:
A `.FLM` authored timeline driving camera, actor, and audio state. Paired one-to-one with an archive.
_Avoid_: movie, replay

**Slice**:
One authored timeline record: a duration plus the state changes applied over it. A film is a sequence of slices.
_Avoid_: frame, keyframe, tick

**Tick**:
One discrete simulation step on the film's 50 Hz playback clock (20 ms). A slice spans zero or more ticks.
_Avoid_: frame, slice

**Tick duration**:
The number of ticks elapsed since the previous slice; zero denotes a slice that changes state without advancing time. Cumulative tick duration gives a slice's timestamp.
_Avoid_: slice duration, frame count

**Timeline**:
A film's slices placed on the 50 Hz clock by cumulative tick duration. Playback and export sample the timeline at arbitrary ticks or wall-clock times, interpolating between slice keyframes.
_Avoid_: track, sequence

**Trajectory record**:
The evaluated snapshot of camera, actors, audio cues, and palette controls at a slice timestamp or at an interpolated tick sampled from the timeline. This is what the renderer consumes. Its timestamp is always a 50 Hz tick, never a slice ordinal; a slice's ordinal is only its position in the timeline.
_Avoid_: trajectory tick, frame

**Trajectory**:
The ordered sequence of trajectory records for a film.
_Avoid_: animation

**Epilogue**:
The terminal film record marking end of stream. It carries the last slice's length and an end marker, and is not a slice.
_Avoid_: trailer, final slice

**Camera cut**:
An instantaneous camera reposition between consecutive trajectory records, exempt from interpolation.

**Palette controls**:
Film variables 13 (night term), 14 (brightness) and 15 (saturation), from which `PLAYONE.EXE` rebuilds palette entries 0–239 every frame. Fades, desaturation and dusk are authored through them.
_Avoid_: tone, palette fade (for the variables themselves)

**Animation input**:
The raw 16-bit value carried by a `.FLM` slot with `SIF_ANIMATES`. Its mapping to SOD resource selection is not established.
_Avoid_: joint angle, frame counter

## Assets and models

**Archive**:
A `.ALL` container of numbered model and auxiliary resource chunks, paired with a film. SOD model chunks are addressed by `shape_id`.
_Avoid_: bundle, resource file

**Shape**:
A 3D `.SOD` model chunk in an archive, identified by `shape_id`. One shape may be bound to several slots.
_Avoid_: sprite, object

**Animation image resource**:
A numbered `.ALL` image resource referenced by an `OP_ANIMATE` table and drawn at a projected screen position. It is distinct from a 3D shape.
_Avoid_: shape, joint

**Slot**:
One of the 64 timeline entity channels in a film. A slot binds a shape and carries position, orientation, and an optional animation input.
_Avoid_: actor

**Actor**:
An evaluated slot presented to the renderer, excluding the slot driving the camera.
_Avoid_: object, entity

**DOS axes**:
The raw coordinate frame of `.FLM` slots and anchor points in `PLAYONE.EXE`. It maps to `[I1]` by a 180° rotation about Z: `(x, y, z) → (−x, −y, z)`, applied to positions and orientations alike. Evaluated trajectory records are always `[I1]`.
_Avoid_: legacy coordinates

**World**:
The static scenery of an island: ocean, terrain patches built from `MAP.BIN` over anchor points, and props placed by `SCENERY.scn`. It is drawn with an identity transform.
_Avoid_: level, map (for the whole)

**Film scene**:
A film's timeline bound to its archive's shapes and the world. Sampling it at a tick yields a scene frame.
_Avoid_: scene bundle

**Scene frame**:
What to draw at one tick: the camera, the world, and one draw per visible actor carrying its shape, world matrix, state mask, and distance to the camera. Two actors sharing a shape are two draws.
_Avoid_: frame (alone), draw list

**glTF export**:
A `.glb` written by `stunt-gltf` for viewing a shape, or one scene frame, in standard tools. It carries `[I1]` geometry unchanged, palette colours as vertex colours, and the decoder's decal-displaced positions. It is a convenience format with no parity gate of its own.
_Avoid_: glTF parity, Phase 1 export

**Partial SOD**:
A shape whose bytecode stopped at an opcode the evaluator does not implement, or at `OP_TAP` without an anchor table; geometry decoded before the stop is retained.
_Avoid_: corrupt model, truncated SOD

**Anchor point** (also **tap point**):
A 28-byte terrain record shared by `MAP.BIN` patches and `OP_TAP`; it carries raw island coordinates and scratch fields for the display-list VM. `OP_TAP` copies the referenced records into the vertex register bank.
_Avoid_: debug marker, scratchpad touch

## Evidence

**Corpus**:
The local, gitignored set of original game files used as evidence. Never committed.
_Avoid_: assets

**Cleanroom fixture**:
Synthetic input built from format knowledge, containing no proprietary game data.
_Avoid_: test asset

**Parity**:
Comparison of a reconstructed render against a captured frame, scored by SSIM and mask IoU. The render is sampled from the timeline at the captured frame's film clock.

**Captured frame**:
One distinct rendered frame grabbed from `PLAYONE.EXE` at the vertical-retrace trap, numbered by capture order and tagged with its film clock.
_Avoid_: tick (for the capture ordinal)

**Film clock**:
`PLAYONE.EXE`'s runtime count of 50 Hz ticks into the active film, read from DGROUP. It is the tick a captured frame shows.
_Avoid_: frame counter, global tick

**Fade level**:
The brightness of a captured frame relative to the static palette: the median, over the indices present in the first captured frame whose static R+G+B exceeds 60, of (captured entry R+G+B) / (static Mode 13h entry R+G+B). About 1.0 when `PLAYONE` is not fading; it falls to 0 over the end-of-film fade. Parity measures the same ratio for the palette the render used and scales the render by the quotient (`ssim_compensated`).
_Avoid_: brightness, exposure
