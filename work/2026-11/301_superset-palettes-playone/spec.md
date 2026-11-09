# Spec: a superset archive with the palette items, on `PLAYONE`

## Facts found while settling the plan

Read from `<data root>/builds/{unpatched,patch3}/RES/SPRITES.RES` with `superset_all.res_items` on 2026-11-08:

- Items `0x1E` and `0x42` (50 and 722 bytes, the same as chunks `0x801E` and `0x8042` in every stored archive; `linking.md` § 1 said 48 and 720, the colour triples alone, and is corrected) are byte-identical in the unpatched and Patch 3 builds. "From the matching build" does not matter for the palettes; each build still uses its own `RES\` for the shapes.
- Patch 3's `SPRITES.RES` differs (sha256 `64274cae…` against `95d3e3c4…`) only in items `0x54` and `0x55`: the unpatched file holds 85 items, Patch 3 84. This partly answers `linking.md` open question 4; whether Patch 3 changes a shape file is checked while building the supersets.
- The demo's shipped `CTRY.ALL` holds `0x8042` but not `0x801E`; every `make-all` archive and the demo's `INTRO.ALL` and `SCENE01.ALL` hold both.
- The demo's `PLAYONE.EXE` is byte-identical to the retail unpatched one (`3c93493c…`).
- The 2026-11-07 TOD captures behind § 7.2 are no longer in the data root, so every arm is captured fresh.
- From the "Reducing capture noise" session, 2026-11-09, not yet landed: on `CTRY.FLM` and `BALLOON.FLM` (BALLOON the controlled test) recapture noise comes from the archive's sound sample chunks (`0xC000`–`0xCFFF`); with them stubbed, replays are bit-identical, and stubbing them also changes what is drawn. The superset holds no sound chunk, so the missing sounds are a third candidate for § 7.2's differences beside the palettes and the extra props. Our noise band would also have measured sample playback, not the archive's contents.

## Tooling

- **`superset-all --with-palettes`**: adds `0x801E` and `0x8042` from the `--game` tree's `SPRITES.RES`. Off by default, so the renderer's superset stays as it is.
- **`capture-ref --archive <.ALL>`**: stages that file as the film's archive and records its sha256 in `meta.json`.
- **`make-all --out`** (`--game-root` already existed): writes a build's own archive outside `captures/<film>/archives/`, so no reference pin moves.
- **Stubbing an archive's sample chunks**: built by [#305](https://github.com/neilsh/stunt-reel/issues/305) (`work/2026-11/305_recapture-noise/spec.md`) in its first stacked PR, which also adopts `capture-compare`; this branch rebases onto that PR and drops its own copy of `capture-compare`. Nothing below runs before it lands. The interface:
  - `mise run stub-sound-samples -- IN.ALL -o OUT.ALL [--sound-ids-from OWN.ALL]` replaces every `0xC000`–`0xCFFF` chunk's payload with the byte `0x04` (the demo `CTRY.ALL`'s `0xC302` stub), keeping ids and order; `--sound-ids-from` adds a stub for each sound id of `OWN` that `IN` lacks.
  - `capture-ref --sound-samples stubbed|kept`, default `stubbed`, stubs the staged archive; `meta.json` records `sound_samples`, and `all_sha256` stays the unstubbed archive's hash.
- **`capture-compare A B`** (new): pairs two captures' index pages by exact `film_tick` and prints the shared-tick count, identical pages, median and 90th-percentile differing pixels, and whether the paired palettes are byte-equal. Fewer than 20 shared ticks is reported as unpaired, not judged. Pairing by nearest tick measures motion ([#299](https://github.com/neilsh/stunt-reel/issues/299)).

Each is tested on synthetic fixtures.

## Experiment

- **Films**: `CTRY.FLM` and `TOD.FLM` (slug `vault-tod`, not a reference film). **Builds**: unpatched and Patch 3, each with its own `RES\`.
- **Own archive**: the `make-all` rebuild for that build, for both films (not the demo's shipped `CTRY.ALL`, which comes from a third `MAKEONE`).
- **Sounds**: every arm but one plays with the film's sample chunks stubbed, the same stubbed ids in each, so sound is not a variable.
- **Arms per film and build**:
  - `own-1`, `own-2`: `capture-ref --archive own.ALL`, samples stubbed by the default. If the pair is not bit-identical, a third (`own-3`).
  - `superset`: `superset.ALL` is `stub-sound-samples superset-bare.ALL --sound-ids-from own.ALL`, the superset with palettes plus the own archive's sound ids as stubs.
  - `superset-bare`: the superset with palettes as `superset-all` writes it, no sound chunk; how a film with no archive plays from it. The default stubbing leaves it unchanged.
  - 16 captures in all (20 if every pair needs a third). No superset-without-palettes arm and no cross-build arm.
- **Layout**: `<data root>/bench/<slug>/301/<build>/` holding `own.ALL`, `superset.ALL`, `superset-bare.ALL`, the capture directories and `compare.txt`.

## Judging

- The own-vs-own pair gives the noise band; with samples stubbed it is expected to be zero (every paired page and palette identical). With three captures, the band is the range of their pairs' identical-page fractions and 90th-percentile differing pixels.
- `superset` against each own capture passes when its paired palettes are byte-equal and both statistics fall inside the band; a difference left is the palettes', the props' or another chunk's, not the sounds'.
- `superset-bare` is judged the same way; it answers whether a missing sound chunk plays like a stubbed one.

## Outcomes

- **Passes on both films and builds**: § 7.2 becomes a `[Bounded Observation]` that the superset with palettes plays like a film's own archive on two films; open question 8 is answered; the `superset_all.py` docstring drops "for our renderer only" for `--with-palettes`.
- **Fails**: record every pair row in § 7.2 and open an issue for an arm that pads the own archive with the superset's extra shape chunks, to separate the extra props from the rest.
- **Either way**: open question 4 gets the Patch 3 `SPRITES.RES` finding.

## Shipping

One PR: the tooling, the `linking.md` edits, the **Superset archive** term in `GLOSSARY.md`, this folder and a `journal.md` entry. A fresh reviewer reads the `research/` diff before the push (AGENTS.md § 3, rule 7). No ADR: no decision here is hard to reverse.
