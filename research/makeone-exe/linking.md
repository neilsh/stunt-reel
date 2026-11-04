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

The two palette chunks, `0x801E` (48 bytes) and `0x8042` (720 bytes), are items `0x1E` and `0x42` of `SPRITES.RES`, whose `res_index` is `0x80`. The ground scene records found in `CTRY.ALL` ([`../formats/all.md`](../formats/all.md) § 3.6) sit inside copied shape chunks.

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

---

## Ruled out

- **Transformed chunks.** Every chunk from a shipped archive is a byte-identical copy (section 1); none is generated or re-encoded.
- **The film inside its archive.** No chunk is the `.FLM` or starts `FILM` (section 1), although [`../formats/all.md`](../formats/all.md) § 3.1 allows for one.
- **Whole archives as the unit of selection.** No film takes all the items of any source archive (section 4).

## Open questions

1. Is the selection the set of resources loaded during playback? Comparing the scenery ids of `CTRY.ALL` and `INTRO.ALL` with the shapes our renderer draws, or finding where `MAKEONE` marks a resource as used, would settle it.
2. Can a film's actor shapes, sounds and the fixed items (palettes, `FASTSPR`, `GAME` sprites) be listed from the `.FLM` alone?
3. Which sound setting matches each music extension (`.ESS`, `.XMA`, `.XMM`, `.XMP`, `.XMI`), and does the setting change which ids are included or only their source? `BALLOON`'s archive from our fixed emulator profile has no music chunk at all.
4. Does Patch #3 change any file in `RES\`, or only the selection?
5. Does `PLAYONE` play an archive padded with unused chunks, and up to what size?
6. Do the 205 archives with add-on chunks rebuild once their add-on `.RES` files are found?

_Found 2026-11-03; see the [parity log](../parity/log.md)._
