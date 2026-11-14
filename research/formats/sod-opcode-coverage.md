---
summary: "Census work queue for Partial SOD shapes: `OP_ANIMATE` is drawn as sprites since #222 (the census no longer stops on it); two-vertex polygons, which stopped 7 more, are now drawn as lines; the films placing them, why seven side-view items export no whole model, and regeneration."
---
# `.SOD` Opcode Coverage: Blocking-Opcode Work Queue

* **Evidence**: corpus census of every compiled `.SOD` model in `corpus/` (`.ALL` and `.RES` archive entries and loose `.BIN` files), walked by the census mode of the evaluator in [`crates/stunt-core/src/sod/vm.rs`](../../crates/stunt-core/src/sod/vm.rs) (`walk_sod`), and joined to the films that place each shape.
* **Scope**: which shapes are Partial SODs, their blocking opcode, the masked opcodes behind it, the films that use them, and the order to implement the opcodes in. Terms follow [`GLOSSARY.md`](../../GLOSSARY.md).
* **Tier**: `[Bounded Observation]` throughout (see § 4).
* **Owns**: the implementation queue for unhandled `.SOD` opcodes. Opcode semantics and operands stay in [`sod-opcodes.md` § 1](sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes); binary evidence stays in [`playone-exe/`](../playone-exe/).

§ 3 is the output of `mise run sod-census -- --format markdown` (§ 5). A first census was hand-run on 2026-10-23 with a throwaway hook in `vm.rs`; § 3.1 records where the tool's output differs from it.

---

## 1. Summary

The census of 2026-11-12 (on `main` at `dbfd0ed4`, after [#222](https://github.com/neilsh/stunt-reel/issues/222) draws `OP_ANIMATE` and [#393](https://github.com/neilsh/stunt-reel/issues/393) draws two-vertex polygons) walks 331 archives. Of the 3,432 unique `MODEL_%04X.SOD` chunks, 3,418 walk to `OP_RETURN` with nothing stepped over (3,391 on 2026-11-01, 3,368 on 2026-10-24) and 14 stop only at `OP_TAP` because the census supplies no anchor table (a census artefact, not a gap). Groups B to J of the 2026-10-24 census are gone. What is left:

| Opcode or stop | Mnemonic | Seen as |
| :---: | :--- | :--- |
| `0x01F8` | `OP_ANIMATE` | handled since [#222](https://github.com/neilsh/stunt-reel/issues/222): emitted as sprites, and the census no longer steps over it (the census reports no unimplemented opcode for them now; the 28 group A models came from the census before #222) |
| `0x00F3`, `0x0168`, `0x02BE` | `OP_POLYZ`, `OP_GVPOLY`, `OP_GVPOLY16` with two vertices | drawn as a line since [#393](https://github.com/neilsh/stunt-reel/issues/393); a count below two still stops (none on the paths the census walks) |
| `0x0333` | `OP_TEXTURE` | ends the walk (loose `TESTTEXT.BIN` only; the opcode table gives no width) |
| `0x022E` | `OP_TAP` | blocking without anchors; implemented, see [`sod-vm.md`](../playone-exe/sod-vm.md) |

Groups B to D of the 2026-11-01 census were the two-vertex polygons, which sit in `SORTON` subtrees past the first `RETURN`. `PLAYONE` has no count test and, read statically, draws such a polygon as a thin line ([`sod-vm.md` § 8.9](../playone-exe/sod-vm.md#89-polygons-of-two-vertices), `[Supported Inference]`). `vm.rs` now draws them as a line too, so all seven models of those groups (`7E09`, `7E0C`, `7E1F`, `7E48`, `7F24`, `7F34`, `7F35` and the loose `PIPER`/`SHUTTLE` copies) walk to `RETURN` and the census lists none of them. A polygon of fewer than two vertices still stops (`SodStopReason::MalformedPolygon`); `PLAYONE` would read past the stream for it, and the census finds none on the paths it walks (it does not walk the other arm of each `BVGT`, § 4).

---

## 2. Work Queue

| # | Implement | Unblocks (shape IDs) | Film use | Evidence for semantics |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `OP_ANIMATE` (done, [#222](https://github.com/neilsh/stunt-reel/issues/222), [#408](https://github.com/neilsh/stunt-reel/issues/408)) | none; the census walks past it | 191 paired films (census before #222); `0105`–`010C` and `3A80` each in 39–130, including `INTRO.FLM` and `CTRY.FLM` (`0107`) | `[Established]` dispatch, frame selection (`0x16` / `0x10`) and blit, [`sod-animate.md`](../playone-exe/sod-animate.md) |

The handlers added on 2026-11-01 are community readings (FreeFlight `siobj.cpp`, si-tools) or `[Hypothesis]` (`SHADE`, [`sod-vm.md` § 8.5](../playone-exe/sod-vm.md#85-polygon-colour-at-shade-time)); the animation variables `ROT*` and `BVGT` read are zero (a resting pose), so articulated parts draw at rest.

### 2.1 The side-view census: shapes that do not decode whole

`[Bounded Observation]`: seven items of `SUPERSET.ALL` (`mise run superset-all`) exported a fragment or no geometry from `stuntreel export-gltf` when the census was taken; since #393 (`0x7F24`, `0x7F34`) and #392 (`0x07C6`) draw whole models, four remain with no `export-gltf` mesh geometry (`0x010D` and `0x3A80` emit sprites only, which `export-gltf` skips; `0x3C01` and `0x7F4B` are not shapes). `stuntreel sod-trace --archive SUPERSET.ALL --shape 0xNNNN` prints each walk. Film counts are from the 2026-11-01 census (§ 3) and, for shapes it does not list, from a one-off print over the 22 films of one machine's corpus, so they are lower bounds.

| Shape | Source | Stops at | Cause | Films placing it |
| :---: | :--- | :--- | :--- | :--- |
| `0x7F24` | `PLANES.RES` item `0x24` | was `0x10A0`, `POLYZ` of two vertices | `vm.rs` stopped on `count < 3`; fixed in [#393](https://github.com/neilsh/stunt-reel/issues/393), now a whole model (below) | 6 (2026-11-01 census; lower bound): `DPLANES`, `DRUGLORD`, `JURASSIC`, `PITTJET1`, `PLANES`, `SPLANES` |
| `0x7F34` | `PLANES.RES` item `0x34` | was `0x0F86`, `GVPOLY16` of two vertices | as `0x7F24` | 5 (2026-11-01 census; lower bound): `COWS`, `END3`, `FLAGDAY1`, `ID5`, `SFAPROMO` |
| `0x010D` | `GAME.RES` item `0x0D` | none: walks to `RETURN` (was `0x0058`, `OP_ANIMATE` `0x01F8`) | emits sprites only since #222 (`export-gltf` skips sprites; previously stopped at `OP_ANIMATE`); byte-identical to `0x3A80`; [`sod-animate.md`](../playone-exe/sod-animate.md) | none seen in the 22 local films; the census does not list it |
| `0x3A80` | `PRODTOOL.RES` item `0x80` | none: walks to `RETURN` (was `0x0058`, `OP_ANIMATE`) | as `0x010D`; was group A | 114 (census before #222; not listed now) |
| `0x07C6` | `SCENERY6.RES` item `0xC6` | none: walks to `RETURN` | was empty before [#392](https://github.com/neilsh/stunt-reel/issues/392): its only drawing opcode is `OP_PERFDISK` (`0x000C 0x2400 0x0000`), now drawn by `vm.rs` as a two-sided 16-gon disc ([`sod-vm.md` § 8.8](../playone-exe/sod-vm.md#88-model-frame-the-other-generators)) | none seen in the 22 local films; the census lists film use only for blocked models |
| `0x3C01` | `LETTERS.RES` item 1 (`SUPERSET.ALL` holds it as chunk id `0x3C01`, named `RES_3C01.BIN`) | not a shape | the chunk does not start with `0x000C`, so it is no `.SOD`; its bytes begin `Letters and Numbers` and then 16-bit values (`0x0021`, `0x0023`, `0x0024`, ...), read as a name and character-code table (`[Hypothesis]`) | none seen in the 22 local films; the census does not list it |
| `0x7F4B` | `PLANES.RES` item `0x4B` (chunk named `RES_7F4B.BIN`) | not a shape | the chunk does not start with `0x000C`; this item is 400 bytes of unread table data, one of 55 non-model items `0x7F39`..`0x7F6F` (models are `0x7F02`..`0x7F38`); `[Hypothesis]` that item `m + 0x37` belongs to model `m`, not checked | none seen in the 22 local films; the census does not list it |

**A two-vertex polygon does not desynchronise the walk of `0x7F24` and `0x7F34`.** `[Supported Inference]`, from these two shapes only. After each of `0x7F24`'s two `POLYZ` stops (`0x10A0`, `0x10C8`) and its `GVPOLY16` at `0x26BE`, and each of `0x7F34`'s four (`0x0F86`, `0x0F94`, `0x1062`, `0x1070`), the next words are a valid `IFVIS`, `GVPOLY16` or `RETURN`. With a throwaway edit making `vm.rs` read the operands (the count's words, or `2 * count + 1` for `GVPOLY`) and go on, `0x7F24` reaches 24 `RETURN`s and `0x7F34` 26, with no further stop; `export-gltf` goes from 13 to 100 nodes and from 38 to 99. That the walk stays in step does not prove the operand sizes right, only that nothing later contradicts them. On this machine's local 31-archive corpus the same edit takes the models that step over an opcode from 12 to 9, all group A (`ANIMATE`); the 14 `TAP`-only models are a separate census group and did not change. So for these two shapes the stop was the `count < 3` check; groups B to D (§ 1) were cut for the same reason (confirmed by the census after #393). This paragraph is the earlier analysis; `PLAYONE`'s two-vertex behaviour was read afterwards ([`sod-vm.md` § 8.9](../playone-exe/sod-vm.md#89-polygons-of-two-vertices)) and the edit is now in `vm.rs`.

_Source: [2026-11-11: each shape traced, and the two-vertex stop tested by skipping it](../../work/2026-11/273_sod-partial-shapes/journal.md#2026-11-11-each-shape-traced-and-the-two-vertex-stop-tested-by-skipping-it)._

**The two-vertex stop is fixed** ([#393](https://github.com/neilsh/stunt-reel/issues/393)). `[Supported Inference]`, from the code read in [`sod-vm.md` § 8.9](../playone-exe/sod-vm.md#89-polygons-of-two-vertices): `PLAYONE`'s `POLYZ` and `GVPOLY16` handlers have no count test (the clipping variant `0xC50E` was not read), and for two vertices its edge builder and span filler draw a thin line. `vm.rs` now emits `line_polygons` for a count of 2 and keeps stopping below 2. The census (§ 3) drops all seven models of old groups B to D, not only `0x7F24` and `0x7F34`, and the walk of every one reaches `RETURN`. `[Bounded Observation]`: the films that place the seven shapes (by the 2026-11-01 join: `DPLANES`, `DRUGLORD`, `JURASSIC`, `PITTJET1`, `PLANES`, `SPLANES`, `COWS`, `END3`, `FLAGDAY1`, `ID5`, `SFAPROMO`, `AWACS747`, `REXBRUCE`, `YODA`, `TALISD`, `AFTERBRN`, `REDB`) include none of the seven parity references (`CTRY`, `INTRO`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`, `LOCATION`), though films without a paired `.ALL` are not joined (§ 4). `mise run parity` scored `CTRY` 0.8973 and `INTRO` 0.8344 with and without the change.

**Follow-ups**: `OP_PERFDISK` (`0xA040`) is drawn as a two-sided 16-gon disc since [#392](https://github.com/neilsh/stunt-reel/issues/392) and its radius scale was checked on `BOMB` ticks 2058/2070 in [#425](https://github.com/neilsh/stunt-reel/issues/425), leaving open the use of the sibling entry `0xA05C`, the near-depth cut, the shadow-pass skip and the early exits (not reproduced), the 16-gon's 4 to 6 % narrowness, a 2 px height gap, and other shapes and depths ([`sod-vm.md` § 8.8](../playone-exe/sod-vm.md#88-model-frame-the-other-generators)); `OP_ANIMATE` and its `0x16` / `0x10` selectors are handled since [#222](https://github.com/neilsh/stunt-reel/issues/222) and [#408](https://github.com/neilsh/stunt-reel/issues/408) ([`sod-animate.md`](../playone-exe/sod-animate.md)); and SOD lines (`ZLINETO` and two-vertex polygons) are drawn one pixel wide on screen since [#415](https://github.com/neilsh/stunt-reel/issues/415) ([`sod-vm.md` § 8.9](../playone-exe/sod-vm.md#89-polygons-of-two-vertices), [§ 8.10](../playone-exe/sod-vm.md#810-lines-moveto-zlineto-and-linecol)). The census tables above were regenerated on 2026-11-12.

---

## 3. Census

Models are unique by content; a shape ID is `MODEL_xxxx.SOD`, other archive entries are named `ARCHIVE:ENTRY`. "Models" counts unique archive models in the group; loose `.BIN` files are listed separately. "Films placing" counts films whose paired `.ALL` holds one of the group's models under a shape ID the film's `create` opcodes place.

Generated 2026-11-12 (UTC) by `stuntreel sod-census --format markdown`. 331 archives: 3703 unique models, 3689 walk clean to RETURN, 14 stop only at `TAP` without anchors, 0 step over an unimplemented opcode; 3432 of them are `MODEL_%04X.SOD` chunks (3418 clean, 14 TAP-only, 0 unimplemented). 393 loose `.BIN` models add 146 unique (145 clean, 0 TAP-only, 1 unimplemented). Film use: 719 `.FLM`/`.TKE` films decoded, 427 without a paired `.ALL`, 18 placed shape IDs missing from the paired archive.

| Group | Unimplemented opcodes in order | Ends at | Models | Shape IDs | Loose `.BIN` | Films placing |
| :---: | :--- | :--- | :---: | :--- | :--- | :---: |
| A | none | `0x0333 (no width)` | 0 | — | `TESTTEXT.BIN` | 0 |
| — | `TAP` (no anchors supplied) | `RETURN` | 14 | `0202`–`0208`, `0402`–`0408`, `SCENERY1.RES:0000.BIN`, `SCENERY1.RES:0001.BIN`, `SCENERY1.RES:0002.BIN`, `SCENERY1.RES:0003.BIN`, `SCENERY1.RES:0004.BIN`, `SCENERY1.RES:0005.BIN`, `SCENERY1.RES:0006.BIN`, `SCENERY3.RES:0000.BIN`, `SCENERY3.RES:0001.BIN`, `SCENERY3.RES:0002.BIN`, `SCENERY3.RES:0003.BIN`, `SCENERY3.RES:0004.BIN`, `SCENERY3.RES:0005.BIN`, `SCENERY3.RES:0006.BIN` | — | 0 |

No shape is blocked in this run, so the per-shape film table is empty. The film counts in § 1 and § 2 come from the census before #222 and have no regenerated source.

### 3.1 Differences from the earlier censuses

* **2026-11-12, [#235](https://github.com/neilsh/stunt-reel/issues/235).** `BVIS` and `BZLT` left the census skip table for real handlers, with `REJVEC` and `REJ2D` beside them. The counts are unchanged: no walk reached any of the four, even with both arms of every `BVGT` followed by a temporary switch ([`sod-vm.md` § 8.6](../playone-exe/sod-vm.md#86-facing-flags-op_rej-and-op_ifvis)). `BZLT`'s skip width of 2 words was one short of its 3.
* **2026-11-12 (`main` at `dbfd0ed4`).** `ANIMATE` is no longer stepped over: the census skip entry went with #222, and the census now reports no unimplemented opcode for the 28 group A models. 3,418 of 3,432 chunks are clean (3,391 before). Loose `.BIN` models: 145 of 146 clean (142 before). Only `TESTTEXT.BIN` (`OP_TEXTURE`, no width) still stops. The tables above are the tool's output, so the old group letters are not kept.
* **2026-11-01.** Groups B to J (the centre stack, `GOSUB`, the matrix stack, rotations, `BVGT`, `SHADE1`) decode to the end; the walk now follows `SORTON`, `GOTO` and `GOSUB`, which exposed the two-vertex polygons of groups B to D. The 2026-10-24 census (309 archives; 3,368 clean, 50 blocked chunks) is in git history.
* **Counts reproduce** (2026-10-24 against the hand run). 3,432 unique chunks, 3,368 clean and 14 `TAP`-only match. The hand run listed 49 blocked models because it keyed by shape ID; the tool counts 50 variants, since `7E22` has one in group A and one in group D (the hand run's "last one scanned" problem, now reported both ways).
* **Group A (`ANIMATE`) is gone** since #222 (see the 2026-11-12 bullet). Earlier shape-ID references to group A describe the 2026-11-01 census. Old group E (`GOSUB`, `7E3B`, `7F03`) is group F there.
* **Old group C's order was wrong.** Its models block on `BVGT`, with `PUSHCENTRE` behind it, not the reverse: a lenient decode of `INTRO.ALL` `7F09` stops at offset `0x0C34` on `0x02FD`. `BVGT` therefore has no prerequisite to be the blocking opcode, though the centre stack is still needed for a full decode.
* **"Ends at `MOVECENTRE`" was a walk artefact.** The hand run stopped there; with every opcode-table width in the skip table the walk reaches `RETURN` in every group and finds masked `GOSUB`, `POPCENTRE`, `PUSHRELMAT`, `POPRELMAT`, `ROTX`, `ROTZ` and `GOTO`. That splits old B into B (`6403`–`641B`) and E (`7F18`, `7F1B`), and old C into C, H (`7F20`, `7F21`) and J (`7F1C`). `POPCENTRE`, listed as never reached, is reached in all of them.
* **New scope.** `.RES` entries, loose `.BIN` models and film use were not in the hand run. They add groups G and I (`GTX.RES` bodies, also as loose `.BIN`), K (`TESTTEXT.BIN`, `OP_TEXTURE`) and L (`UFO2.BIN`).

---

## 4. Limits

* **Followed branches.** The walk follows `SORTON` subtrees, `GOTO` and `GOSUB` (each `RETURN` resumes the pending branch) and `BVGT` with its animation variable at zero, so the other arm of each `BVGT` is not walked. A branch outside the stream, or more than 4,096 branches, stops the walk (`SodStopReason::MalformedBranch`); none does in the corpus.
* **Assumed operand widths.** Skips use the widths in [`sod-opcodes.md` § 1](sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes) (`CENSUS_SKIPS` in `vm.rs`), which come from `SOD.H`, not the binary (`OP_ANIMATE` and `OP_TAP` excepted). A wrong width desynchronises the walk and can invent or hide later opcodes. Every group reaching `RETURN` is weak evidence the widths it used are right.
* **No anchors.** `OP_TAP` is stepped over by its `count` words, so `TAP` appears as a skip even where `ANCHORPT.DAT` would resolve it.
* **Film join.** A film is paired with the `<NAME>.ALL` in its own folder ([`formats/flm.md`](flm.md)), and only those films count. 409 of the 700 films have none: the 143 in `Films/FLMOnly/` ship without sets, and 254 in `NEW/Morganroth/VAULT/` sit beside `.ALL` files of other names. Their placements are not counted, so film counts are lower bounds. Film names are deduplicated, so copies of one film in several folders count once.

A group's tier moves to `[Established]` once its opcodes have real handlers and its models decode to the end.

---

## 5. Regenerating

```sh
mise run sod-census -- --format markdown
```

runs `stuntreel sod-census` over `corpus/` (corpus-only, like `verify-corpus`, and never part of `mise run check`; `--corpus DIR` points elsewhere). Without `--format markdown` it prints each model variant with its films, plus any model that failed to walk and any file that failed to parse. Paste the markdown output over § 3 above § 3.1, then update §§ 1–2 and § 3.1 if the groups move.

When an opcode gets a real handler in `vm.rs`, delete its `CENSUS_SKIPS` entry (a unit test fails until you do) and re-run the census: its models drop out of § 3, and any opcode it was masking becomes the new blocking one.

---

## Ruled out

* A visible desync as the cause of the `0x7F24` and `0x7F34` fragments: the walk stays in step past every two-vertex polygon of those two and reaches `RETURN` once the stop is removed (operand sizes not independently checked); with the stop gone (#393) the whole of old groups B to D reaches `RETURN` ([journal](../../work/2026-11/273_sod-partial-shapes/journal.md#2026-11-11-each-shape-traced-and-the-two-vertex-stop-tested-by-skipping-it)).
* `0x3C01` and `0x7F4B` as shapes: they are data items, not `.SOD` chunks (same entry).

## Open questions

1. Is a two-vertex polygon one screen pixel wide in a capture, as the static reading says ([`sod-vm.md` § 8.9](../playone-exe/sod-vm.md#89-polygons-of-two-vertices))? None of the seven parity references is known to place one.
2. Which films place `0x07C6`, `0x3C01` and `0x7F4B`? The census prints film use only for blocked models.
3. What the `PLANES.RES` tables `0x7F39`..`0x7F6F` hold, and whether item `m + 0x37` belongs to model `m`.
