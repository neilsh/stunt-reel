# Journal: research contradictions (#472)

Nine rulings from [#472](https://github.com/neilsh/stunt-reel/issues/472): seven contradictions listed in [plan Task 16](../307_docs-streamline/plan.md) and two stale claims. Each entry reads the evidence each side cites; only items 3 and 8 ran anything, and both only read corpus files with existing code. Method for all: static reading on `origin/main` at `1d94e4a`.

## 2026-11-13: the GVPOLY16 colour rule is decoded, its ramp operand is not traced

- **Question**: does a parity note still call the `GVPOLY16` colour rule undecoded while `terrain-shade.md` § 5 decodes it?
- **Method**: the claim moved from `research/parity/framing-and-actors.md` to `research/parity/hero-aircraft-placement.md` in #386. Read its § 1 and Ruled out against `terrain-shade.md` § 5, `world-scene.md` § 4.1, `sod-vm.md` § 8.5 and its open questions, and the `OP_GVPOLY16` arm of `crates/stunt-core/src/sod/vm.rs`.
- **Result**: `terrain-shade.md` § 5 (`[Established]`, static) gives the index the Gouraud handlers compose, `base + max(0, highbyte(s >> 1) + G)` for `GVPOLY` (`s >> 2` for `GVPOLY16`, corrected in [the 2026-11-14 entry](#2026-11-14-gvpoly16-shifts-its-shade-by-two-and-reads-its-ramp-after-the-registers)), with `base` read by `mov ch, es:[si+1]`; `world-scene.md` § 4.1 reads that byte as the high byte of the record word `(ramp base << 8) | count`. `vm.rs` takes the ramp from the high byte of the word after the registers and has done so since #233 or before. `sod-vm.md` § 8.5 still lists "whether `GVPOLY16` takes its ramp from the word after its registers" as open: the handlers were not traced for which stream word that record is. `hero-aircraft-placement.md` § 1 (two 2026-11-01 bullets) and its Open question 1 still called the rule undecoded and named the `SHADE` light and per-vertex interpolation as open, both closed by #233 per `sod-vm.md`'s open questions. Its Ruled out entry "colour from the high byte of the `GVPOLY16` trailing word (0.7779 / 0.5449)" was scored before #233 lit shapes with the world light, and the renderer now does exactly that.
- **Verdict**: the rule is decoded; the parity note was stale. Which word supplies the ramp was left open in `sod-vm.md` and `hero-aircraft-placement.md`; [the 2026-11-14 entry](#2026-11-14-gvpoly16-shifts-its-shade-by-two-and-reads-its-ramp-after-the-registers) resolves it.
- **Also read**: `world-scene.md` § 4.1's live probe saw base `0x00` on all 32 records the hero aircraft passed to `0x9A24`, while `vm.rs` reads base `0x30` from `0x7F37`'s `0x3004`; that bears on the open question; [the 2026-11-14 entry](#2026-11-14-gvpoly16-shifts-its-shade-by-two-and-reads-its-ramp-after-the-registers) shows the probe read `count`'s high byte.
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
- **Note**: the clock itself is incremented in the 50 Hz interrupt, so the first reading is about when the frame step takes the clock relative to its draw, not when it increments it.
- **Verdict**: open. Both notes now state the fit and give each cause as a `[Hypothesis]`; `playback.rs` stops stating the first as fact.
- **Lives in**: `research/playone-exe/capture.md` § 4, `research/playone-exe/dosbox-x-legacy.md` § 5 and its Open questions.

## 2026-11-13: unlzexe unpacks every STUNT.EXE in the data root

- **Question**: `map.md` open question 3 says `mise run unlzexe` fails on `STUNT.EXE` with an `IndexError` in the relocation table. Does it still?
- **Method**: ran `unlzexe.unpack` and `unlzexe.to_mz` from `python/scripts/unlzexe.py` on every `STUNT.EXE` in the data root (the retail install, its `NEV_001` copy, OldPLAY, and the `unpatched`, `patched` and `patch3` build trees with their `NEV_001` copies); read `tests/test_unlzexe.py`.
- **Result**: all nine unpack without error: the seven unpatched copies (every `NEV_001` copy included) to a 248,460-byte image with 248 relocations, the `patched` and `patch3` root copies to 244,684 bytes with 256. `test_unpacks_the_program_under_an_entry_stub` models the retail install's stubbed copy with a synthetic stub.
- **Verdict**: the open question is answered; removed.
- **Lives in**: `research/formats/auxiliary/map.md` § 4.2 (removed), `research/formats/concepts/compression.md` (unchanged, already current).

## 2026-11-13: OP_PERFDISK draws a disc

- **Question**: does the `OP_PERFDISK` doc comment in `vm.rs` still say the VM draws nothing?
- **Method**: read the constant's comment and its `run_vm` arm.
- **Result**: the arm calls `disc_polygons` (since #392); the comment said "consumes the three words and draws nothing".
- **Verdict**: comment rewritten.
- **Lives in**: `crates/stunt-core/src/sod/vm.rs`, `OP_PERFDISK`.

## 2026-11-14: GVPOLY16 shifts its shade by two and reads its ramp after the registers

- **Question**: a review of PR #494 reported that `GVPOLY16` shifts its shade by 2, not 1, and that the handler reads its ramp word only after the edge builder consumes the registers, while the live probe broke at the handler's entry. Do the listings bear that out?
- **Method**: `mise run disasm -- 0x995C 0x9B10` and `-- 0xC9D4 0xCA60` on the unpatched image; `0x8C2F..0x8CD0` on the Patch #3 image (`--image playone_p3.img`); read `tools/dosbox-x/plans/ground-objects.toml`.
- **Result**: `0x995C` (`GVPOLY`) shifts with `sar ax, 1` (`0x99E9`). Its flat route also has a `sar ax, 1` (`0x9990`), but nothing loads a shade into `AX` before it, so what it shifts is not read here. `0x9A24` (`GVPOLY16`) shifts with `sar ax, 2` in its per-vertex loop (`0x9AB8`) and in its flat path (`0x9A5C`, then `jns`/clamp and `shr ax, 1`); Patch #3 has `sar ax, 2` at `0x8CC3` and `0x8C67`. On the Gouraud route `0x9A24` calls `0xC9D4` (`0x9A7E`), whose first `lodsw` is `count` (`mov cx, ax`) and which then reads `count` register offsets (`0xC9E0`, then the `loop` at `0xCA12..0xCA5B`); only then does `0x9A98` do `es lodsw; mov cx, ax`, so `CH` (the base added at `0x9AC3`) is the high byte of the word after the registers and `CL` counts the shade offsets read at `0x9AB0`. `0x995C` matches (`0x99AF`, `0x99C9`). The flat routes read `es:[si+1]` after `call [0x8080]` (`0xC9D4` or `0xC50E`; `0xC50E` not read). `ground-objects.toml` breaks at `0x995C` and `0x9A24` and captures `mem:ES:SI:40` there, so its first word is `count`.
- **Verdict**: both review points confirmed. `GVPOLY16` is `idx = max(0, highbyte(s >> 2) + G) + base`; its ramp base is the high byte of the word after the registers (`[Established]` for the `0xC9D4` route; `0xC50E` was first tagged `[Supported Inference]` unread, and is read in the next entry); the logged base `0x00` was `count`'s high byte. `vm.rs` already does both, but its `shade_level` also subtracts 2 when the base is `0x10`, which the handlers do not (now an open question in `sod-vm.md`).
- **Also**: `mise run gvpoly-stream` decoded the entry word as the ramp word; it now reads `count`, the registers, then the ramp word. On `CTRY/ground-objects-unpatched-20261104T092138Z.jsonl` it lists 32 records of object `608A`, bases `0x30` x13, `0xE0` x10, `0x00` x4, `0x20` x2, `0x29` x2, `0x40` x1.
- **Lives in**: `research/playone-exe/terrain-shade.md` § 5, `research/playone-exe/sod-vm.md` § 8.5, `research/playone-exe/world-scene.md` § 4.1, `research/parity/hero-aircraft-placement.md` § 1.

## 2026-11-14: the clipping edge builder and the Gouraud loop count

- **Question**: a second review of PR #494 reported that `0xC50E`'s handling of `SI`, tagged `[Supported Inference]` though unread, can be read, and that the Gouraud loop counts its shades over the ramp word's whole low byte, not `& 0x0F`. Do the listings bear that out?
- **Method**: `mise run disasm` over `0xC50E..0xC6B8`, `0xC6AF..0xC88E`, `0xC88E..0xC950`, `0xC65A..0xC6AF` and `0xCA5E..0xCAD7` (unpatched); `0x8B70..0x8CE0` on the Patch #3 image; the `0x995C`/`0x9A24` listing of the previous entry.
- **Result**: `0xC50E` reads `count` into `work:0x41AC` (`0xC523`) and the last register through `es:[bx+si-2]` (`0xC535`) without moving `SI`; each register `es lodsw` (`0xC556`, `0xC589`) is followed by one `dec word [0x41AC]` (`0xC561`, `0xC57F`, `0xC59C`) before the loop can end, so it reads exactly `count` offsets. `0xC60C`/`0xC656` push and pop `SI`; `0xC6AF` pushes it at `0xC6B6` and pops it before each `ret` (`0xC814`, `0xC818`, `0xC880`, `0xC88B`); `0xC88E` pushes and pops it; `0xC65A` and `0xCA5E..0xCACF` do not name it. The Gouraud loops load `CX` from the ramp word (`0x99CB`, `0x9A9A`; Patch #3 `0x8BD6`, `0x8CA5`) and count `dec cl` (`0x99FF`, `0x9ACF`; Patch #3 `0x8C0A`, `0x8CDA`); `and ax, 0Fh` is only in the skip tail (`0x9970`, `0x9A38`; Patch #3 `0x8C43`).
- **Verdict**: both confirmed. `0xC50E` leaves `SI` on the ramp word (`[Established]`, static). `gvpoly-stream` now counts shades by the whole low byte; the 304 `CTRY` hits all have a low byte of 3 to 6, so its output is unchanged.
- **Lives in**: `research/playone-exe/sod-vm.md` § 8.5, `research/playone-exe/world-scene.md` § 4.1, `python/stunt_reel/gvpoly_stream.py`.
