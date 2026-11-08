---
summary: "A film's `.ALL` copies stock items verbatim, id-ordered by `(res_index << 8) | (segment + 1)`, music and common sounds by sound setting; stock shapes draw CTRY, INTRO and BALLOON like their archives."
---
# `MAKEONE.EXE`: What the Film Linker Puts in a `.ALL`

`MAKEONE.EXE` writes the `.ALL` archive that `PLAYONE.EXE` plays ([`driving.md`](driving.md), container layout in [`../formats/all.ksy`](../formats/all.ksy)). This note records where each chunk of that archive comes from, judged from the archives alone: which source file, which id, in what order, and which items a film gets. It is the evidence for an archive writer of our own ([ADR 0023](../../docs/adr/0023-make-all-generates-archives-with-makeone.md) deferred one until the packaging was understood).

Method, for every section below: a throwaway script (not committed) parsed all 289 `.ALL` files in `corpus/siarchive/` and `corpus/stisldem/`, split every `.RES` and `.SMP` file in the full game's `corpus/stuntisl/RES\` into its segments by [`../formats/res.ksy`](../formats/res.ksy), and compared payloads by SHA-1, then by substring search for those with no match. Run on 2026-11-03. No `MAKEONE` run was involved; the corpus archives were made by their authors on their own machines.

---

## 1. Chunks Are Copies

`[Bounded Observation]`, 289 archives, 114,573 chunks.

| Class | Chunks | Where |
|---|---|---|
| Byte-identical to one segment of a shipped `.RES` or `.SMP` | 106,358 (92.8%) | Every id range in use |
| Matched nothing, not even as a substring of a game file | 8,215 | 3,117 below `0x8000`, 5,098 in `0xC000`-`0xCFFF` |
| A copy of the film's `.FLM`, or any payload starting `FILM` | 0 | |
| An id in `0x8100`-`0xBFFF` | 0 | |

Every unmatched chunk has an id whose high byte no shipped archive uses as its `res_index` (`0x1D`-`0x1F` beyond `FASTSPR`, `0x5B`-`0x7E`, `0xC8`-`0xCC`), apart from 117 under `0xC0`, 107 under `0xC1`, 387 under `0xC5` and 14 under `0xC3`. The first group is the community's add-on shapes and sounds; the second is most likely sound data from other releases or add-on sound packs, unchecked. No chunk is a transformed resource: when `MAKEONE` includes a shipped resource it copies it unchanged.

The two palette chunks, `0x801E` (48 bytes) and `0x8042` (720 bytes), are items `0x1E` and `0x42` of `SPRITES.RES`, whose `res_index` is `0x80`. The `GVPOLY` records once read as ground scene records in `CTRY.ALL` ([`../formats/all.md`](../formats/all.md) § 3.6) sit inside copied shape chunks.

## 2. The Chunk Id

`[Bounded Observation]`, every matched chunk. A chunk's id is `(res_index << 8) | (segment + 1)`, where `res_index` is byte `0x0002` of the source archive and `segment` counts the data regions of [`res.ksy`](../formats/res.ksy) from 0, so the name-table region of a prop archive (region 0) is item 1 and its first payload (region 1) is item 2. The few matches that break the rule are payloads stored twice in the game (the same bytes as an item of another archive), not a second rule.

## 3. Layout

`[Bounded Observation]`, 289 archives. Ids are in ascending order in every archive. The header is `6n + 6` bytes, the first payload starts right after it, and each payload follows the previous with no padding, so the offsets are the running sum of payload lengths. `Films/MultiFLM/UFOAct2/BRIEFING.ALL`, already known to be truncated ([`../formats/all.md`](../formats/all.md) § 2.1), is the one archive this does not reproduce.

**Rebuild test.** For each archive the script kept only its id list, fetched each payload from `RES\` by the rule of section 2, and packed the result as above.

| Archives | Count | Result |
|---|---|---|
| Only shipped resources | 83 | Byte-identical to the original |
| Holding add-on chunks | 205 | Not attempted; the add-on files were not looked for |
| `BRIEFING.ALL` | 1 | Its own header does not match its length, and it holds an add-on chunk (`0x1F01`) |

So an id list, the sound variant of section 5 and the game's `RES\` determine the archive exactly.

**The writer agrees.** `stuntreel link extract` ([ADR 0032](../../docs/adr/0032-a-films-archive-is-committed-as-a-manifest.md)), run on 2026-11-03 over the same 289 archives with `corpus/stuntisl` as the game tree, wrote a manifest that rebuilds its archive byte for byte for the same 83, and exited 3 (not linkable) for the other 206: the 205 with add-on chunks and `BRIEFING.ALL`, whose `0x1F01` is reported before its truncation. It also holds for an archive `make-all` wrote: `BALLOON.FLM`'s (46,702 bytes, 10 source files, no music chunk) extracts to `manifests/all/vault-balloon.toml`, the `--manifest-only` backfill writes the same file, and the archive `resolve_all` rebuilds from it into `target/linked/` hashes to the `all_sha256` of `MAKEONE`'s output.

## 4. Which Items a Film Gets

`[Bounded Observation]` for the counts; `[Supported Inference]` for the cause.

Items are chosen one by one. No archive in the corpus holds every item of any source archive. The share a film takes varies widely, most of all in scenery:

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

If that holds, the scenery subset can be predicted only by reproducing the original's culling and level-of-detail choices over every frame. Actor shapes and sounds can probably be read from the film statically; that is untested.

The question matters only for an archive `PLAYONE` must accept. Our renderer does not need the selection: renders from every stock shape match renders from the film's own archive within noise, and the archive's one render effect is the prop filter of section 7. `stuntreel --game` reads the shapes from `RES\` with no archive (section 7.1).

## 5. The Sound Setting

`[Bounded Observation]` for the sources; the link to `SETUP.BAT` is `[Supported Inference]` from community notes.

Some `res_index` values belong to several files, one per sound setting, and the archives disagree on which one they copied:

| Id high byte | Files | Archives' chunks from each |
|---|---|---|
| `0xC0` | `MUSIC1.XMA`, `.ESS`, `.XMM`, `.XMP` | 80, 64, 13, 10 |
| `0xC1` | `MUSIC2.XMA`, `.ESS`, `.XMP`, `.XMM` | 55, 35, 8, 7 |
| `0xC3` | `COMMNSND.SMP`, `COMMNSND.ZCR` | 300, 31 |

`MUSIC1.XMI` and `MUSIC2.XMI` exist but supplied no chunk. A film usually holds one music chunk. So `MAKEONE` copies the music and common sounds of the sound setting configured when it ran; shapes, palettes and scenery do not depend on it. The community's `corpus/siarchive/Films/Playing_Films.txt` says the same from the player's side: a film archived with synthesized music plays without music in a `PLAYONE` set up for digital music. Our own runs are byte-stable ([`driving.md`](driving.md) § 5) because the emulator configuration is fixed.

## 6. Archive Size in the Corpus

`[Bounded Observation]`. The largest archives are `FLAGDAY1.ALL` (4,276,872 bytes, 1,066 chunks) and `ID5.ALL` (4,260,719 bytes); the most chunks are 1,151 (`SIDEM1S.ALL`, `SIDEM1D.ALL`). `CTRY.ALL` is 135 chunks. Whether `PLAYONE` plays an archive padded with chunks the film never asks for is untested; lookups are by id, so the extra chunks should only cost memory and load time.

## 7. A Superset Renders Like a Film's Own Archive

`[Bounded Observation]`, CTRY and INTRO, run 2026-11-06 at `48f5d49`.

Our renderer takes nothing from a `.ALL` but its shapes ([`scene.rs`](../../crates/stunt-core/src/scene.rs) `decode_archive_shapes`). It builds the palette from film variables, and it reads the scenery, anchors and font from loose files. So the item selection of section 4 matters to `PLAYONE`, not to us. [`superset_all.py`](../../python/scripts/superset_all.py) (`mise run superset-all`) builds one archive holding every item of every `RES\` file with `res_index` below `0x80`: 17 files, 2,669 chunks, 4,193,452 bytes, about 1.28 MB with zstd -19. Both demo archives are subsets of it: `stuntreel link extract` of `CTRY.ALL` and `INTRO.ALL` against `corpus/stuntisl` succeeds.

We rendered each film with its demo archive and again with the superset, then scored both against the reference captures:

| Film | Own archive SSIM / IoU / idx | Superset SSIM / IoU / idx |
|---|---|---|
| CTRY | 0.8725 / 0.9897 / 0.890 | 0.8726 / 0.9899 / 0.890 |
| INTRO | 0.8273 / 0.9856 / 0.830 | 0.8282 / 0.9856 / 0.831 |

Both films stay within the 0.002 noise floor. The one thing the archive changes is which scenery props get placed. `build_world` places a scenery leaf only when the archive holds its shape (`available_models` in [`world.rs`](../../crates/stunt-core/src/world.rs)). With the superset, CTRY places 69 static props instead of 68 and INTRO 1,114 instead of 1,103. That changes 125 of 1,343 CTRY frames and 440 of 3,823 INTRO frames, by at most 164 and 373 of 64,000 pixels. `palettes.zst` is byte-identical. The extra props are most likely ones that `PLAYONE`'s per-frame level of detail never loaded and our once-per-film path-distance level of detail keeps (`[Supported Inference]`). Decoding 2,669 chunks instead of 127 or 250 adds about 0.2 s at startup.

### 7.1 Rendering Straight from `RES\`

`[Bounded Observation]`, CTRY, INTRO and BALLOON, run 2026-11-07 on `2e215fd` with `--game` added, in a cloud session on Mesa lavapipe (no GPU), so the scores below compare with each other, not with the GPU rows above.

`stuntreel --game <TREE>` takes the shapes from `<TREE>/RES/*.RES` in place of an archive. [`link.rs`](../../crates/stunt-core/src/link.rs) `shape_chunks` keys every item of every file with `res_index` below `0x80` by the rule of section 2 and refuses two files with one index. [`scene.rs`](../../crates/stunt-core/src/scene.rs) `decode_res_shapes` decodes them as `decode_archive_shapes` decodes an archive's chunks, keeping only the items an archive would name `MODEL_%04X.SOD`. Both films were rendered whole with the demo archive and with `--game corpus/stuntisl`, then scored with `mise run parity -- --no-build --reuse`:

| Film | `--all` (demo archive) SSIM / IoU / idx | `--game` SSIM / IoU / idx |
|---|---|---|
| CTRY | 0.6609 / 0.9897 / 0.674 | 0.6610 / 0.9899 / 0.674 |
| INTRO | 0.6070 / 0.9856 / 0.613 | 0.6079 / 0.9857 / 0.614 |

`--game` loads the superset's 2,516 models and places its 69 and 1,114 props. Against the `--all` render, 125 of 1,343 CTRY frames and 440 of 3,823 INTRO frames differ, by at most 164 and 377 pixels, and the actor layer is identical on every frame.

The full game ships its `VAULT` films with no archive. `corpus/stuntisl/VAULT/BALLOON.FLM` renders with `--game` and no `make-all` run. It draws actors on 997 of its 1,193 frames, with an actor layer identical on every frame to a render from the archive `make-all` wrote (`captures/vault-balloon/archives/BALLOON.ALL`, 58 models). It places 25 static props against that archive's 18, and 139 frames differ by at most 6 pixels.

Cost on this machine (4 cores, lavapipe): a one-tick render starts in 0.44 to 0.51 s, against 0.08 to 0.12 s with the archive. Whole films take about twice as long: CTRY 3.4 s to 5.3 s (one run each), INTRO 14.7 to 14.9 s to 28.4 to 28.9 s (two runs each). The spike measured about 6% on INTRO on a GPU. All 2,516 shapes are uploaded to the device, against 127 or 250, which is a likely cause of the per-frame cost on lavapipe but is untested.

---

## Ruled out

- **Transformed chunks.** Every chunk from a shipped archive is a byte-identical copy (section 1); none is generated or re-encoded.
- **The film inside its archive.** No chunk is the `.FLM` or starts `FILM` (section 1), although [`../formats/all.md`](../formats/all.md) § 3.1 allows for one.
- **Whole archives as the unit of selection.** No film takes all the items of any source archive (section 4).
- **Our renderer needing a film's own selection.** A superset of every stock shape scores within noise of the film's own archive on CTRY and INTRO, as an archive on a GPU (section 7) and read straight from `RES\` on lavapipe (section 7.1). The selection's one render effect is the `available_models` prop filter.

## Open questions

1. Is the selection the set of resources loaded during playback? Comparing the scenery ids of `CTRY.ALL` and `INTRO.ALL` with the shapes our renderer draws, or finding where `MAKEONE` marks a resource as used, would settle it. Section 7 is a first step: the superset adds 1 and 11 props that the archives leave out, consistent with level-of-detail selection. Our renders do not depend on the answer: they match the film's own archive within noise without it (sections 7 and 7.1).
2. Can a film's actor shapes, sounds and the fixed items (palettes, `FASTSPR`, `GAME` sprites) be listed from the `.FLM` alone?
3. Which sound setting matches each music extension (`.ESS`, `.XMA`, `.XMM`, `.XMP`, `.XMI`), and does the setting change which ids are included or only their source? `BALLOON`'s archive from our fixed emulator profile has no music chunk at all.
4. Does Patch #3 change any file in `RES\`, or only the selection?
5. Does `PLAYONE` play an archive padded with unused chunks, and up to what size?
6. Do the 205 archives with add-on chunks rebuild once their add-on `.RES` files are found?
7. Does `--game` cost less if the scene keeps only the shapes a film draws? Its startup decodes all 2,516 shapes, and its renders take about twice as long on lavapipe (section 7.1). After `build_world`, only the actors' shape ids are still needed, so dropping the rest before the device upload would test the cause. Decoding only the ids a film references is harder, since the scenery walk decides its props from the whole set.

_Found 2026-11-03; see the [parity log](../../work/2026-10/parity-log/log.md)._
