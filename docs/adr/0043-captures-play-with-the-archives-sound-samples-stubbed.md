# Captures play with the archive's sound samples stubbed

## Status

accepted 2026-11-09. Leaves [ADR 0028](0028-a-film-has-one-capture-of-each-kind.md)'s one capture
of each kind per film and [ADR 0037](0037-a-reference-pins-its-archive.md)'s archive pin
unchanged.

## Context

On six of the seven reference films, a recapture from the film's `MAKEONE` archive differs from
the reference on 23 to 45% of the pages they both hold. As a result, the parity verdict could
not tell a render change from recapture noise (#305). On `BALLOON.FLM` the difference comes from the one sound sample in the
archive. Two captures with it differed on 26 of 102 pages, and with that sample's payload cut
to one byte, two captures agreed on 108 of 108. The demo's `CTRY.ALL`, which ships its samples
stubbed, replays identically on both builds
([capture note](../../research/playone-exe/capture-dosbox-automation.md) § 4.4).

The stub changes the pictures as well. The stubbed `BALLOON` capture differs from the reference
captured with sound on 66 of 96 pages. A stubbed capture is a different recording of the film,
not a cleaner copy of the old one.

## Decision

- **Staging stubs every sound sample.** `staging.stage_play` writes
  `all_archive.stub_sound_samples` of the film's archive into the mount. Each chunk in
  `0xC000`–`0xCFFF` gets the one byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302`.
  No other chunk changes.
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
- `mise run play` and the light probe stub as well, with no option, so what a person watches
  matches what a capture records.
