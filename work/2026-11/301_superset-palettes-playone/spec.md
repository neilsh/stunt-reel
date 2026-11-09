# Spec: a superset archive with the palette items, on `PLAYONE`

## Facts found while settling the plan

Read from `<data root>/builds/{unpatched,patch3}/RES/SPRITES.RES` with `superset_all.res_items` on 2026-11-08:

- Items `0x1E` and `0x42` (50 and 722 bytes, the same as chunks `0x801E` and `0x8042` in every stored archive; `linking.md` § 1 said 48 and 720, the colour triples alone, and is corrected) are byte-identical in the unpatched and Patch 3 builds. "From the matching build" does not matter for the palettes; each build still uses its own `RES\` for the shapes.
- Patch 3's `SPRITES.RES` differs (sha256 `64274cae…` against `95d3e3c4…`) only in items `0x54` and `0x55`: the unpatched file holds 85 items, Patch 3 84. This partly answers `linking.md` open question 4; whether Patch 3 changes a shape file is checked while building the supersets.
- The demo's shipped `CTRY.ALL` holds `0x8042` but not `0x801E`; every `make-all` archive and the demo's `INTRO.ALL` and `SCENE01.ALL` hold both.
- The demo's `PLAYONE.EXE` is byte-identical to the retail unpatched one (`3c93493c…`).
- The 2026-11-07 TOD captures behind § 7.2 are no longer in the data root, so every arm is captured fresh.

## Tooling

- **`superset-all --with-palettes`**: adds `0x801E` and `0x8042` from the `--game` tree's `SPRITES.RES`. Off by default, so the renderer's superset stays as it is.
- **`capture-ref --archive <.ALL>`**: stages that file as the film's archive and records its sha256 in `meta.json`.
- **`make-all --out`** (`--game-root` already existed): writes a build's own archive outside `captures/<film>/archives/`, so no reference pin moves.
- **`capture-compare A B`** (new): pairs two captures' index pages by exact `film_tick` and prints the shared-tick count, identical pages, median and 90th-percentile differing pixels, and whether the paired palettes are byte-equal. Fewer than 20 shared ticks is reported as unpaired, not judged. Pairing by nearest tick measures motion ([#299](https://github.com/neilsh/stunt-reel/issues/299)).

Each is tested on synthetic fixtures.

## Experiment

- **Films**: `CTRY.FLM` and `TOD.FLM` (slug `vault-tod`, not a reference film). **Builds**: unpatched and Patch 3, each with its own `RES\`.
- **Own archive**: the `make-all` rebuild for that build, for both films (not the demo's shipped `CTRY.ALL`, which comes from a third `MAKEONE`).
- **Arms per film and build**: the own archive captured 3 times (`own-1`…`own-3`), the superset with palettes once (`superset`). 16 captures in all. No superset-without-palettes arm and no cross-build arm.
- **Layout**: `<data root>/bench/<slug>/301/<build>/` holding `own.ALL`, `superset.ALL`, the four capture directories and `compare.txt`.

## Judging

- The 3 own-vs-own pairs give the noise band: the range of their identical-page fractions and 90th-percentile differing pixels.
- The superset arm, against each own capture, passes when its paired palettes are byte-equal and both statistics fall inside the band.

## Outcomes

- **Passes on both films and builds**: § 7.2 becomes a `[Bounded Observation]` that the superset with palettes plays like a film's own archive on two films; open question 8 is answered; the `superset_all.py` docstring drops "for our renderer only" for `--with-palettes`.
- **Fails**: record the 12 pair rows in § 7.2 and open an issue for an arm that pads the own archive with the superset's extra shape chunks, to separate the extra props from the rest.
- **Either way**: open question 4 gets the Patch 3 `SPRITES.RES` finding.

## Shipping

One PR: the tooling, the `linking.md` edits, the **Superset archive** term in `GLOSSARY.md`, this folder and a `journal.md` entry. A fresh reviewer reads the `research/` diff before the push (AGENTS.md § 3, rule 7). No ADR: no decision here is hard to reverse.
