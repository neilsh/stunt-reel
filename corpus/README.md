# Corpus Reference & Data Archives

This directory serves as the root storage for *Stunt Island* reference archives, demo files, and community reverse-engineering packages. Due to copyright and archive size, source archives and extracted binary assets are not committed directly to the repository and should be downloaded and unzipped into their respective subdirectories.

---

## 1. Stunt Island Demo (`stisldem/`)

The `stisldem/` folder is reserved for the official MS-DOS promotional demo of *Stunt Island* (1992).

### Setup Instructions

1. **Download `stisldem.zip`**: Obtain the demo archive (e.g. from classic DOS gaming archives or historical software repositories) into `corpus/`.
2. **Extract into `corpus/stisldem/`**:
   - Unzip the contents of `stisldem.zip` directly into the `corpus/stisldem/` directory.
   - **Important**: Ensure directory structure is preserved during extraction (e.g., `pkunzip -d` or standard modern zip extraction) so that the `VAULT/` subfolder (containing demo `.FLM` film reels such as `CTRY.FLM`, `DES.FLM`, `TOWN.FLM`) is created properly.

### Expected Contents

- `PLAYONE.EXE` — Standalone film reel playback utility.
- `VAULT/` — Directory containing sample film reels (`.FLM`), takes (`.TKE`), and camera setups.
- `DRIVER1.BIN`, `DRIVER2.BIN`, `DRIVER3.BIN` — Audio drivers.
- `GAME.CFG`, `INSTALL.CFG`, `INSTALL.EXE` — Configuration tools.
- `PFONT.BIN`, `VDATA.BIN` — Font and visual resources.
- `SETUP.BAT`, `README.TXT` — Setup script and original release notes.

---

## 2. Stunt Island Central Archive (`si_archive/`)

The `si_archive/` folder contains historical assets, developer utilities, file format documentation, and community tools curated by Doug Armknecht.

### Setup Instructions

1. **Download Archive**: Download the zip file from [Stunt Island Central Archive](https://armknechted.com/sicentral/newpage/SIArchive.html).
2. **Extract into `corpus/si_archive/`**: Unzip the contents directly into `corpus/si_archive/`.

### Expected Directory Layout

The extracted `si_archive/` directory includes a `Developer/` folder containing reverse-engineering tools and source code:

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
  - Additional reverse engineering folders: `Notes_SETFile/`, `Notes_SIExtractor/`, `SI-8x/`, `SIDG/`, `SIRes/`, `SI_FLM_Format/`.

### Documentation and Community Sets

A folder-by-folder map of the whole extracted archive, with counts and what each part is good for: [`si_archive.md`](si_archive.md).

- **`Docs/`** — the retail handbook (`Docs/Manual/`), period reviews and ads, the SIFA email archive, and Disney's support updates (`Docs/Disney_Support/`). Read as primary sources; see [`research/handbook.md`](../research/handbook.md).
- **`Misc/Sets/`** — 92 tutorial `.SET` files from the 1993 authoring examples. Twenty-two ship with a printed `.TXT` dump that decodes every header, prop and event field in prose, which makes them a field-level oracle for the `.SET` format rather than just sample data.

## External References (not in the corpus)

- [`AlbertoMarnetto/si-tools`](https://github.com/AlbertoMarnetto/si-tools) (MIT, 2026): `si-8x` detail patch, `sod-decoder` (`.SOD` to `.obj`) and `si-free-flight-2` (raylib island viewer that reads the scene tree from the executable's stack segment; its `terrain_mapbin.cpp` embeds a `MAP.BIN` byte-identical to `Developer/FreeFlight/SIDATA/MAP.BIN`). Consulted, not vendored; the local checkout is commit `bf2b666` (2026-04-26).
