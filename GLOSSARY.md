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
One discrete simulation step at the film's authored rate (20 or 30 Hz). A slice spans zero or more ticks.
_Avoid_: frame, slice

**Tick duration**:
The number of ticks a slice spans; zero denotes a slice that changes state without advancing time.
_Avoid_: slice duration, frame count

**Trajectory record**:
The evaluated snapshot of camera, actors, and audio cues for one slice. This is what the renderer consumes.
_Avoid_: trajectory tick, frame

**Trajectory**:
The ordered sequence of trajectory records for a film.
_Avoid_: animation

**Epilogue**:
The terminal film record marking end of stream. It carries the last slice's length and an end marker, and is not a slice.
_Avoid_: trailer, final slice

**Camera cut**:
An instantaneous camera reposition between consecutive trajectory records, exempt from interpolation.

## Assets and models

**Archive**:
A `.ALL` container of numbered model chunks addressed by `shape_id`, paired with a film.
_Avoid_: bundle, resource file

**Shape**:
A model chunk in an archive, identified by `shape_id`. One shape may be bound to several slots.
_Avoid_: sprite, object

**Slot**:
One of the 64 timeline entity channels in a film. A slot binds a shape and carries position, orientation, and animation state.
_Avoid_: actor

**Actor**:
An evaluated slot presented to the renderer, excluding the slot driving the camera.
_Avoid_: object, entity

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
Comparison of a reconstructed render against a frame captured from `PLAYONE.EXE`, scored by SSIM and mask IoU.
