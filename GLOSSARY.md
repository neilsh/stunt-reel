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
One of the 64 timeline entity channels in a film. A slot binds a shape and carries position, orientation, and an optional animation input. Distinct from **Prop slot** and **Sound slot**, the handbook's other two uses of the word.
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

**Prop**:
A shape placed in the world by a `SCENERY.scn` leaf. A prop has a position and no orientation; a rotated variant is a separate shape.
_Avoid_: asset, scenegraph node

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

**Blocking opcode**:
The first opcode in a shape's bytecode that the evaluator does not implement; the point where a Partial SOD stops.
_Avoid_: bad opcode, invalid opcode

**Masked opcode**:
An unimplemented opcode that sits after a shape's blocking opcode, so a lenient decode never reports it. Implementing the blocking opcode can expose it as the next one.
_Avoid_: hidden opcode (collides with face visibility, `OP_VOTEHID`)

**Anchor point** (also **tap point**):
A 28-byte terrain record shared by `MAP.BIN` patches and `OP_TAP`; it carries raw island coordinates and scratch fields for the display-list VM. `OP_TAP` copies the referenced records into the vertex register bank.
_Avoid_: debug marker, scratchpad touch

## Production (authoring)

Vocabulary the handbook uses for the authoring front end. These name data the player reads, not features StuntReel implements: see [`docs/SPEC.md` § 2.1](docs/SPEC.md#21-explicit-scope-boundaries--non-goals).

**Set**:
The authored stage stored in a `.SET` file: recording mode, numbered prop slots and their placement, camera rigs, and the event list.
_Avoid_: level, map, stage

**Take**:
One filmed attempt at a set's stunt, saved as a `.TKE` and numbered per set. A take is raw multi-camera footage; a film is its edit.
_Avoid_: shot, film

**Event**:
One numbered rule in a set's event list: an IF trigger, optional AND qualifiers, and THEN actions.
_Avoid_: script, trigger (alone)

**Flag**:
An author-assigned integer in a set's event system, range -128 to 127, tested by `Flag =` and `Flag ?` and written by `Set Flag`. Whether flags are the film's variable registers is not established.
_Avoid_: variable (for the event integers)

**Authored limit**:
A ceiling the authoring tools impose on a set (40 prop slots, 64 events, 655 seconds of event time), as opposed to a bound the file format enforces; the encoding is often wider, as `num_events` is a single byte, and the prop count is not stored at all — it is derived from the file length.
_Avoid_: format limit, hard limit

**Prop slot**:
A numbered container for a placed prop in a set, 1 to 40. Slots 1 to 8 also record film; slots 9 to 40 hold props only.
_Avoid_: slot (unqualified), film slot

**Recording slot**:
One of prop slots 1 to 8 in a set, each producing one camera angle. Slot 1 is the stunt aircraft and slot 2 the spotter.
_Avoid_: camera (for the slot itself)

**Camera angle**:
The view produced by one recording slot, to which the editing room assigns a deck.
_Avoid_: view, shot

**Sound slot**:
One numbered entry in a `Usersnd` bank; each of the five banks holds up to 253 sounds.
_Avoid_: slot (unqualified)

## Evidence

**Corpus**:
The local, gitignored set of original game files used as evidence. Never committed.
_Avoid_: assets

**Cleanroom fixture**:
Synthetic input built from format knowledge, containing no proprietary game data.
_Avoid_: test asset

**Parity**:
Comparison of a reconstructed render against a captured frame, scored by SSIM and mask IoU. The render is sampled from the timeline at the captured frame's film clock.
_Avoid_: parity (for checking a trajectory against an oracle trajectory)

**Oracle trajectory**:
A trusted reference trajectory that an evaluated timeline is checked against for position error. It concerns trajectory records only, never rendered pixels.
_Avoid_: parity oracle, golden frames

**Captured frame**:
One distinct rendered frame grabbed from `PLAYONE.EXE` at the vertical-retrace trap, numbered by capture order and tagged with its film clock.
_Avoid_: tick (for the capture ordinal)

**UI overlay**:
What `PLAYONE.EXE` draws over the 3D scene in a captured frame: the button bar, the mouse cursor, and credits text. The renderer does not draw it, and parity leaves it out of scoring.
_Avoid_: HUD, status bar

**Index agreement**:
The fraction of scored pixels whose palette index in the render equals the one in the captured frame. A diagnostic beside SSIM and mask IoU, not a gate.
_Avoid_: pixel accuracy, exact match

**Film clock**:
`PLAYONE.EXE`'s runtime count of 50 Hz ticks into the active film, read from DGROUP. It is the tick a captured frame shows.
_Avoid_: frame counter, global tick

**Fade level**:
The brightness of a captured frame relative to the static palette: about 1.0 when `PLAYONE` is not fading, falling to 0 over the end-of-film fade. The **authored fade level** is the same ratio taken from the film's own brightness palette control at that tick. Parity leaves out frames too faded to compare.
_Avoid_: brightness, exposure

**Sky band**:
One of the palette indices 227 to 238 that `PLAYONE.EXE` paints the sky with, in straight bands by view-ray elevation (238 at the horizon). Every captured pixel in a sky band is sky.
_Avoid_: sky index, clear colour (the render's framebuffer clear)

**Scored frame**:
A captured frame that enters a mean: matched to a render at its film clock, not excluded by the fade floor or the UI overlay. `mean_ssim_scored` averages scored frames only, so a score is always quoted with its count.
_Avoid_: valid frame, sampled frame

**Probe**:
A measurement of one frame or region through `parity_probe.py` — crop, shift, actor IoU, retime. An investigation that is still open is an open question, not a probe.
_Avoid_: probe (for a hypothesis still to be settled)

**Round**:
One hypothesis class closed by one batched sweep, its adoption decision and its log row. A round may begin by reading one `PLAYONE.EXE` rule when no renderer-only lever fits.
_Avoid_: iteration, pass

**Sweep**:
One run of `mise run sweep` over the product of one hypothesis class's candidate values, scoring every variant on both films. The round ends at its result.
_Avoid_: batch run, grid search

**Adoption**:
Keeping a round's best candidate. An evidence-backed change (a rule read from `PLAYONE.EXE`, cited at an image offset) adopts when neither film regresses by more than 0.002 SSIM and one improves; a heuristic change needs both films above +0.002, or one above +0.004 with the other within 0.002.
_Avoid_: acceptance, merge (for the parity decision)
