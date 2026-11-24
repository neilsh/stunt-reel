---
summary: "A film's `.ALL` copies stock items verbatim, id-ordered by `(res_index << 8) | (segment + 1)`, music and common sounds by sound setting; stock shapes draw CTRY, INTRO and BALLOON like their archives in our renderer; on `PLAYONE` a superset with the palette items keeps the palettes, but some pages differ, as they do when the own archive is padded with inert chunks: not by content, nor by count, bytes or ids alone, but, on CTRY, once the padding makes the film's pages fall a whole film tick later (the smallest arms tried that change them: 368 one-byte chunks, 137,500 bytes in 63 chunks), and, in 34 captures, exactly when the pages fall on other emulator frames."
sidebar_label: "What the linker puts in a .ALL"
---
# `MAKEONE.EXE`: What the Film Linker Puts in a `.ALL`

`MAKEONE.EXE` writes the `.ALL` archive that `PLAYONE.EXE` plays ([`driving.md`](driving.md), container layout in [`../formats/all.ksy`](../formats/all.ksy)).
This note records where each chunk of that archive comes from, judged from the archives alone: which source file, which id, in what order, and which items a film gets.
It is the evidence for an archive writer of our own ([ADR 0023](../../docs/adr/0023-make-all-generates-archives-with-makeone.md) deferred one until the packaging was understood).

Method, for every section below: a throwaway script (not committed) parsed all 289 `.ALL` files in `corpus/siarchive/` and `corpus/stisldem/`, split every `.RES` and `.SMP` file in the full game's `corpus/stuntisl/RES\` into its segments by [`../formats/res.ksy`](../formats/res.ksy), and compared payloads by SHA-1, then by substring search for those with no match.
Run on 2026-11-03.
No `MAKEONE` run was involved; the corpus archives were made by their authors on their own machines.

---

## 1. Chunks Are Copies

`[Bounded Observation]`, 289 archives, 114,573 chunks.

| Class | Chunks | Where |
|---|---|---|
| Byte-identical to one segment of a shipped `.RES` or `.SMP` | 106,358 (92.8%) | Every id range in use |
| Matched nothing, not even as a substring of a game file | 8,215 | 3,117 below `0x8000`, 5,098 in `0xC000`-`0xCFFF` |
| A copy of the film's `.FLM`, or any payload starting `FILM` | 0 | |
| An id in `0x8100`-`0xBFFF` | 0 | |

Every unmatched chunk has an id whose high byte no shipped archive uses as its `res_index` (`0x1D`-`0x1F` beyond `FASTSPR`, `0x5B`-`0x7E`, `0xC8`-`0xCC`), apart from 117 under `0xC0`, 107 under `0xC1`, 387 under `0xC5` and 14 under `0xC3`.
The first group is the community's add-on shapes and sounds; the second is most likely sound data from other releases or add-on sound packs, unchecked.
No chunk is a transformed resource: when `MAKEONE` includes a shipped resource it copies it unchanged.

The two palette chunks, `0x801E` (50 bytes) and `0x8042` (722 bytes), are items `0x1E` and `0x42` of `SPRITES.RES`, whose `res_index` is `0x80`.
[`../formats/all.md`](../formats/all.md) gives 48 and 720 bytes, the 16 and 240 colour triples; each chunk holds 2 bytes more, not yet explained.
Every archive `make-all` stored for a reference film and the demo's `INTRO.ALL` and `SCENE01.ALL` hold both; the demo's shipped `CTRY.ALL` holds only `0x8042`.
The `GVPOLY` records once read as ground scene records in `CTRY.ALL` ([`../formats/all.md`](../formats/all.md) § 3.6) sit inside copied shape chunks.

## 2. The Chunk Id

`[Bounded Observation]`, every matched chunk.
A chunk's id is `(res_index << 8) | (segment + 1)`, where `res_index` is byte `0x0002` of the source archive and `segment` counts the data regions of [`res.ksy`](../formats/res.ksy) from 0, so the name-table region of a prop archive (region 0) is item 1 and its first payload (region 1) is item 2.
The few matches that break the rule are payloads stored twice in the game (the same bytes as an item of another archive), not a second rule.

## 3. Layout

`[Bounded Observation]`, 289 archives.
Ids are in ascending order in every archive.
The header is `6n + 6` bytes, the first payload starts right after it, and each payload follows the previous with no padding, so the offsets are the running sum of payload lengths.
`Films/MultiFLM/UFOAct2/BRIEFING.ALL`, already known to be truncated ([`../formats/all.md`](../formats/all.md) § 2.1), is the one archive this does not reproduce.

**Rebuild test.**
For each archive the script kept only its id list, fetched each payload from `RES\` by the rule of section 2, and packed the result as above.

| Archives | Count | Result |
|---|---|---|
| Only shipped resources | 83 | Byte-identical to the original |
| Holding add-on chunks | 205 | Not attempted; the add-on files were not looked for |
| `BRIEFING.ALL` | 1 | Its own header does not match its length, and it holds an add-on chunk (`0x1F01`) |

So an id list, the sound variant of section 5 and the game's `RES\` determine the archive exactly.

**The writer agrees.**
`stuntreel link extract` ([ADR 0032](../../docs/adr/0032-a-films-archive-is-committed-as-a-manifest.md)), run on 2026-11-03 over the same 289 archives with `corpus/stuntisl` as the game tree, wrote a manifest that rebuilds its archive byte for byte for the same 83, and exited 3 (not linkable) for the other 206: the 205 with add-on chunks and `BRIEFING.ALL`, whose `0x1F01` is reported before its truncation.
It also holds for an archive `make-all` wrote: `BALLOON.FLM`'s (46,702 bytes, 10 source files, no music chunk) extracts to `manifests/all/vault-balloon.toml`, the `--manifest-only` backfill writes the same file, and the archive `resolve_all` rebuilds from it into `target/linked/` hashes to the `all_sha256` of `MAKEONE`'s output.

## 4. Which Items a Film Gets

`[Bounded Observation]` for the counts; `[Supported Inference]` for the cause.

Items are chosen one by one.
No archive in the corpus holds every item of any source archive.
The share a film takes varies widely, most of all in scenery:

| Source | Films using it | Share of the archive's items: median (range) |
|---|---|---|
| `SCENERY1.RES`-`SCENERY6.RES` | 251 to 286 | 0.13 to 0.22 (0.00 to 0.90) |
| `FASTSPR.RES` | 207 | 0.17 (0.02 to 0.18) |
| `GAME.RES` | 202 | 0.24 (0.06 to 0.59) |
| `SPRITES.RES` | 289 | 0.02 (the two palettes, sometimes one more) |
| `ACTORS`, `MILITARY`, `MISCELLA`, `PLANES`, `STRUCTUR`, `VEHICLES`, `LETTERS`, `MARKERS`, `PRODTOOL` | 84 to 215 | 0.01 to 0.09 |

`CTRY.ALL` holds 135 chunks, 125 of them scenery; `INTRO.ALL` 282, 232 of them scenery.

The selection looks like the set of resources the renderer loaded while `MAKEONE` played the film:

- `MAKEONE` plays the whole film before it writes anything ([`driving.md`](driving.md) § 1).
- It shares `PLAYONE`'s rendering code, down to the level-of-detail site that swaps a far object for its stand-in ([`../playone-exe/lod.md`](../playone-exe/lod.md) § 1.2).
- It never opens a `.SET` ([`../stunt-exe/sets.md`](../stunt-exe/sets.md)), so it cannot read a set's scenery list directly.
- Patch #3, which changes level of detail, makes a different `BIGMAN.ALL` from the same film ([`../playone-exe/patch3.md`](../playone-exe/patch3.md) § 3).

If that holds, the scenery subset can be predicted only by reproducing the original's culling and level-of-detail choices over every frame.
Actor shapes and sounds can probably be read from the film statically; that is untested.

The question matters only for an archive `PLAYONE` must accept.
Our renderer does not need the selection: renders from every stock shape match renders from the film's own archive within noise, and the archive's one render effect is the prop filter of section 7.
`stuntreel --game` reads the shapes from `RES\` with no archive (section 7.1).

## 5. The Sound Setting

`[Bounded Observation]` for the sources; the link to `SETUP.BAT` is `[Supported Inference]` from community notes.

Some `res_index` values belong to several files, one per sound setting, and the archives disagree on which one they copied:

| Id high byte | Files | Archives' chunks from each |
|---|---|---|
| `0xC0` | `MUSIC1.XMA`, `.ESS`, `.XMM`, `.XMP` | 80, 64, 13, 10 |
| `0xC1` | `MUSIC2.XMA`, `.ESS`, `.XMP`, `.XMM` | 55, 35, 8, 7 |
| `0xC3` | `COMMNSND.SMP`, `COMMNSND.ZCR` | 300, 31 |

`MUSIC1.XMI` and `MUSIC2.XMI` exist but supplied no chunk.
A film usually holds one music chunk.
So `MAKEONE` copies the music and common sounds of the sound setting configured when it ran; shapes, palettes and scenery do not depend on it.
The community's `corpus/siarchive/Films/Playing_Films.txt` says the same from the player's side: a film archived with synthesized music plays without music in a `PLAYONE` set up for digital music.
Our own runs are byte-stable ([`driving.md`](driving.md) § 5) because the emulator configuration is fixed.

## 6. Archive Size in the Corpus

`[Bounded Observation]`.
The largest archives are `FLAGDAY1.ALL` (4,276,872 bytes, 1,066 chunks) and `ID5.ALL` (4,260,719 bytes); the most chunks are 1,151 (`SIDEM1S.ALL`, `SIDEM1D.ALL`).
`CTRY.ALL` is 135 chunks.
Whether `PLAYONE` plays an archive padded with chunks the film never asks for is untested; lookups are by id, so the extra chunks should only cost memory and load time.

## 7. A Superset Renders Like a Film's Own Archive

`[Bounded Observation]`, CTRY and INTRO, run 2026-11-06 at `48f5d49`.

Our renderer takes nothing from a `.ALL` but its shapes ([`scene/shapes.rs`](../../crates/stunt-core/src/scene/shapes.rs) `decode_archive_shapes`).
It builds the palette from film variables, and it reads the scenery, anchors and font from loose files.
So the item selection of section 4 matters to `PLAYONE`, not to us.
[`superset_all.py`](../../python/scripts/superset_all.py) (`mise run superset-all`) builds one archive holding every item of every `RES\` file with `res_index` below `0x80`: 17 files, 2,669 chunks, 4,193,452 bytes, about 1.28 MB with zstd -19.
Both demo archives are subsets of it: `stuntreel link extract` of `CTRY.ALL` and `INTRO.ALL` against `corpus/stuntisl` succeeds.

We rendered each film with its demo archive and again with the superset, then scored both against the reference captures:

| Film | Own archive SSIM / IoU / idx | Superset SSIM / IoU / idx |
|---|---|---|
| CTRY | 0.8725 / 0.9897 / 0.890 | 0.8726 / 0.9899 / 0.890 |
| INTRO | 0.8273 / 0.9856 / 0.830 | 0.8282 / 0.9856 / 0.831 |

Both films stay within the 0.002 noise floor.
The one thing the archive changes is which scenery props get placed.
`build_world` places a scenery leaf only when the archive holds its shape (`place_props` in [`world/scenery/mod.rs`](../../crates/stunt-core/src/world/scenery/mod.rs)).
With the superset, CTRY places 69 static props instead of 68 and INTRO 1,114 instead of 1,103.
That changes 125 of 1,343 CTRY frames and 440 of 3,823 INTRO frames, by at most 164 and 373 of 64,000 pixels.
`palettes.zst` is byte-identical.
The extra props are most likely ones that `PLAYONE`'s per-frame level of detail never loaded and our once-per-film path-distance level of detail keeps (`[Supported Inference]`).
Decoding 2,669 chunks instead of 127 or 250 adds about 0.2 s at startup.

### 7.1 Rendering Straight from `RES\`

`[Bounded Observation]`, CTRY, INTRO and BALLOON, run 2026-11-07 on `2e215fd` with `--game` added, in a cloud session on Mesa lavapipe (no GPU), so the scores below compare with each other, not with the GPU rows above.

`stuntreel --game <TREE>` takes the shapes from `<TREE>/RES/*.RES` in place of an archive.
[`link.rs`](../../crates/stunt-core/src/link.rs) `shape_chunks` keys every item of every file with `res_index` below `0x80` by the rule of section 2 and refuses two files with one index.
[`scene/shapes.rs`](../../crates/stunt-core/src/scene/shapes.rs) `decode_res_shapes` decodes them as `decode_archive_shapes` decodes an archive's chunks, keeping only the items an archive would name `MODEL_%04X.SOD`.
Both films were rendered whole with the demo archive and with `--game corpus/stuntisl`, then scored with `mise run parity -- --no-build --reuse`:

| Film | `--all` (demo archive) SSIM / IoU / idx | `--game` SSIM / IoU / idx |
|---|---|---|
| CTRY | 0.6609 / 0.9897 / 0.674 | 0.6610 / 0.9899 / 0.674 |
| INTRO | 0.6070 / 0.9856 / 0.613 | 0.6079 / 0.9857 / 0.614 |

`--game` loads the superset's 2,516 models and places its 69 and 1,114 props.
Against the `--all` render, 125 of 1,343 CTRY frames and 440 of 3,823 INTRO frames differ, by at most 164 and 377 pixels, and the actor layer is identical on every frame.

The full game ships its `VAULT` films with no archive.
`corpus/stuntisl/VAULT/BALLOON.FLM` renders with `--game` and no `make-all` run.
It draws actors on 997 of its 1,193 frames, with an actor layer identical on every frame to a render from the archive `make-all` wrote (`captures/vault-balloon/archives/BALLOON.ALL`, 58 models).
It places 25 static props against that archive's 18, and 139 frames differ by at most 6 pixels.

Cost on this machine (4 cores, lavapipe): a one-tick render starts in 0.44 to 0.51 s, against 0.08 to 0.12 s with the archive.
Whole films take about twice as long: CTRY 3.4 s to 5.3 s (one run each), INTRO 14.7 to 14.9 s to 28.4 to 28.9 s (two runs each).
The spike measured about 6% on INTRO on a GPU.
At that commit all 2,516 shapes were uploaded to the device, against 127 or 250 from an archive.

The film path now uploads only the shapes a film can draw: every slice's actor shapes, the view-facing props whatever their gates, and the origin shape (`FilmScene::drawn_only` in [`scene/film.rs`](../../crates/stunt-core/src/scene/film.rs)); baked props live in the world mesh.
`[Bounded Observation]`, 2026-11-13, `ce861b2b` against `3d680420`, `--game`, lavapipe on 16 threads shared with two GPU sweeps, so not comparable with the figures above: CTRY's and INTRO's `frames.zst`, `layers.zst` and `palettes.zst` are byte-identical (`render.json` and `preview/` not hashed).
Median one-tick renders (five runs) fall from 0.90 to 0.60 s on CTRY and from 2.24 to 1.48 s on INTRO, whose ranges overlap, against 0.29 and 0.49 s from the archive on `3d680420`.
One binary's whole-film runs of one film varied up to 2.2 times, too much to show a per-frame change.
_Source: [2026-11-13: dropping undrawn shapes before the upload](../../work/2026-11/484_upload-used-shapes/journal.md#2026-11-13-dropping-undrawn-shapes-before-the-upload)._

### 7.2 `PLAYONE` on a Superset

`[Bounded Observation]`, `CTRY.FLM` and `TOD.FLM` (`corpus/stuntisl/VAULT`), run 2026-11-09 at `4f5f8e59`.

`PLAYONE.EXE` played the superset in place of each film's own `make-all` archive, every archive with its sound chunks stubbed ([ADR 0043](../../docs/adr/0043-captures-play-with-the-archives-sound-samples-stubbed.md)) so that replays repeat.
`superset-all --with-palettes` adds the two palette items of section 1, `0x801E` and `0x8042` from `SPRITES.RES` (index 128), which the superset otherwise leaves out with every file of `res_index` `0x80` or more.
Without them the ground drew in purple and green (TOD, 2026-11-07); with them every paired page's palette is byte-equal to the own archive's.

Some pages still differ.
Two captures of the own archive agreed page for page on every row, and the superset does not.
Pages are paired by `film_tick` with `mise run capture-compare`:

| Film, build | Own against own | Own against superset: identical pages | Median, 90th percentile pixels differing |
|---|---|---|---|
| CTRY, unpatched | 121 of 121 | 72 of 112 | 0, 1,649 |
| CTRY, Patch 3 | 121 of 121 | 48 of 101 | 3, 1,186 |
| TOD, unpatched | 128 of 128 | 108 of 115 | 0, 0 |
| TOD, Patch 3 | 128 of 128 | 53 of 108 | 1, 934 |

A superset with no sound chunk at all plays bit for bit like one holding the own archive's sound ids as stubs, on the CTRY unpatched, CTRY Patch 3 and TOD unpatched rows; the TOD Patch 3 row has no `superset-bare` capture, so it does not test this.
Every other chunk of the own `CTRY.ALL` and `TOD.ALL` is in the superset byte for byte, so what the superset adds is the stock items these films' archives leave out, and size: 4,194,236 bytes against CTRY's 125,813.
Its captures also keep other ticks (CTRY 12, 134, 178 where the own archive's keep 14, 133, 177).
Some differing pages differ across the whole view (16 of CTRY unpatched's 40, up to 8,580 pixels), others by a few pixels in one spot.
The TOD Patch 3 row was added 2026-11-11: `MAKEONE` on Patch 3 had not finished `TOD.FLM` within 600 s on two attempts on 2026-11-09, but finished in 24 to 28 s on each of 4 reruns that evening, all writing the same `TOD.ALL`, so the stall did not recur in those 4 runs ([`driving.md`](driving.md) item 9).

_Source: [2026-11-09: the superset with palettes on CTRY and TOD](../../work/2026-11/301_superset-palettes-playone/journal.md#2026-11-09-the-superset-with-palettes-on-ctry-and-tod)._

**Not a timing shift.**
`capture-compare --shift 2` looks for each own page with no identical superset page at its tick among the superset's pages two ticks either side.
On the unpatched rows, none of CTRY's 40 differing pages nor TOD's 7 has an exact match there, and of the ticks only the own capture keeps, 1 of 9 (CTRY) and 2 of 13 (TOD) do.
So no differing superset page is a pixel-for-pixel copy of an own page from a tick within 2; what is drawn at a tick differs.

_Source: [2026-11-09: no differing page is a timing shift](../../work/2026-11/348_superset-pages/journal.md#2026-11-09-no-differing-page-is-a-timing-shift)._

**Padding does it too.**
`[Bounded Observation]`, `CTRY.FLM` and `TOD.FLM`, unpatched build, run 2026-11-09.
`mise run pad-all` added to each film's own archive either the superset's extra chunks (the props arm; stubbed as captures stage it, it is byte for byte the superset arm above, `e8110ffe…` and `bdee4cd7…`) or inert zero-filled chunks of the same count and bytes in ids `0xF001` upward, a `res_index` no game file uses (CTRY 2,529 chunks, 4,092,524 bytes; TOD 2,623, 4,138,716).
`PLAYONE` played both.
A second capture of the own, the props and (CTRY) the padded archive matched the first on every page; TOD's padded archive was captured once.
Palettes were byte-equal on every paired tick.

| Film | Own against props: identical pages | Own against padding | Props against padding |
|---|---|---|---|
| CTRY | 72 of 112 | 42 of 111 | 45 of 110 |
| TOD | 108 of 115 | 51 of 109 | 53 of 109 |

Padding that no film references changes more pages than the props, on both films, and as with the superset no differing page matches within 2 ticks.
So the props are not needed for the difference: what `PLAYONE` draws at a film tick depends on the archive beyond the chunks the film uses.
Total bytes and chunk count alone do not settle it, since props and padding share both and still draw differently from each other.

_Source: [2026-11-09: padding of the props' size changes pages more than the props](../../work/2026-11/348_superset-pages/journal.md#2026-11-09-padding-of-the-props-size-changes-pages-more-than-the-props)._

**No one property: pages change when the film runs later.**
`[Bounded Observation]`, `CTRY.FLM` (one arm on `TOD.FLM`), unpatched build, run 2026-11-16 at `03356d6e`.
Each arm added inert chunks to the own `CTRY.ALL` with `pad-all --inert`, varying one property; one capture each, against a fresh own capture (identical to #348's on all 121 pages) or, for ids and content, #348's padding.
The last column is the `emu_frame` of the page at film tick 1,333, the emulator frame it was drawn on.

| Added to own | Against | Identical pages | Last page drawn on frame |
|---|---|---|---|
| Nothing (recapture) | own | 121 of 121 | 3,139 |
| 1 chunk of 1 byte, id `0xF001` or `0x5B01` | own | 121 of 121 | 3,139 |
| 300 chunks of 1 byte | own | 121 of 121 | 3,139 |
| 1 chunk of 60,000 bytes | own | 121 of 121 | 3,139 |
| 63 chunks, 4,092,524 bytes | own | 61 of 110 | 3,144 |
| 2,529 chunks of 1 byte | own | 39 of 106 | 3,149 |
| Padding with ids from `0x5B01` (among the film's) | padding | 56 of 109 | 3,169 against 3,173 |
| Padding filled with `0xFF` | padding | 122 of 122 | 3,173 |
| TOD padding filled with `0xFF` | TOD padding | 129 of 129 | 3,279 |

- Content did not count: zero and `0xFF` fill drew alike on both films.
  Ids, varied alone, change pages; so do 2,529 chunks adding only 2.5 KB and 63 chunks adding 4 MB, each adding little of the other.
  So none of them is the property by itself; here a chunk weighs more than its bytes (2.5 KB in 2,529 chunks changed 67 pages, 4 MB in 63 chunks 49).
- How little is enough: 300 one-byte chunks and one 60,000-byte chunk change nothing, 2,529 and 63 chunks of 4 MB do; the thresholds between are bisected below.
- In these and #301's and #348's captures, every archive that changed pages drew its last page later than the own archive (props 3,167, padding 3,173).
  So the pages track how late the film runs, which grows with the chunks and bytes an archive adds.

That the archive's load time sets when the film starts against the emulator's frame clock, and so which ticks get drawn and what is drawn at them, is a `[Hypothesis]`: it rests on one film's captures; the start itself is timed below.

_Source: [2026-11-16: content does not count; chunk count, bytes and ids do once the film runs later](../../work/2026-11/482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later)._

**Where pages start to change: a whole film tick late.**
`[Bounded Observation]`, `CTRY.FLM`, unpatched build, 34 captures in a cloud session, run 2026-11-18.
The own `CTRY.ALL` plus `pad-all --inert` on two axes, ids from `0xF001`: 16 counts of one-byte chunks (300, 350, 362, 368, 375, 400, 450, 500, 550, 600, 900, 1,200, 1,500, 1,800, 2,100, 2,529) and 16 totals in 63 chunks (60,000, 100,000, 125,000, 131,250, 137,500, 150,000, 200,000, 275,000, 350,000, 425,000, 500,000, 750,000, 1,000,000, 2,000,000, 3,000,000 and 4,092,524 bytes); one capture each and two of the own archive, which matched each other on every page.
The four arms #482 also ran (300 and 2,529 chunks, 63 chunks of 60,000 and 4,092,524 bytes), rerun here, gave its identical-page counts and last-page frames; their pages were not compared with #482's local captures byte for byte.
The delay is the mean `emu_frame` offset of each capture's kept pages from the own capture's on shared ticks, in film ticks (70.086 emulator frames to 50 ticks).

| Delay | Arms | Last page drawn on frame | Identical pages with own |
|---|---|---|---|
| 0 | 300, 350, 362 one-byte chunks; 63 chunks of 60,000 to 131,250 bytes (4 totals) | 3,139 | 121 of 121 |
| 1 | 368 chunks; 63 chunks of 137,500 and 150,000 bytes | 3,141 | 39 of 103 |
| 1 | 375 to 600 chunks (6 counts); 63 chunks of 200,000 to 500,000 bytes (5 totals) | 3,141 | 36 of 104 |
| 2 | 900 chunks | 3,142 | 39 of 106 |
| 3 | 63 chunks of 750,000 to 4,092,524 bytes (5 totals) | 3,144 | 61 of 110 |
| 4 | 1,200 and 1,500 chunks | 3,145 | 37 of 106 |
| 5 | 1,800 chunks | 3,146 | 109 of 118 |
| 6 | 2,100 chunks | 3,148 | 36 of 107 |
| 7 | 2,529 chunks | 3,149 | 39 of 106 |

- Pages change between 362 and 368 one-byte chunks, and between 131,250 and 137,500 bytes in 63 chunks: the largest arms tried that leave them and the smallest that change them.
  Every capture's delay is within 0.04 of a whole number of film ticks, and every arm that changed pages is at least one tick late.
  In 63 chunks, 750,000 bytes and 4,092,524 bytes are both 3 ticks late, as are the three sizes tried between.
- The steps are film ticks of 20 ms, 1.40 frames, not frames: the last page moves 2, 3, 5, 6, 7, 9 and 10 frames for delays of 1 to 7 ticks.
- Two captures drew identical pages on every shared tick exactly when every kept page fell on the same emulator frame: the 105 pairs within the table's 9 rows do, none of the 456 pairs across rows does.
  The last page's frame alone does not decide it: the two 1-tick rows share it and differ in 29 of 113 pages.
- Those two rows draw 111 of their 113 shared ticks on the same frame, and 27 of the 29 differing pages are drawn at the same tick on the same frame; where they differ is which ticks were drawn, 8 of them one tick apart (12, 89, 145 … against 13, 90, 144 …).
  So what is drawn at a tick is not fixed by the tick and the frame it is drawn on; that it carries state from the frames drawn before is a `[Hypothesis]`: the probe's sweep from the previous frame is ruled out, and on #348's padded archive 12 of the 23 viewpoint pages show the scene a tick from the own archive's at one tag.
  The 5 peaked pairs with equal HUD clocks are consistent with a varying lag, and the camera's eye and angles matched at the common film-step ticks of two DOSBox-X runs.
  The propeller remains ([`film-load.md`](../playone-exe/film-load.md) section 5).
- Rows 5 ticks apart, 7.009 frames, share 79 to 110 pages of 111 to 118; other pairs of rows share 36 to 61 of 100 to 111, except the two 1-tick rows, 84 of 113.
  That what is drawn follows the film clock's phase against the 70 Hz frame, and that the clock starts whole timer ticks later as the load grows ([`film-load.md`](../playone-exe/film-load.md) section 4), are `[Hypothesis]`: the delays are read from kept pages, not from a log of the clock's start.

_Source: [2026-11-18: pages change once the film runs a whole film tick late](../../work/2026-11/611_padding-threshold/journal.md#2026-11-18-pages-change-once-the-film-runs-a-whole-film-tick-late)._

The code fits it in part: `PLAYONE` passes every chunk of the archive through its chunk cache before the film starts, each chunk costing a scan of the id table that grows with the chunk count, and the film clock counts from the first timer tick after the load ([`film-load.md`](../playone-exe/film-load.md) sections 1 to 4, read statically).
The CPU work it counts does not account for the 63-chunk 4 MB arm, and why a later start changes what is drawn at a tick is still open there.

_Source: [the loader preloads every chunk](../../work/2026-11/609_archive-load-start/journal.md#2026-11-18-the-loader-preloads-every-chunk-and-the-film-clock-starts-on-the-next-timer-tick)._

**The start moves by whole timer ticks.**
`[Bounded Observation]`, `CTRY.FLM`, unpatched build, the own archive and nine padded arms (those above and #348's padding), logged per emulator frame on dosbox-automation, 2026-11-18.
The arms that draw the own archive's pages start the film clock on the same timer interrupt; each that draws differently starts 3 to 24 interrupts later, and its last page falls as many ticks later, to within one frame ([`film-load.md`](../playone-exe/film-load.md) § 6).

_Source: [archives that draw alike start the film clock on the same timer interrupt](../../work/2026-11/722_playone-start-timer-tick/journal.md#2026-11-18-archives-that-draw-alike-start-the-film-clock-on-the-same-timer-interrupt)._

---

## Ruled out

- **Transformed chunks.**
  Every chunk from a shipped archive is a byte-identical copy (section 1); none is generated or re-encoded.
- **The film inside its archive.**
  No chunk is the `.FLM` or starts `FILM` (section 1), although [`../formats/all.md`](../formats/all.md) § 3.1 allows for one.
- **Whole archives as the unit of selection.**
  No film takes all the items of any source archive (section 4).
- **Our renderer needing a film's own selection.**
  A superset of every stock shape scores within noise of the film's own archive on CTRY and INTRO, as an archive on a GPU (section 7) and read straight from `RES\` on lavapipe (section 7.1).
  The selection's one render effect is the `available_models` prop filter.
- **A missing sound chunk as the cause of `PLAYONE`'s superset differences.**
  The superset plays alike with and without the own archive's sound ids as stubs (section 7.2).
- **A timing shift as the cause of `PLAYONE`'s superset differences.**
  No differing page matches the other archive's page within 2 film ticks (section 7.2; [journal](../../work/2026-11/348_superset-pages/journal.md#2026-11-09-no-differing-page-is-a-timing-shift)).
- **The extra props as a necessary cause of `PLAYONE`'s superset differences.**
  Inert padding of the same count and bytes also changes pages, more of them (section 7.2; [journal](../../work/2026-11/348_superset-pages/journal.md#2026-11-09-padding-of-the-props-size-changes-pages-more-than-the-props)).
- **Chunk content as a cause of `PLAYONE`'s padded-archive differences.**
  Padding filled with `0xFF` draws every page as zero padding does, on CTRY and TOD; only these two fills were tried (section 7.2; [journal](../../work/2026-11/482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later)).
- **A single archive property (chunk count, bytes or ids) deciding the pages.**
  Ids change pages varied alone, and many tiny chunks or a few large ones each do while adding little of the other; what tracks the pages is how late the film's frames fall (section 7.2; [journal](../../work/2026-11/482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later)).
- **Any extra chunk changing `PLAYONE`'s pages.**
  One chunk of 1 or 60,000 bytes, 300, 350 or 362 one-byte chunks, or 63 chunks of 60,000, 100,000, 125,000 or 131,250 bytes leave every CTRY page as it was; these are the only small arms tried (section 7.2; [#482's journal](../../work/2026-11/482_archive-property-pages/journal.md#2026-11-16-content-does-not-count-chunk-count-bytes-and-ids-do-once-the-film-runs-later), [#611's](../../work/2026-11/611_padding-threshold/journal.md#2026-11-18-pages-change-once-the-film-runs-a-whole-film-tick-late)).
- **The last page's emulator frame as what decides whether two archives draw alike.**
  Two CTRY archives whose last page falls on the same frame, both a film tick late, differ in 29 of 113 pages; what matched in 34 captures is the frame of every kept page (section 7.2; [journal](../../work/2026-11/611_padding-threshold/journal.md#2026-11-18-pages-change-once-the-film-runs-a-whole-film-tick-late)).
- **One-frame steps in how late the film runs.**
  CTRY's pages fall late by whole film ticks, 1.40 frames each, and the last page never moved by 1 frame (section 7.2; [journal](../../work/2026-11/611_padding-threshold/journal.md#2026-11-18-pages-change-once-the-film-runs-a-whole-film-tick-late)).
- **The film tick and the frame it is drawn on fixing what `PLAYONE` draws.**
  27 CTRY pages differ between two archives that draw them at the same tick on the same frame (section 7.2; [journal](../../work/2026-11/611_padding-threshold/journal.md#2026-11-18-pages-change-once-the-film-runs-a-whole-film-tick-late)).
- **Patch #3 changing a shape file.**
  Of `RES\`, Patch #3 changes only `SPRITES.RES` and four sound files, and both builds' supersets are byte-identical (open question 4).

## Open questions

1. Is the selection the set of resources loaded during playback?
   Comparing the scenery ids of `CTRY.ALL` and `INTRO.ALL` with the shapes our renderer draws, or finding where `MAKEONE` marks a resource as used, would settle it.
   Section 7 is a first step: the superset adds 1 and 11 props that the archives leave out, consistent with level-of-detail selection.
   Our renders do not depend on the answer: they match the film's own archive within noise without it (sections 7 and 7.1).
2. Can a film's actor shapes, sounds and the fixed items (palettes, `FASTSPR`, `GAME` sprites) be listed from the `.FLM` alone?
3. Which sound setting matches each music extension (`.ESS`, `.XMA`, `.XMM`, `.XMP`, `.XMI`), and does the setting change which ids are included or only their source?
   `BALLOON`'s archive from our fixed emulator profile has no music chunk at all.
4. Patch #3 changes five files of `RES\`: `SPRITES.RES` (it drops item `0x54`, 9,398 bytes, so the unpatched `0x55` is Patch #3's `0x54`; the other 83 items are unchanged), `COMMNSND.SMP`, `SNDFX2.SMP`, `MUSIC1.ESS` and `MUSIC2.ESS`.
   No shape file changes, and the two builds' `make-all` archives of `CTRY.FLM` differ only in sound chunk `0xC56A` (section 7.2).
   Open: what the changed sound files and the dropped item hold, and whether the selection differs for any film.
5. Up to what size does `PLAYONE` play an archive padded with unused chunks?
   It played own archives padded to about 4.2 MB with some 2,500 to 2,600 inert chunks in ids `0xF001` or `0x5B01` upward (section 7.2), drawing some pages differently; larger archives are untested.
   The id index shares 10,000 bytes with the cache nodes, so an archive whose index needs more than that overruns it ([`film-load.md`](../playone-exe/film-load.md) section 2).
6. Do the 205 archives with add-on chunks rebuild once their add-on `.RES` files are found?
7. What is left of `--game`'s extra cost now that only drawn shapes are uploaded (section 7.1)?
   Median one-tick renders still take about 0.3 s (CTRY) and 1.0 s (INTRO) longer than from an archive timed on the earlier commit, possibly from decoding all 2,516 shapes, untested.
   Decoding only the ids a film references is harder, since the scenery walk decides its props from the whole set.
   A per-frame cost needs whole-film timings on an unloaded machine.
8. Why does a larger archive change what `PLAYONE` draws at a film tick (section 7.2)?
   Narrowed by [#482](https://github.com/neilsh/stunt-reel/issues/482): no single property decides it and content does not count; pages changed when the film's frames fell later, which more chunks, more bytes or other ids bring about once they add enough; [#611](https://github.com/neilsh/stunt-reel/issues/611) found the smallest arms tried that do it on CTRY, 368 one-byte chunks and 137,500 bytes in 63 chunks, each a whole film tick late, and pages that differ at the same tick on the same frame.
   [#609](https://github.com/neilsh/stunt-reel/issues/609) read the loader: every chunk is preloaded, at a per-chunk cost, and the film clock starts on the first timer tick after the load ([`film-load.md`](../playone-exe/film-load.md)).
   Open there: whether that tick is the quantum, what is stepped per drawn frame, and why the 63-chunk 4 MB arm starts later; a live log of the global tick `DS:0x22B8` and the emulator frame at the film clock's start would test the load-time inference.

_Found 2026-11-03; see the [parity log](../../work/2026-10/parity-log/log.md)._
