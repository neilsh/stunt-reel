# FLM Field Notes (Inferred)

This file summarizes what the current parser can identify and what each field likely means.
It is based on:

- `Freeflight/sifilm.cpp` parsing logic
- `Freeflight/sifilm.h` data structures
- `Documents/SIManual.txt` Chapter 5, Chapter 6, Chapter 8
- `SiRes/SIResNames.h` object/shape ID names

## Header

- File starts with ASCII signature `FILM` (4 bytes).
- Remaining payload is a stream of time slices.

## Slice Structure

Each slice starts with:

- `inctime` (1 byte)
- `declared_len_word` (2 bytes)

Then a sequence of opcodes until `0xFF` (end-of-slice).

Corpus clue:

- In many films, `declared_len_word` values parsed as little-endian are often multiples of 256.
- Byte-swapped values (`swap16`) often look like small counters/timing values.
- This suggests the field might be big-endian in source data or otherwise packed in a nonstandard way.

## Object Flags (`type_flags`)

From `sifilm.h`:

- `E` (`SIF_EXISTS`): object exists
- `D` (`SIF_DRAW`): has drawable shape
- `S` (`SIF_SHADOW`): shadow-enabled flag
- `M` (`SIF_MOVES`): uses per-slice motion interpolation
- `R` (`SIF_ROTATES`): uses per-slice rotation interpolation
- `A` (`SIF_ANIMATES`): includes animation value

If `M`/`R` are not set, static position/rotation values are stored in create data.

## Opcode Groups

`00xxxxxx` (`create`):

- Defines object slot and type flags.
- May include shape ID, static position, static rotation.

`01xxxxxx` (`interp`):

- Per-slice update for move/rotate/animate fields, depending on object flags.

`10xxxxxx` (`misc`):

- `0x80-0x8F` var set (`nextvar[0..15]`)
- `0x90-0x97` view object select (`view_obj`)
- `0x98` clear credits
- `0x99` set two credit strings (NUL-terminated)
- `0x9B` set `max_obj`
- `0x9C` sound event (byte + word args)
- `0xA0+` "before" control words (not fully resolved)

`11xxxxxx`:

- Treated as unknown/error in `sifilm.cpp`.

## Manual Cross-Reference (Likely Mappings)

These are informed inferences, not yet fully proven:

- Chapter 5 (`SIManual.txt`) explains slots 1-8 as recording-capable camera/prop slots.
  `view_obj` likely corresponds to camera/slot view selection used during playback.
- Chapter 6 explains Events with Start Rec, Stop Rec, CutTo camera, object changes, and 16 flags.
  `var_set (0x80-0x8F)` likely maps to this flag/event state machinery.
- Chapter 8 explains post-production credits, audio/silence marks, and cut-based edited films.
  `0x99` credits and `0x9C` sound opcodes align well with those editor operations.

## Coordinate and Rotation Units

From `sifilm_draw()`:

- Position is fixed-point 16.16 (`raw / 65536`).
- Rotation uses `raw / (65536/360)` degrees.

## Known Unknowns

- Exact semantics of the slice header length word.
- Exact meaning of `0xA0+` before/control opcodes.
- Full interpretation of sound args in `0x9C`.
- Why some films can emit `interp` against objects currently marked non-existing (seen in corpus).
