# Journal: research contradictions (#472)

Nine rulings from [#472](https://github.com/neilsh/stunt-reel/issues/472): seven contradictions listed in [plan Task 16](../307_docs-streamline/plan.md) and two stale claims. Each entry reads the evidence each side cites; only items 3 and 8 ran anything, and both only read corpus files with existing code. Method for all: static reading on `origin/main` at `1d94e4a`.

## 2026-11-13: the GVPOLY16 colour rule is decoded, its ramp operand is not traced

- **Question**: does a parity note still call the `GVPOLY16` colour rule undecoded while `terrain-shade.md` § 5 decodes it?
- **Method**: the claim moved from `research/parity/framing-and-actors.md` to `research/parity/hero-aircraft-placement.md` in #386. Read its § 1 and Ruled out against `terrain-shade.md` § 5, `world-scene.md` § 4.1, `sod-vm.md` § 8.5 and its open questions, and the `OP_GVPOLY16` arm of `crates/stunt-core/src/sod/vm.rs`.
- **Result**: `terrain-shade.md` § 5 (`[Established]`, static) gives the index both Gouraud handlers compose, `base + max(0, highbyte(s >> 1) + G)`, with `base` read by `mov ch, es:[si+1]`; `world-scene.md` § 4.1 reads that byte as the high byte of the record word `(ramp base << 8) | count`. `vm.rs` takes the ramp from the high byte of the word after the registers and has done so since #233 or before. `sod-vm.md` § 8.5 still lists "whether `GVPOLY16` takes its ramp from the word after its registers" as open: the handlers were not traced for which stream word that record is. `hero-aircraft-placement.md` § 1 (two 2026-11-01 bullets) and its Open question 1 still called the rule undecoded and named the `SHADE` light and per-vertex interpolation as open, both closed by #233 per `sod-vm.md`'s open questions. Its Ruled out entry "colour from the high byte of the `GVPOLY16` trailing word (0.7779 / 0.5449)" was scored before #233 lit shapes with the world light, and the renderer now does exactly that.
- **Verdict**: the rule is decoded; the parity note was stale. Which word supplies the ramp stays open, in `sod-vm.md` only.
- **Lives in**: `research/parity/hero-aircraft-placement.md` § 1, Ruled out and Open questions.

## 2026-11-13: SHADES lights from film variable 13, not from the SET time of day

- **Question**: `palette-and-shading.md` § 3.2 says the original's shading is not sun-derived; its `[BK-PAL-03]` says, as `[Established]`, that `OP_SHADES` relights facets from a sun vector loaded from the `.SET` `time_of_day`. Which holds?
- **Method**: read `terrain-shade.md` §§ 3, 4.1 and 4.2, `world-scene.md` § 2, `set.md`, and `mode13h.wgsl`.
- **Result**: `SHADES` (`0x9481`) stores `s = -clamp((N . L) >> 16)` per normal (`[Established]`). `L` is handed to `0x9100` by its caller; for scenery it is the world light at `DS:0x49EC`, whose one writer found is the film-variable-13 handler `0x196C` (`[Bounded Observation]` for "one writer"). Nothing cited ties it to a `.SET` field; `set.md` gives `time_of_day` only a `[Bounded Observation]` meaning with its encoding unconfirmed. The ground never passes through `0x9100` and is drawn flat. So § 3.2's capture result (full brightness scores best on the ground) and a light-dependent `SHADES` are both true: the ground takes no light, `SHADES` objects do.
- **Verdict**: `[BK-PAL-03]` was wrong on the light's source and over-tiered; § 3.2's "not a sun-derived level" holds for the ground only.
- **Lives in**: `research/formats/concepts/palette-and-shading.md` § 3.2 and § 4.

## 2026-11-13: GAME.RES has no name table

- **Question**: `res.md` § 3.1 says an archive with `res_index <= 0x0F` has no name table; § 3.3 marks `GAME.RES` (`0x01`) "String Table Present: Yes". Which holds?
- **Method**: read `crates/stunt-core/src/vfs/res.rs` (`parse_res` ignores `res_index` and sniffs region 0 for ASCII). Read the first 80 bytes of region 0 (`data[ofs[0]..ofs[1]]`) of `GAME.RES` from the retail install and Patch #3, and of `SCENERY1.RES` and `PLANES.RES` for comparison, with a one-off Python read.
- **Result**: `GAME.RES` (`res_index` `0x01`, 18 offsets) region 0 is 48 bytes starting `0C 00 70 17`, the SOD magic `0x000C`, on both builds. `SCENERY1.RES` region 0 also starts `0C 00`; `PLANES.RES` region 0 starts `Planes\0F86 Sabre\0`. `sod-opcode-coverage.md` already lists `GAME.RES` item `0x0D` as a shape.
- **Verdict**: § 3.1's threshold rule holds for `GAME.RES`; § 3.3's "Yes" was wrong. The table's "UI dialog strings, fonts, menus" description comes from `indices.txt` and is not checked.
- **Lives in**: `research/formats/res.md` § 3.3.

## 2026-11-13: full capture detail rests on an unread failure path

- **Question**: `lod.md` § 3 bullet 2 tags "every capture runs at detail `0xFFFF`" `[Established]`; bullet 1 says the premise, that a missing `game.var` leaves `DS:0x0710` at its initial `0xFFFF`, is `[Supported Inference]` because the loader's failure path is unread. Which tier stands?
- **Method**: read `lod.md` §§ 2-3 and `python/stunt_reel/tac/staging.py` (`ENGINE_FILES`, `_engine_root`, `stage_play`); listed the demo engine root `corpus/stisldem` and the `builds/*` trees in the data root.
- **Result**: `ENGINE_FILES` lists no `GAME.VAR`, and `stage_play` copies only those names beside the film, so no player stage gets one whatever its engine root (the `builds/*` trees do hold a `GAME.VAR`; `stisldem` does not). That part is read from the code. That the player then runs at `0xFFFF` depends on the unread failure path of loader `0x4790`. Staging moved from `capture_playone_reference.py` to `tac/staging.py`.
- **Verdict**: the conclusion takes its premise's tier, `[Supported Inference]`; no live read of `DS:0x0710` exists.
- **Lives in**: `research/playone-exe/lod.md` § 3.

## 2026-11-13: memory-map.md defines all MEM anchors but one

- **Question**: `memory-map.md` opens by owning "every `# [MEM-*]` anchor"; its summary says most. Which is true?
- **Method**: read `python/stunt_reel/doc_anchors.py` `ANCHORS`.
- **Result**: every `MEM-*` anchor's home is `MEMORY_MAP` except `MEM-UNPACK-LOCKOUT`, whose home is `MEMORY_NOTES` (`research/playone-exe/memory.md` § 3.4).
- **Verdict**: the opening line was too broad; it now names the exception and defers to the registry.
- **Lives in**: `research/playone-exe/memory-map.md`, opening paragraph.

## 2026-11-13: 108 dispatch slots is the unpatched count

- **Question**: `sod-vm.md` § 1 gives the dispatch table 108 slots and, a few lines on, "107 table entries". Which is right?
- **Method**: read `sod-vm.md` § 1, `world-scene.md` § 4 and `patch3.md` § 4.1.
- **Result**: `world-scene.md` § 4's byte scan of the unpacked unpatched image finds 108 slots; `patch3.md` § 4.1 pairs the builds slot by slot and finds 108 unpatched and 107 on Patch #3 (`[Supported Inference]`, static). The "107 table entries" line in `sod-vm.md` names no build; its substance is the `0x022E` slot observed at `CS:0x1544`.
- **Verdict**: both counts are right for their build; `sod-vm.md` now says which, and the stray count is dropped. Which build `sod-opcodes.md` numbers is left to [#480](https://github.com/neilsh/stunt-reel/issues/480).
- **Lives in**: `research/playone-exe/sod-vm.md` § 1.

## 2026-11-13: the cause of the one-tick page lag is open

- **Question**: `capture.md` § 4 says the captured page lags the film clock by one tick because `PLAYONE` advances the clock at the start of a frame; `dosbox-x-legacy.md` § 5 says the lag came from the debugger's late, wall-paced tags. Which cause does the evidence support?
- **Method**: read both sections, `memory.md` § 3.2, `capture-dosbox-automation.md` § 3 and `crates/stunt-cli/src/playback.rs` (`capture_tick`).
- **Result**: the one-tick fit is measured (`[Bounded Observation]`: one tick back CTRY 0.7713 to 0.7732, INTRO 0.6775 to 0.6793; two ticks 0.7723 / 0.6773; integer phase). Neither cause is backed. `memory.md` § 3.2 places the clock increment in the 50 Hz interrupt (`0x43B0`), and no note cites code showing the clock moving before the page is drawn. The late-tag measurement (a page matching a stepped page 7 to 10 ticks earlier than its tag) is not one tick, and no run isolated the tags' share of the fitted lag. `capture-dosbox-automation.md` § 3 sees the page lag the clock "by different ticks in each emulator", which points at the harness but does not measure it.
- **Verdict**: open. Both notes now state the fit and give each cause as a `[Hypothesis]`; `playback.rs` stops stating the first as fact.
- **Lives in**: `research/playone-exe/capture.md` § 4, `research/playone-exe/dosbox-x-legacy.md` § 5 and its Open questions.

## 2026-11-13: unlzexe unpacks every STUNT.EXE

- **Question**: `map.md` open question 3 says `mise run unlzexe` fails on `STUNT.EXE` with an `IndexError` in the relocation table. Does it still?
- **Method**: ran `unlzexe.unpack` and `unlzexe.to_mz` from `python/scripts/unlzexe.py` on every `STUNT.EXE` in the data root (the retail install, its `NEV_001` copy, OldPLAY, and the `unpatched`, `patched` and `patch3` build trees with their `NEV_001` copies); read `tests/test_unlzexe.py`.
- **Result**: all nine unpack without error: the unpatched copies to a 248,460-byte image with 248 relocations, the `patched` and `patch3` root copies to 244,684 bytes with 256. `test_unpacks_the_program_under_an_entry_stub` covers the retail install's stubbed copy.
- **Verdict**: the open question is answered; removed.
- **Lives in**: `research/formats/auxiliary/map.md` § 4.2 (removed), `research/formats/concepts/compression.md` (unchanged, already current).

## 2026-11-13: OP_PERFDISK draws a disc

- **Question**: does the `OP_PERFDISK` doc comment in `vm.rs` still say the VM draws nothing?
- **Method**: read the constant's comment and its `run_vm` arm.
- **Result**: the arm calls `disc_polygons` (since #392); the comment said "consumes the three words and draws nothing".
- **Verdict**: comment rewritten.
- **Lives in**: `crates/stunt-core/src/sod/vm.rs`, `OP_PERFDISK`.
