# A film's archive is committed as a manifest

## Status

accepted 2026-11-03. Implemented on branch `feat/all-manifests`
([spec](../process/plans/all-manifests-2026-11-03.md),
[plan](../process/plans/all-manifests-implementation-2026-11-03.md)). Amends the resolve order of
[ADR 0023](0023-make-all-generates-archives-with-makeone.md): a committed manifest comes between
the sibling `.ALL` and the stored archive. The stored archive of
[ADR 0028](0028-a-film-has-one-capture-of-each-kind.md) stays, as the fallback and as the source a
manifest is extracted from.

## Context

A film without a shipped `.ALL` needs one before `PLAYONE` can play it, and `make-all` writes it by
running `MAKEONE.EXE` under an emulator. The result lives only in the data root of the machine that
ran it, so every other machine or fresh data root has to run the emulator again.

The archives turn out to be simple ([`linking.md`](../../research/makeone-exe/linking.md)). Every
chunk that comes from the game is a byte-identical copy of one item of a `RES\` file, its id is
`(res_index << 8) | item`, and the layout is fixed, so 83 of 83 stock-only corpus archives rebuild
byte for byte from their id lists. Which items a film gets is the hard part: it looks like whatever
the renderer loaded while `MAKEONE` played the film, and the sound setting picks between files that
share an index (`MUSIC1.XMA` and `MUSIC1.ESS` are both `0xC0`).

## Decision

- **One manifest per film, committed** (`manifests/all/<slug>.toml`), changed only by a reviewed
  commit. It is TOML, grouped by source file: each `[[source]]` has the file, its `res_index`, its
  SHA-256 and the item numbers.
- **`MAKEONE` still decides what goes in.** We record its decision once: `make-all` extracts the
  manifest from the archive it has just stored, and `--manifest-only` does the same for an archive
  stored earlier.
- **Hashes guard every step.** Each source file's hash is checked before a build, and the result
  must hash to the `all_sha256` of `MAKEONE`'s archive; `extract` refuses a manifest whose rebuild
  differs. A different release, Patch #3's resources or another sound file fails loudly and names
  the file.
- **Pure core, I/O in the CLI.** `stunt_core::link` and the `.ALL` writer see only bytes (`[I7]`);
  `stuntreel link extract|build` reads, hashes and writes. Exit 3 means not linkable.
- **Resolve order: sibling, manifest, stored archive.** A manifest whose `flm_sha256` is the film's
  is rebuilt into `target/linked/<slug>/` on each resolve. One that matches but fails to build is an
  error, never a silent fall back to a stale stored archive.
- **An archive with add-on content gets no manifest.** Its stored archive stays the record, and
  `make-all` says why.
- **`NOTICE.md` names manifests.** They hold item numbers and hashes of game files, no game bytes;
  the archive is rebuilt from the user's own copy of the game.

## Considered Options

- **Choose the items ourselves**, a Rust `MAKEONE`. Rejected for now: the scenery selection seems to
  need the original's culling and level-of-detail choices over every frame
  ([`linking.md`](../../research/makeone-exe/linking.md) § 4), so it would be a second renderer to
  keep in step. The manifests are the test data such a linker would need.
- **Keep the stored archive as the only record.** Rejected: it is a game-derived binary that cannot
  be committed, so every machine runs the emulator again.
- **Replace the stored archive with manifests.** Rejected: archives with add-on content cannot be
  described by the game's `RES\`, and the stored archive is what a manifest is checked against.

## Consequences

- A checkout with the game files and a committed manifest gets a film's `.ALL` in milliseconds,
  with no emulator.
- The sound setting is part of the record: a manifest names the music file it was made with, and a
  tree with another file fails its hash check.
- A manifest's `game_root` is a hint. It is written relative to the checkout when the tree is inside
  it, and `stuntreel link build --game` overrides it.
