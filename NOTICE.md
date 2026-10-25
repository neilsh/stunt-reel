# NOTICE

This repository is an unofficial, non-commercial research and preservation project for
*Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line). It is not
affiliated with, authorised by, or endorsed by The Walt Disney Company or The Assembly
Line. "Stunt Island" and related marks are trademarks of The Walt Disney Company.

## No game assets

No game executables, films, archives, artwork, audio, or manual scans are distributed
here. `corpus/` and `target_bin/` are gitignored, and you must supply your own lawfully
obtained copy of any retail files. Tests run offline against synthetic fixtures.

## Game-derived data

Two small tables are committed because the renderer needs them for format fidelity. Both
are game-derived and are not relicensed by this project:

- `MODE_13H_PALETTE` (768 bytes: 256 RGB triples), the Stunt Island master palette
  (240 scene entries + 16 UI entries). It was transcribed from the community
  `SODParse/pal.h` in the Stunt Island Central archive and re-encoded as 6-bit DAC
  levels shifted left by two. The same data is pinned in
  `tests/fixtures/mode13h_palette.json` so the Rust and Python copies cannot drift.
- `SOD_SCALE_TABLE` (18 floating-point entries), the scale table from the community
  `SODParse/SOD.H` (Dave Palmowski), matching the historical `DECODE.C` implementation.

## Third-party material and credits

Quoted manual text, cited community research, and third-party tools remain under their
original terms; citation does not relicense them. Key credits:

- **Chris Phillips** — SODParse (`RIPRES.C`, `DECODE.C`, `SOD.H`), SIRes, FreeFlight.
- **Dave Palmowski** — SODParse `SOD.H` scale table, RESMaker, `SITools/`.
- **Ángel Eduardo** — Stunt Island Extractor (2004–2005).
- **Doug Armknecht** — Stunt Island Central developer archive.
- **Alberto Marnetto** — `si-tools` and the `si-8x` patch (MIT), consulted and not vendored.
- **Fabrice Bellard** — LZEXE; `python/scripts/unlzexe.py` is a minimal Python unpacker
  written for analysis, not a copy of LZEXE.
- **Adrian Stephens** — original Assembly Line engine developer.
- **Neil Halelamien** — original `.SET` format notes (2004).

Dependencies retain their own licences; `cargo deny` enforces the Rust allow-list and the
Python tooling dependencies are dev-only. DOSBox-X, ffmpeg, Kaitai Struct and the
DOSBox-X MCP server are external prerequisites, not bundled here.
