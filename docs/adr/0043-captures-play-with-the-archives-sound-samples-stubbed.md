# Captures play with the archive's sound samples stubbed

## Status

accepted 2026-11-09. Leaves [ADR 0028](0028-a-film-has-one-capture-of-each-kind.md)'s one capture
of each kind per film and [ADR 0037](0037-a-reference-pins-its-archive.md)'s archive pin
unchanged.

## Context

On six of the seven reference films, a recapture from the film's `MAKEONE` archive differs from
the reference on about a quarter to a half of the pages they both hold. As a result, the parity
verdict could not tell a render change from recapture noise (#305).

On `BALLOON.FLM` the difference comes from the archive's chunks in the sound range
`0xC000`–`0xCFFF`, and `CTRY.FLM` fits.
- Two `BALLOON` captures with those chunks differed on 26 of 102 pages. With each payload cut to
  one byte, two captures agreed on 108 of 108.
- A stubbed `CTRY` pair, started 0.1 s apart, agreed on 121 of 121 pages. An earlier pair with
  sound, captured one after the other, differed on 27 of the 111 pages both held.
- The demo's `CTRY.ALL`, whose samples are shortened, also replays identically
  ([capture note](../../research/playone-exe/capture-dosbox-automation.md) § 4.4).

The stub changes the pictures as well. The stubbed `BALLOON` capture differs from the reference
captured with sound on 66 of 96 pages. A stubbed capture is a different recording of the film,
not a cleaner copy of the old one.

## Decision

- **Staging stubs the sound range.** `staging.stage_play` writes
  `all_archive.stub_sound_samples` of the film's archive into the mount. Each chunk in
  `0xC000`–`0xCFFF` gets the one byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302`.
  That covers both samples and the range's music chunks. The demo keeps its own music chunk
  whole. No chunk outside the range changes.
- **`--sound-samples kept` records with sound.** `capture-ref` and `capture-video` take it, and
  the default is `stubbed`. A capture's `meta.json` records `"sound_samples"`. A capture without
  the field played with its samples, as every capture before this ADR did.
- **The pin stays the archive as resolved.** `all_sha256` is the hash of the archive before it
  is stubbed. The played archive is a function of that pin and `sound_samples`, so
  `references.toml` gains no field.
- **The reference captures are recaptured stubbed and repinned once.** Their scores move, and
  the move is recorded, not gated: a reference is chosen for being repeatable, not for scoring
  well.

## Considered Options

- **Consensus capture.** Capture each film three times and keep the majority page, as proposed
  on #305. It triples capture time and needs a rule for pages where no two runs agree. It also
  hides the cause instead of removing it, and it breaks ADR 0028's one capture per film.
- **Stubbing in `stuntreel link`.** The archive our renderer reads would then match what was
  played. Renders never read sound, though, so the stub belongs where PLAYONE meets the archive.
- **A zero-length payload or a minimal well-formed sample.** Neither was tried. What PLAYONE
  does with the one-byte stub is unknown, beyond the fact that it replays identically.

## Consequences

- A recapture of a reference film is expected to match it page for page, so the verdict's rule
  without a σ (only a Δ of exactly 0 is within noise) applies, and `noise_sigma` is retired.
- Captures no longer record what a film's sound does to its pictures. Use `--sound-samples kept`
  for that.
- The batch survey's existing captures stay as they are. Their `meta.json` lacks the field, so
  they played with their samples.
- `mise run play`, the light probe and `mise run debug-x` (`dbx/boot.py`) stub as well, with no
  option, so what a person watches or traces matches what a capture records. A trace made before
  this ADR played the sound.
