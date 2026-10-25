# `si_archive/`: What Is In the Reference Corpus

The extracted Stunt Island Central Archive (Doug Armknecht's collection): roughly **3,700 files and 600 MB**. Every byte here is gitignored under `[I7]` and used as evidence only; nothing in it ships with the project or enters a test fixture.

This file is a map, not an index. It exists so nobody blind-scans 3,700 files: read the folder section you need, then grep inside it.

Counts are a snapshot of the local extraction (2026-10-24) and drift as the archive grows.

## Start here

| If you need | Go to |
|---|---|
| The game's own words for its structures | `Docs/Manual/`; how to cite it is [`research/handbook.md`](../research/handbook.md) |
| Formats as the community decoded them | `Developer/SI_FLM_Format/`, `Developer/Notes_SETFile/` |
| A second decoder written from the format, not from our code | `Developer/FreeFlight/src/`, `Developer/SODParse/` |
| World data the renderer consumes | `Developer/FreeFlight/SIDATA/` |
| A complete player run directory | `Films/NewPLAY/` |
| Sets to decode, with printed field dumps | `Misc/Sets/` |
| Films for a corpus sweep | `Films/` |
| Hand notes on the authoring formats | `SITools/Docs/` |

## `Developer/` (140 files, 8.8 MB)

| Folder | What it holds | Relevance |
|---|---|---|
| `SI_FLM_Format/` (12) | Doug Armknecht's `.FLM` work: `FLM_FORMAT_DOUG_NOTES.txt`, `FLM_NOTES.md`, `CORPUS_FINDINGS.md`, extract/compare scripts, `Source/` | Primary source for [`research/formats/flm.md`](../research/formats/flm.md) |
| `Notes_SETFile/` (2) | `Stunt_Island_SET_fileformat_notes.txt`, `SET_File_Email_Thread.txt` (Neil Halelamien, 2004) | Primary source for [`research/formats/auxiliary/set.md`](../research/formats/auxiliary/set.md) |
| `FreeFlight/` (32) | `src/` (`sifilm.cpp`, `sifilm.h`, `scenery.c`) and `SIDATA/` with `MAP.BIN`, `ANCHORPT.DAT`, `SCENERY.scn`, `SCENERY1-6.RES`, `MAP.3DS` | The world data the player reads; source of the anchor-table evidence |
| `SODParse/` (39) | `RIPRES.C`, `DECODE.C`, `SI.MTL`, `Fragment/` scenery headers | `.SOD` decoding prior art |
| `SIRes/` (50) | Resource-extraction tooling | `.RES`/archive layout checks |
| `Notes_SIExtractor/` (1), `SI-8x/` (2), `SIDG/` (1) | Smaller utilities and notes | Consulted case by case |

## `Docs/` (72 files, 92.3 MB)

| Folder | What it holds |
|---|---|
| `Manual/` (2) | `stuntisle.pdf` (scanned handbook) and `SIManual.txt` (its OCR text) |
| `Disney_Support/` (4) | `SIUPDATE.TXT`, `SIUPDATE2.txt` (revised handbook plus tutorials), `SIPRODUCTINFO.txt`, `ALLFILES.TXT` |
| `SIFA_Email/` (27) | The 1997 SIFA email archive, including `MBoxView/` |
| `Reviews_and_Ads/` (17) | Period magazine reviews and advertisements |
| `Interviews/` (17) | Designer interview scans |
| `Tips/` (2) | Playing tips |

Loose here: `SIHistory.txt`, `SIFAprofiles_1997.txt`, and Mic Healy's "how big is Stunt Island".

## `Films/` (901 files, 401.3 MB)

The film corpus, split by how each package was assembled: `FLMOnly/` (143), `FLMUsnd/` (16), `MultiFLM/` (306), `NewPLAY/` (232), `OldPLAY/` (147), `READMES/` (53). `Films_By_Year.png` and two `.xlsx` inventories describe the set.

`NewPLAY/` is a complete run directory rather than loose films: `DRIVER1-3.BIN`, `GAME.CFG`, `GAME.VAR`, `Vault/`. `GAME.VAR` is the detail word documented in [`research/playone-exe/lod.md`](../research/playone-exe/lod.md).

## `Misc/` (192 files, 12.9 MB)

| Folder | What it holds | Relevance |
|---|---|---|
| `Sets/` (120) | **92 `.SET` files and 22 printed `.TXT` dumps** emitted by the authoring tools | A field-level oracle for `.SET`: every header, prop and event field decoded in prose next to its binary |
| `UserSnds/` (7) | `Dean1`, `Dean2` sound banks | The `Usersnd` category the handbook describes |
| `MIDI/` (35) | Music | Outside playback scope |
| `GameMaps/` (7) | CivNet and Warcraft II maps | **Not Stunt Island** |
| `ClawIsle/` (9), `Film_Production_BTS/` (12), `Font/` (2) | Collected odds and ends | Unclassified; not used yet |

## `SITools/` (1,406 files, 11 MB)

| Folder | What it holds |
|---|---|
| `Docs/` (8) | `Adrian_Subobjects.txt`, `deannote.txt`, `DougTutorial.txt`, `EDITOR.DOC`, `shading.doc`, `subobj.txt` — hand notes on subobjects, shading and the editors |
| `OBJECTS/` (1,289) | The object/sprite library |
| `SpriteMaker/` (34), `ResMaker/` (21), `Slice/` (28), `GameReady/` (13) | Authoring utilities |

Loose: `ANCHORPT.DAT` (an anchor-table copy, cited in [`research/formats/flm.md`](../research/formats/flm.md)), `EGA.LBM`, `LOVELY.8X8`, `MAKERES.EXE`.

## The rest

- `Patch/` (9 files, 4.1 MB) — the Product Update: `P3-SI1..5.EXE`, `PATSI.BAT`, `README.TXT`, `SINEW.TXT`. Same payload as `corpus/SIPatch.zip`.
- `NEW/` (283 files, 40.8 MB) — `Films/` (20) plus the `Morganroth/` collection (263); unclassified.
- `Images/` (69 files, 22.4 MB) — box contents, covers, maps, keyboard overlays, prototype shots. Useful for release history and the handbook's art, not for byte-level work.
- `Websites/` (632 files, 22.7 MB) — eight snapshots of community sites (1999-2023); release history and tool discovery.
- `SI_Archive_Readme.txt`, `SI_Archive_News.txt`, `Archive_Files_Chart.png` — the collector's own descriptions.

## What is not evidence

`Misc/GameMaps/` holds maps for other games. `Images/` and `Websites/` are scans and captures. `Misc/MIDI/` is music. None of them says anything about a format, and none should be cited as such.

## Open questions

1. `Misc/ClawIsle/`, `Misc/Film_Production_BTS/` and `NEW/Morganroth/` are unclassified; whether they contain material no other copy has is unknown.
2. The two `Films/*.xlsx` inventories may carry provenance for each film package (author, year, film count) that would let sweeps weight films by era. Unread.
