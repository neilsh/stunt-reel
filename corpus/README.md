# Corpus Reference & Data Archives

This directory serves as the root storage for *Stunt Island* reference archives, demo files, and community format-analysis packages. Due to copyright and archive size, source archives and extracted binary assets are not committed directly to the repository.

> [!WARNING]
> You must supply your own lawfully obtained copy of every archive described here. We do not host, distribute, or endorse these archives; their contents may be copyrighted and their legal status varies by jurisdiction. The quality gate does not need this directory — `mise run check` passes on a clean clone.

---

## 1. Stunt Island Demo (`stisldem/`)

The `stisldem/` folder is reserved for the official MS-DOS promotional demo of *Stunt Island* (1992).

### Setup Instructions

1. **Obtain `stisldem.zip`**: Get the demo archive from a source you are entitled to use, and place it in `corpus/`.
2. **Extract into `corpus/stisldem/`**:
   - Unzip the contents of `stisldem.zip` directly into the `corpus/stisldem/` directory.
   - **Important**: Ensure directory structure is preserved during extraction (e.g., `pkunzip -d` or standard modern zip extraction) so that the `VAULT/` subfolder (containing demo `.FLM` film reels such as `CTRY.FLM`, `DES.FLM`, `TOWN.FLM`) is created properly.

### Expected Contents

The demo's `VAULT/` holds a complete `.FLM` + `.ALL` pair only for `INTRO` and `CTRY`. The full game (`corpus/stuntisl/`, when supplied) ships further `.FLM` files with no `.ALL`; `mise run make-all` generates one with `MAKEONE.EXE` and stores it under `captures/all/`, never here.

- `PLAYONE.EXE` — Standalone film reel playback utility.
- `VAULT/` — Directory containing sample film reels (`.FLM`), takes (`.TKE`), and camera setups.
- `DRIVER1.BIN`, `DRIVER2.BIN`, `DRIVER3.BIN` — Audio drivers.
- `GAME.CFG`, `INSTALL.CFG`, `INSTALL.EXE` — Configuration tools.
- `PFONT.BIN`, `VDATA.BIN` — Font and visual resources.
- `SETUP.BAT`, `README.TXT` — Setup script and original release notes.

---

## 2. Stunt Island Central Archive (`siarchive/`)

The `siarchive/` folder contains historical assets, developer utilities, file format documentation, and community tools curated by Doug Armknecht.

### Setup Instructions

1. **Obtain the archive**: Get the Stunt Island Central Archive from its curator's site (we neither link, host nor redistribute it) and place the zip in `corpus/`.
2. **Extract into `corpus/siarchive/`**: Unzip the contents directly into `corpus/siarchive/`.

### Expected Directory Layout

The extracted `siarchive/` directory includes a `Developer/` folder containing format-analysis tools and source code:

- **`Developer/`**
  - **`sodparse/`** (or `SODParse/`):
    - `RIPRES.C` — Resource extractor source code for extracting objects and scenery.
    - `DECODE.C` — Object decoder source code.
    - `SI.MTL` — Wavefront material definitions.
    - `Fragment/` — Additional parsing headers and source fragments (e.g. `scenery1.h`–`scenery6.h`, `siobj.c`, `siobj.h`).
  - **`freeflight/`** (or `FreeFlight/`):
    - `flm_reader.c`
    - `scenery.c`
    - OpenGL 3D island exploration utility (`Play.exe`, `SIDATA/`, and source fragments).
  - Additional analysis folders: `Notes_SETFile/`, `Notes_SIExtractor/`, `SI-8x/`, `SIDG/`, `SIRes/`, `SI_FLM_Format/`.

### Documentation and Community Sets

A folder-by-folder map of the whole extracted archive, with counts and what each part is good for: [`siarchive.md`](siarchive.md).

- **`Docs/`** — the retail handbook (`Docs/Manual/`), period reviews and ads, the SIFA email archive, and Disney's support updates (`Docs/Disney_Support/`). Read as primary sources; see [`research/handbook.md`](../research/handbook.md).
- **`Misc/Sets/`** — 92 tutorial `.SET` files from the 1993 authoring examples. Twenty-two ship with a printed `.TXT` describing the same set; they are tutorial articles rather than one-to-one dumps and disagree with their binaries on some header fields, so treat them as a lead rather than an oracle.

## External References (not in the corpus)

- [`AlbertoMarnetto/si-tools`](https://github.com/AlbertoMarnetto/si-tools) (MIT, 2026): `si-8x` detail patch, `sod-decoder` (`.SOD` to `.obj`) and `si-free-flight-2` (raylib island viewer that reads the scene tree from the executable's stack segment; its `terrain_mapbin.cpp` embeds a `MAP.BIN` byte-identical to `Developer/FreeFlight/SIDATA/MAP.BIN`). Consulted, not vendored; the local checkout is commit `bf2b666` (2026-04-26).
