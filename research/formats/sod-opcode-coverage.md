# `.SOD` Opcode Coverage: Blocking-Opcode Work Queue

* **Evidence**: corpus census of every compiled `.SOD` model in `corpus/` (`.ALL` and `.RES` archive entries and loose `.BIN` files), walked by the census mode of the evaluator in [`crates/stunt-core/src/sod/vm.rs`](../../crates/stunt-core/src/sod/vm.rs) (`walk_sod`), and joined to the films that place each shape.
* **Scope**: which shapes are Partial SODs, their blocking opcode, the masked opcodes behind it, the films that use them, and the order to implement the opcodes in. Terms follow [`GLOSSARY.md`](../../GLOSSARY.md).
* **Tier**: `[Bounded Observation]` throughout (see § 4).
* **Owns**: the implementation queue for unhandled `.SOD` opcodes. Opcode semantics and operands stay in [`sod-opcodes.md` § 1](sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes); binary evidence stays in [`playone-exe/`](../playone-exe/).

§ 3 is the output of `mise run sod-census -- --format markdown` (§ 5). A first census was hand-run on 2026-10-23 with a throwaway hook in `vm.rs`; § 3.1 records where the tool's output differs from it.

---

## 1. Summary

The 309 archives hold 3,432 unique `MODEL_%04X.SOD` chunks (deduplicated by content). 3,368 walk to `OP_RETURN` with nothing stepped over. 14 stop only at `OP_TAP` because the census supplies no anchor table (a census artefact, not a gap). 50 step over at least one unimplemented opcode: 49 shape IDs, because `7E22` has two variants that block on different opcodes. Archive entries without a shape ID (`.RES` name tables) add 77 unique models, 12 of them blocked, and the 393 loose `.BIN` files add 147 more, 30 of them blocked; § 3 lists both beside the shape IDs.

Fourteen unimplemented opcodes are reached:

| Opcode | Mnemonic | Seen as | Operands assumed for the skip (from the opcode table) |
| :---: | :--- | :--- | :--- |
| `0x007E` | `OP_PUSHCENTRE` | blocking | none |
| `0x0087` | `OP_POPCENTRE` | masked | none |
| `0x0090` | `OP_MOVECENTRE` | masked behind `PUSHCENTRE` | `reg_off: u16` |
| `0x0144` | `OP_SHADE1` | blocking | `normal_reg: u16, ramp: u16` |
| `0x019E` | `OP_GOTO` | masked | `rel_offset: i16` |
| `0x01A7` | `OP_GOSUB` | blocking and masked | `rel_offset: i16` |
| `0x01DD` | `OP_ROTY` | masked (loose `UFO2.BIN` only) | `angle_bam: u16` |
| `0x01E6` | `OP_PUSHRELMAT` | masked; blocking in loose `UFO2.BIN` | none |
| `0x01EF` | `OP_POPRELMAT` | masked | none |
| `0x01F8` | `OP_ANIMATE` | blocking | `reg_off, parameter, selector, count: u16`, then `count` resource IDs |
| `0x02E2` | `OP_ROTX` | masked | `angle_bam: u16` |
| `0x02EB` | `OP_ROTZ` | masked | `angle_bam: u16` |
| `0x02FD` | `OP_BVGT` | blocking and masked | `reg: u16, val: i16, rel_off: i16` |
| `0x0333` | `OP_TEXTURE` | ends the walk (loose `TESTTEXT.BIN` only; the opcode table gives no width) | unknown |
| `0x022E` | `OP_TAP` | blocking without anchors | implemented; see [`sod-vm.md`](../playone-exe/sod-vm.md) |

The other unimplemented opcodes with a width in the opcode table (`CENSUS_SKIPS` in `vm.rs`) were never reached under the limits in § 4.

---

## 2. Work Queue

Ordered by shape IDs unblocked per opcode implemented. A shape decodes fully only once every opcode in its § 3 row has a handler. Each item's done-check is that its models decode with no stop in a lenient run, and that the next census shows no new masked opcode behind it.

| # | Implement | Unblocks (shape IDs) | Film use | Prerequisite | Evidence for semantics |
| :---: | :--- | :---: | :--- | :--- | :--- |
| 1 | `OP_ANIMATE` | 20 (group A) | 191 paired films; `0105`–`010C` and `3A80` each in 39–130, including `INTRO.FLM` and `CTRY.FLM` (`0107`) | none | `[Established]` dispatch and blit, [`sod-animate.md`](../playone-exe/sod-animate.md); selector and `.FLM` mapping open |
| 2 | `OP_SHADE1` | 5 (group D) | 38 films; `7F0A` in 31 | none | community table; `OP_SHADE2` is `[Hypothesis]` in [`formats/INDEX.md`](INDEX.md) |
| 3 | `OP_GOSUB` | 2 (group F) | `7F03` in 6 films, `7E3B` in 1 | none | community table; subroutine bodies are not walked (§ 4) |
| 4 | Centre stack: `PUSHCENTRE`, `MOVECENTRE`, `POPCENTRE` | 11 (group B) | `CRISMAS.FLM` only | item 3 | community table; si-tools ([`sod-opcodes.md` § 3](sod-opcodes.md#3-community-semantics-from-si-tools)) |
| 5 | Matrix stack and rotations: `PUSHRELMAT`, `POPRELMAT`, `ROTX`, `ROTZ`, then `OP_BVGT` (and `OP_GOTO` for group E) | 12 (groups C, E, H, J) | 77 films for group C alone; `7F09` in 40, including `INTRO.FLM` | items 3, 4 | community table; si-tools ([`sod-opcodes.md` § 3](sod-opcodes.md#3-community-semantics-from-si-tools)) |

For `INTRO.FLM` parity, `7F09` needs items 3–5 together: it blocks on `BVGT` and masks the centre stack, the matrix stack, `ROTX` and `GOSUB` behind it. Item 1 is the larger win by film count.

The loose `.BIN` names beside groups C, E, H and J (`737WGEAR.BIN`, `DC10WGEA.BIN`, `B2WGEAR.BIN`) suggest these shapes are landing-gear assemblies, which would fit a branch on a gear-state vector (`BVGT`) and articulated rotations. That reading is `[Hypothesis]`.

---

## 3. Census

Models are unique by content; a shape ID is `MODEL_xxxx.SOD`, other archive entries are named `ARCHIVE:ENTRY`. "Models" counts unique archive models in the group; loose `.BIN` files are listed separately. "Films placing" counts films whose paired `.ALL` holds one of the group's models under a shape ID the film's `create` opcodes place.

Generated 2026-10-24 (UTC) by `stuntreel sod-census --format markdown`. 309 archives: 3509 unique models, 3433 walk clean to RETURN, 14 stop only at `TAP` without anchors, 62 step over an unimplemented opcode; 3432 of them are `MODEL_%04X.SOD` chunks (3368 clean, 14 TAP-only, 50 unimplemented). 393 loose `.BIN` models add 147 unique (117 clean, 0 TAP-only, 30 unimplemented). Film use: 700 `.FLM`/`.TKE` films decoded, 409 without a paired `.ALL`, 18 placed shape IDs missing from the paired archive.

| Group | Unimplemented opcodes in order | Ends at | Models | Shape IDs | Loose `.BIN` | Films placing |
| :---: | :--- | :--- | :---: | :--- | :--- | :---: |
| A | `ANIMATE` | `RETURN` | 28 | `0105`–`010C`, `3A80`, `7C06`, `7C14`, `7C1B`, `7C1C`, `7C2C`–`7C2E`, `7C34`, `7E22`, `7E26`, `7E49`, `DSTAR-84.RES:DEATH STAR`, `SPRTTEST.RES:MAC LOGO 1000`, `SPRTTEST.RES:MAC LOGO 2000`, `SPRTTEST.RES:MAC LOGO 3000`, `SPRTTEST.RES:MAC LOGO 4000`, `SPRTTEST.RES:MAC LOGO 500`, `SPRTTEST.RES:MAC LOGO 5000`, `SPRTTEST.RES:MAC LOGO 6000`, `SPRTTEST.RES:SPRITE TEST` | `DAVEFIRE.BIN`, `DETHSTAR.BIN`, `DSTAR2.BIN`, `EXP1.BIN`, `EXP2.BIN`, `EXP3.BIN`, `EXP4.BIN`, `EXP5.BIN`, `EXP6.BIN`, `EXP7.BIN`, `EXP8.BIN`, `MAC1000.BIN`, `MAC2000.BIN`, `MAC3000.BIN`, `MAC4000.BIN`, `MAC500.BIN`, `MAC5000.BIN`, `MAC6000.BIN`, `MAC7000.BIN`, `MINE.BIN`, `SMOKE.BIN` | 191 |
| B | `PUSHCENTRE`, `MOVECENTRE`, `GOSUB`, `POPCENTRE` | `RETURN` | 11 | `6403`, `6405`, `6407`, `6408`, `640C`, `640D`, `6411`, `6414`–`6416`, `641B` | `J-HEAD1A.BIN`, `J-HEAD1B.BIN`, `J-HEAD1C.BIN`, `J-HEAD1D.BIN`, `J-HEAD1E.BIN`, `J-HEAD2A.BIN`, `J-HEAD2B.BIN`, `J-HEAD2C.BIN`, `J-HEAD2D.BIN`, `J-HEAD2E.BIN`, `J-HEAD3A.BIN`, `J-HEAD3B.BIN`, `J-HEAD3C.BIN`, `J-HEAD3D.BIN`, `J-HEAD3E.BIN`, `J-HEAD4A.BIN`, `J-HEAD4B.BIN`, `J-HEAD4C.BIN`, `J-HEAD4D.BIN`, `J-HEAD4E.BIN`, `J-HEAD5A.BIN`, `J-HEAD5B.BIN`, `J-HEAD5C.BIN`, `J-HEAD5D.BIN`, `J-HEAD5E.BIN`, `J-HEAD6A.BIN`, `J-HEAD6B.BIN`, `J-HEAD6C.BIN`, `J-HEAD6D.BIN`, `J-HEAD6E.BIN` | 1 |
| C | `BVGT`, `PUSHCENTRE`, `MOVECENTRE`, `PUSHRELMAT`, `ROTX`, `GOSUB`, `POPRELMAT`, `POPCENTRE` | `RETURN` | 7 | `7F02`, `7F09`, `7F0F`, `7F22`, `7F29`, `7F2C`, `7F32` | `737WGEAR.BIN`, `A10GEAR.BIN`, `BEAR.BIN`, `F16X.BIN`, `F16X2.BIN`, `SABRE7.BIN`, `TR1X.BIN` | 77 |
| D | `SHADE1` | `RETURN` | 6 | `7E17`, `7E22`, `7F0A`, `7F2A`, `7F38`, `ISD TEST-81.RES:ISD DECKS` | `F18WGEAR.BIN`, `ISD-TOP.BIN`, `JENNY.BIN`, `JEN_3.BIN` | 38 |
| E | `PUSHCENTRE`, `MOVECENTRE`, `PUSHRELMAT`, `ROTZ`, `BVGT`, `GOSUB`, `GOTO`, `POPRELMAT`, `POPCENTRE` | `RETURN` | 2 | `7F18`, `7F1B` | `BRISTOL.BIN`, `SFIRE.BIN` | 17 |
| F | `GOSUB` | `RETURN` | 2 | `7E3B`, `7F03` | `FALCON1.BIN`, `FALCON4.BIN`, `HANGLIDE.BIN`, `TIEFITER.BIN` | 7 |
| G | `GOSUB`, `PUSHCENTRE`, `MOVECENTRE`, `POPCENTRE` | `RETURN` | 2 | `GTX.RES:GTX 2ND BODY`, `GTX.RES:GTX FOUR TIRES` | `GTXSTOP.BIN` | 0 |
| H | `BVGT`, `PUSHCENTRE`, `MOVECENTRE`, `PUSHRELMAT`, `ROTZ`, `GOSUB`, `POPRELMAT`, `POPCENTRE`, `ROTX` | `RETURN` | 2 | `7F20`, `7F21` | `727XGEAR.BIN`, `DC10WGEA.BIN` | 28 |
| I | `GOSUB`, `PUSHCENTRE`, `MOVECENTRE`, `PUSHRELMAT`, `ROTX`, `POPRELMAT`, `POPCENTRE` | `RETURN` | 1 | `GTX.RES:GTX STOPPED` | `GTXROLL.BIN` | 0 |
| J | `BVGT`, `PUSHCENTRE`, `MOVECENTRE`, `PUSHRELMAT`, `ROTZ`, `GOSUB`, `POPRELMAT`, `POPCENTRE` | `RETURN` | 1 | `7F1C` | `B2WGEAR.BIN` | 24 |
| K | none | `0x0333 (no width)` | 0 | — | `TESTTEXT.BIN` | 0 |
| L | `PUSHRELMAT`, `ROTY`, `BVGT`, `GOSUB`, `GOTO`, `POPRELMAT` | `RETURN` | 0 | — | `UFO2.BIN` | 0 |
| — | `TAP` (no anchors supplied) | `RETURN` | 14 | `0202`–`0208`, `0402`–`0408`, `SCENERY1.RES:0000.BIN`, `SCENERY1.RES:0001.BIN`, `SCENERY1.RES:0002.BIN`, `SCENERY1.RES:0003.BIN`, `SCENERY1.RES:0004.BIN`, `SCENERY1.RES:0005.BIN`, `SCENERY1.RES:0006.BIN`, `SCENERY3.RES:0000.BIN`, `SCENERY3.RES:0001.BIN`, `SCENERY3.RES:0002.BIN`, `SCENERY3.RES:0003.BIN`, `SCENERY3.RES:0004.BIN`, `SCENERY3.RES:0005.BIN`, `SCENERY3.RES:0006.BIN` | — | 0 |

Shape IDs whose variants fall in more than one group: `7E22` (A, D).

Film use per placed shape (films resolved through their paired `.ALL`):

| Shape ID | Group | Films | Film names |
| :--- | :---: | :---: | :--- |
| `0105` | A | 130 | 2000AD.FLM, AC.FLM, AC2.FLM, ACCIDENT.FLM, AIRPORT.FLM, ARBOR1.FLM, BACKSTAB.FLM, BOB1.FLM, BOB2.FLM, BOBWRLD1.FLM, BOMB.FLM, BOMBING.FLM, BOMRUN.FLM, BOZTRLR.FLM, BRETT.FLM, BRIEFING.FLM, C.FLM, CAMERA.FLM, CHASEP1.FLM, CITY.FLM, COL3-1.FLM, COL3-2.FLM, COL5-1.FLM, COL5-5.FLM, COL5-6.FLM, COL5-8.FLM, COWS.FLM, CPU_ACT1.FLM, CREDITS.FLM, DAGS09.FLM, DEAN.FLM, DEVSCN23.FLM, DINTRO.FLM, E3TEASER.FLM, EGALLOC0.FLM, EGALLOC1.FLM, EGALLOC3.FLM, EGALLOC4.FLM, EGALLOC8.FLM, ELITE221.FLM, END3.FLM, F.FLM, F15.FLM, F162.FLM, FARMWAR.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, FREEWAY.FLM, GAVIN.FLM, H.FLM, HAHA.FLM, ID5-2.FLM, ID5.FLM, INCOMMIN.FLM, INSURE2.FLM, INTRO.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, JOSH.FLM, JOYRIDE.FLM, LD2-FNL.FLM, MORPROMO.FLM, MOTOR1.FLM, P38ATACK.FLM, PART01D.FLM, PEARL.FLM, PEARLTRA.FLM, PICKUP.FLM, PITJET3A.FLM, PITJET3B.FLM, PITTJET1.FLM, PITTJET2.FLM, PMENOPRN.FLM, POE4.FLM, PONCA.FLM, PONCB.FLM, PREV.FLM, PREV2.FLM, PROMOZ.FLM, R.FLM, RACE.FLM, REDB.FLM, RES.FLM, REVENG2.FLM, REVENGE.FLM, RUMBLCOP.FLM, S.FLM, SCENE01.TKE, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIDM3CD.FLM, SIFA1.FLM, SINTRO.FLM, SMUGGLE.FLM, SOLDIER.FLM, SPDKLS_1.FLM, STEALTH.FLM, STEALTHY.FLM, SUNRISE.FLM, SZ3.FLM, SZ3PROMO.FLM, T2.FLM, TACPREV.FLM, TAKELEAD.FLM, TANGO.FLM, TEASER.FLM, TERROR.FLM, THE.FLM, THEM2.FLM, TODD.FLM, TOTSED.FLM, TTRAILER.FLM, TW1-1.FLM, TW1-3.FLM, TW1-4.FLM, TWISTE.FLM, TWPREV.FLM, ULTRA.FLM, UNIFORM.FLM, UNKNOWN.FLM, V-5.FLM, WOW#3.FLM, WOW#4.FLM, X.FLM, ZERO.FLM |
| `0106` | A | 99 | 2000AD.FLM, AC2.FLM, ACCIDENT.FLM, APPROACH.FLM, ARBOR1.FLM, BACKSTAB.FLM, BALANC.FLM, BILLY1.FLM, BOB1.FLM, BOBWRLD1.FLM, BOMB.FLM, BOMRUN.FLM, BRNTRICK.FLM, CAMERA.FLM, CITY.FLM, COL3-1.FLM, COL3-2.FLM, COL5-4.FLM, COL5-5.FLM, COWS.FLM, CPU_ACT1.FLM, CREDITS.FLM, DINTRO.FLM, DRUGLORD.FLM, E3TEASER.FLM, EGALLOC0.FLM, EGALLOC3.FLM, F15.FLM, FARMWAR.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, H.FLM, HIGHWAY.FLM, HIGHWAYD.FLM, HIGHWAYS.FLM, ID5-2.FLM, ID5.FLM, INSURE1.FLM, INSURE2.FLM, INTRO.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, JOSH.FLM, JURASSIC.FLM, KACKTUS.FLM, LD2-FNL.FLM, MAXX1.FLM, MORPROMO.FLM, PART01D.FLM, PEARLTRA.FLM, PITJET3A.FLM, PITJET3B.FLM, PITTJET1.FLM, PITTJET2.FLM, PONCB.FLM, PREV.FLM, PREV2.FLM, Q.FLM, QFILES.FLM, R.FLM, REDB.FLM, RES.FLM, REVENG2.FLM, REVENGE.FLM, REXBRUCE.FLM, RUMBLCOP.FLM, S.FLM, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SINTRO.FLM, SMUGGLE.FLM, SOLDIER.FLM, SPDKLS_1.FLM, SUNRISE.FLM, SZ2.FLM, SZ3PROMO.FLM, T.FLM, T2.FLM, TALISD.FLM, TANGO.FLM, TEASER.FLM, TERROR.FLM, THE.FLM, THEM2.FLM, TODD.FLM, TOTSED.FLM, TTRAILER.FLM, TW1-2.FLM, TW1-4.FLM, TWISTE.FLM, UNIFORM.FLM, UNKNOWN.FLM, V-5.FLM, WOW#4.FLM, WW1.FLM |
| `0107` | A | 98 | 2000AD.FLM, AC2.FLM, ACCIDENT.FLM, AFTERBRN.FLM, AIRPORT.FLM, ARBOR1.FLM, BACKSTAB.FLM, BOB1.FLM, BOB2.FLM, BOBWRLD1.FLM, BOZTRLR.FLM, CARRIER.FLM, CHASEP1.FLM, CITY.FLM, COL3-1.FLM, COL5-5.FLM, COL5-7.FLM, COWS.FLM, CPU_ACT1.FLM, CTRY.FLM, DAGS09.FLM, DINTRO.FLM, DRUGLORD.FLM, EGALLOC0.FLM, EGALLOC1.FLM, EGALLOC3.FLM, END3.FLM, EXTREME.FLM, F162.FLM, FINAL-PR.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, ID5-2.FLM, ID5.FLM, INCOMMIN.FLM, INTRO.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, KACKTUS.FLM, LD2-FNL.FLM, MORPROMO.FLM, N.FLM, OPENING.FLM, P38ATACK.FLM, PART01D.FLM, PEARL.FLM, PEARLTRA.FLM, PITJET3A.FLM, PITJET3B.FLM, PITTJET1.FLM, PITTJET2.FLM, PREV.FLM, PREV2.FLM, PROMOZ.FLM, Q.FLM, R.FLM, RACE.FLM, RES.FLM, REVENG2.FLM, REVENGE.FLM, REXBRUCE.FLM, ROSWELL.FLM, RUMBLCOP.FLM, S.FLM, SCENE01.TKE, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIDM3BD.FLM, SIDM3CD.FLM, SIFA1.FLM, SINTRO.FLM, SMUGGLE.FLM, SOLDIER.FLM, STEALTHY.FLM, SUNRISE.FLM, SZ3.FLM, SZ3PROMO.FLM, SZ4.FLM, SZPROMO.FLM, TEASER.FLM, THE.FLM, THEM2.FLM, TOTSED.FLM, TTRAILER.FLM, TWISTE2.FLM, TYLER.FLM, ULTRA.FLM, UNKNOWN.FLM, V-5.FLM, WOW#2.FLM, WOW#3.FLM, WOW#4.FLM, ZERO.FLM |
| `0108` | A | 97 | 2000AD.FLM, AC.FLM, AC2.FLM, ACCIDENT.FLM, AIRPORT.FLM, ARBOR1.FLM, BACKSTAB.FLM, BOB1.FLM, BOBWRLD1.FLM, BOMBING.FLM, BOMRUN.FLM, CAMERA.FLM, CHASEP1.FLM, CITY.FLM, COL3-1.FLM, COL5-1.FLM, COL5-3.FLM, COL5-7.FLM, COL5-8.FLM, COWS.FLM, CPU_ACT1.FLM, DAGS09.FLM, DINGHEAD.FLM, DRUGLORD.FLM, E.FLM, EGALLOC3.FLM, EGALLOC8.FLM, END3.FLM, EXTREME.FLM, F15.FLM, FACTORYB.FLM, FARMWAR.FLM, FINAL-PR.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, ID5-2.FLM, ID5.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, JURASSIC.FLM, LD2-FNL.FLM, MAXX1.FLM, MIG.FLM, MORPROMO.FLM, MOTOR1.FLM, P38ATACK.FLM, PART01D.FLM, PEARLTRA.FLM, PITJET3A.FLM, PITTJET1.FLM, PITTJET2.FLM, PMENOPRN.FLM, POE3.FLM, PREV.FLM, PREV2.FLM, Q.FLM, QFILES.FLM, R.FLM, RACE.FLM, RES.FLM, REVENG2.FLM, RUMBLCOP.FLM, S.FLM, SCENE01.TKE, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIDM3BD.FLM, SIDM3CD.FLM, SIFA1.FLM, SMUGGLE.FLM, SOLDIER.FLM, STEALTHY.FLM, SZ3.FLM, SZ4.FLM, TAKELEAD.FLM, TALISD.FLM, TEASER.FLM, TERROR.FLM, THE.FLM, THEM.FLM, TOTSED.FLM, TTRAILER.FLM, TW1-2.FLM, TW1-3.FLM, TW1-4.FLM, TWISTE2.FLM, UNIFORM.FLM, UNKNOWN.FLM, WOW#2.FLM, WOW#3.FLM, WOW#4.FLM, ZERO.FLM |
| `0109` | A | 70 | 2000AD.FLM, AC2.FLM, ACCIDENT.FLM, AIRPORT.FLM, APPROACH.FLM, ARBOR1.FLM, AWACS747.FLM, BALANC.FLM, BOB2.FLM, BOMRUN.FLM, BRETT.FLM, CITY.FLM, COL3-1.FLM, COL5-4.FLM, COL5-8.FLM, CPU_ACT1.FLM, DAGS09.FLM, DC10.FLM, DRUGLORD.FLM, E3TEASER.FLM, ELITE221.FLM, END3.FLM, EXPLODE.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, HANGIN.FLM, ID5-2.FLM, ID5.FLM, INCOMMIN.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, LD2-FNL.FLM, MORPROMO.FLM, PART01D.FLM, PEARLTRA.FLM, PITTJET1.FLM, PMENOPRN.FLM, POE3.FLM, PREV.FLM, PREV2.FLM, Q.FLM, RES.FLM, REVENG2.FLM, REVENGE.FLM, RUMBLCOP.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIFA1.FLM, SOLDIER.FLM, STEALTHY.FLM, SZ2.FLM, SZ3.FLM, SZ3PROMO.FLM, TALISD.FLM, TERROR.FLM, THEM.FLM, THEM2.FLM, TOTSED.FLM, TW1-1.FLM, TW1-3.FLM, TW1-4.FLM, TYLER.FLM, ULTRA.FLM, UNIFORM.FLM, X.FLM, ZERO.FLM |
| `010A` | A | 46 | ACCIDENT.FLM, AIRPORT.FLM, ARBOR1.FLM, ASESINO.FLM, AWACS747.FLM, BOBWRLD1.FLM, BOMRUN.FLM, BOZTRLR.FLM, CITY.FLM, COL3-1.FLM, COL3-2.FLM, DAGS09.FLM, DRUGLORD.FLM, EGALLOC0.FLM, EXTREME.FLM, FINAL-PR.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, ID5.FLM, INSURE1.FLM, INTRUD3.FLM, INTRUDER.FLM, LD2-FNL.FLM, MORPROMO.FLM, PITJET3A.FLM, POE3.FLM, POE5.FLM, PREV.FLM, PREV2.FLM, Q.FLM, R.FLM, RES.FLM, REVENG2.FLM, REVENGE.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SOLDIER.FLM, STEALTH.FLM, TALISD.FLM, TW1-1.FLM, ULTRA.FLM, WOW#1.FLM, WW1.FLM, X.FLM |
| `010B` | A | 39 | BOB2.FLM, BOBWRLD1.FLM, BOMRUN.FLM, BOZTRLR.FLM, CHASEP1.FLM, CITY.FLM, COL5-7.FLM, COL5-8.FLM, CPU_ACT1.FLM, E3TEASER.FLM, END3.FLM, FLAGDAY1.FLM, ID5.FLM, INTRUDER.FLM, LD2-FNL.FLM, MORPROMO.FLM, N.FLM, PART01D.FLM, PMENOPRN.FLM, POE3.FLM, POE4.FLM, POE5.FLM, PREV2.FLM, Q.FLM, R.FLM, RACE.FLM, RES.FLM, S.FLM, SOLDIER.FLM, T2.FLM, TALISD.FLM, TERROR.FLM, TOTSED.FLM, TTRAILER.FLM, TW1-1.FLM, TW1-2.FLM, ULTRA.FLM, UNKNOWN.FLM, WOW#3.FLM |
| `010C` | A | 42 | ACCIDENT.FLM, BOB1.FLM, BOMRUN.FLM, BOZTRLR.FLM, CARRIER.FLM, CITY.FLM, COL3-1.FLM, COL3-2.FLM, COL5-6.FLM, COL5-7.FLM, E3TEASER.FLM, EGALLOC0.FLM, END3.FLM, FLASH.FLM, ID5-2.FLM, ID5.FLM, INTRUDER.FLM, LD2-FNL.FLM, MORPROMO.FLM, PART01D.FLM, PMENOPRN.FLM, PREV2.FLM, Q.FLM, R.FLM, REECE.FLM, REVENG2.FLM, S.FLM, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIFA1.FLM, STEALTH.FLM, TALISD.FLM, THEM.FLM, TOTSED.FLM, TW1-1.FLM, TW1-2.FLM, TW1-4.FLM, ULTRA.FLM, WOW#4.FLM, X.FLM |
| `3A80` | A | 114 | 2000AD.FLM, AC.FLM, AC2.FLM, ACCIDENT.FLM, AIRHEAD.FLM, ARBOR1.FLM, BACKSTAB.FLM, BOB1.FLM, BOB2.FLM, BOZTRLR.FLM, CHASEP1.FLM, COL3-1.FLM, COL3-2.FLM, COL5-1.FLM, COL5-4.FLM, COL5-5.FLM, COL5-6.FLM, COL5-8.FLM, COL7.FLM, COWS.FLM, CPU_ACT1.FLM, CREDITS.FLM, DRUGLORD.FLM, EGALLOC0.FLM, EGALLOC3.FLM, EGALLOC4.FLM, EGALLOC6.FLM, END3.FLM, EXPLODE.FLM, F.FLM, FACTORYB.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, H.FLM, ID5.FLM, INCOMMIN.FLM, INSURE1.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUD3.FLM, INTRUDER.FLM, JOSH.FLM, JOYRIDE.FLM, JURASSIC.FLM, KACKTUS.FLM, LD2-FNL.FLM, MAXX1.FLM, MIG.FLM, MORPROMO.FLM, NEWFX.FLM, P38ATACK.FLM, PART01D.FLM, PEARL.FLM, PEARLTRA.FLM, PITJET3A.FLM, PITTJET1.FLM, PITTJET2.FLM, PMENOPRN.FLM, POE4.FLM, POE5.FLM, PREV.FLM, PREV2.FLM, QFILES.FLM, RACE.FLM, REAL.FLM, REDB.FLM, REECE.FLM, RES.FLM, REVENG2.FLM, REXBRUCE.FLM, ROMROD.FLM, RUMBLCOP.FLM, SCENE01.TKE, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIDM3BD.FLM, SIDM3CD.FLM, SIFA1.FLM, SIFA2.FLM, SPDKLS_1.FLM, STEALTHY.FLM, SUNRISE.FLM, SZ1.FLM, SZ2.FLM, SZ3.FLM, SZ3PROMO.FLM, SZ4.FLM, SZPROMO.FLM, T2.FLM, TACPREV.FLM, TAKELEAD.FLM, TEASER.FLM, TERROR.FLM, THE.FLM, THEM2.FLM, TOTSED.FLM, TRAILER.FLM, TTRAILER.FLM, TW1-1.FLM, TWISTE.FLM, TWISTE2.FLM, TWISTPRE.FLM, TYLER.FLM, ULTRA.FLM, UNIFORM.FLM, UNKNOWN.FLM, V-5.FLM, WOW#2.FLM, WOW#3.FLM, WOW#4.FLM, ZERO.FLM |
| `6403` | B | 1 | CRISMAS.FLM |
| `6405` | B | 1 | CRISMAS.FLM |
| `6407` | B | 1 | CRISMAS.FLM |
| `6408` | B | 1 | CRISMAS.FLM |
| `640C` | B | 1 | CRISMAS.FLM |
| `640D` | B | 1 | CRISMAS.FLM |
| `6411` | B | 1 | CRISMAS.FLM |
| `6414` | B | 1 | CRISMAS.FLM |
| `6415` | B | 1 | CRISMAS.FLM |
| `6416` | B | 1 | CRISMAS.FLM |
| `641B` | B | 1 | CRISMAS.FLM |
| `7C06` | A | 1 | PART01D.FLM |
| `7C14` | A | 1 | PART01D.FLM |
| `7C1B` | A | 1 | PART01D.FLM |
| `7C1C` | A | 1 | PART01D.FLM |
| `7C2C` | A | 1 | PART01D.FLM |
| `7C2D` | A | 1 | PART01D.FLM |
| `7C2E` | A | 1 | PART01D.FLM |
| `7C34` | A | 1 | PART01D.FLM |
| `7E17` | D | 2 | PITJET3A.FLM, SFAPROMO.FLM |
| `7E22` | A | 1 | TTRAILER.FLM |
| `7E22` | D | 2 | TW1-1.FLM, TW1-4.FLM |
| `7E26` | A | 1 | TTRAILER.FLM |
| `7E3B` | F | 1 | EGALLOC0.FLM |
| `7E49` | A | 2 | NEWFX.FLM, PART01D.FLM |
| `7F02` | C | 10 | AFTERBRN.FLM, DPLANES.FLM, FLAGDAY1.FLM, PLANES.FLM, POE3.FLM, SFAPROMO.FLM, SPLANES.FLM, SZ2.FLM, SZ3PROMO.FLM, UNIFORM.FLM |
| `7F03` | F | 6 | BACKSTAB.FLM, COL5-3.FLM, DPLANES.FLM, FLAGDAY1.FLM, PLANES.FLM, SPLANES.FLM |
| `7F09` | C | 40 | 2000AD.FLM, AC2.FLM, BOZTRLR.FLM, BRNTRICK.FLM, COL5-1.FLM, COWS.FLM, DINTRO.FLM, DPLANES.FLM, END3.FLM, F162.FLM, FLAGDAY1.FLM, FLAGDAY2.FLM, FLASH.FLM, ID5-2.FLM, INCOMMIN.FLM, INTRO.FLM, INTRO2A.FLM, INTRUD3.FLM, INTRUDER.FLM, LAND.FLM, LD2-FNL.FLM, MORPROMO.FLM, PLANES.FLM, PREV.FLM, RACE.FLM, REAL.FLM, RES.FLM, REVENGE.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3AD.FLM, SIDM3BD.FLM, SINTRO.FLM, SOLDIER.FLM, SPLANES.FLM, TEASER.FLM, THE.FLM, TOTSED.FLM, TW1-2.FLM, TWPREV.FLM |
| `7F0A` | D | 31 | AFTERBRN.FLM, AIRSHOW.FLM, BOZTRLR.FLM, CAN.FLM, COL3-1.FLM, DPLANES.FLM, FLAGDAY1.FLM, INTRO2A.FLM, INTRUDER.FLM, PITJET3A.FLM, PITTJET2.FLM, PLANES.FLM, POE3.FLM, PREV.FLM, REAL.FLM, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3BD.FLM, SIFA1.FLM, SIFA2.FLM, SOLDIER.FLM, SPLANES.FLM, SZ3.FLM, SZ3PROMO.FLM, SZ4.FLM, SZPROMO.FLM, THE.FLM, TOTSED.FLM, UNKNOWN.FLM, WOW#4.FLM |
| `7F0F` | C | 30 | 2000AD.FLM, AC.FLM, AC2.FLM, BEARS.FLM, BOMRUN.FLM, CITY.FLM, DINGHEAD.FLM, DPLANES.FLM, FARMWAR.FLM, FLAGDAY1.FLM, PART01D.FLM, PITTJET1.FLM, PITTJET2.FLM, PLANES.FLM, PMENOPRN.FLM, POE3.FLM, REAL.FLM, REVENG2.FLM, REVENGE.FLM, SIFA1.FLM, SMUGGLE.FLM, SPLANES.FLM, TACPREV.FLM, TALISD.FLM, TOTSED.FLM, TTRAILER.FLM, TW1-1.FLM, TWPREV.FLM, WOW#1.FLM, WOW#3.FLM |
| `7F18` | E | 13 | COL3-1.FLM, COL7.FLM, DPLANES.FLM, EGALLOC1.FLM, INSURE2.FLM, INTRO2A.FLM, JOSH.FLM, PITJET3B.FLM, PITTJET1.FLM, PLANES.FLM, ROMROD.FLM, SPLANES.FLM, TOTSED.FLM |
| `7F1B` | E | 7 | BOB1.FLM, BOB2.FLM, BUSDRIVR.FLM, DPLANES.FLM, FLAGDAY1.FLM, PLANES.FLM, SPLANES.FLM |
| `7F1C` | J | 24 | AC.FLM, ACCIDENT.FLM, BOZTRLR.FLM, CITY.FLM, DPLANES.FLM, EGALLOC1.FLM, END3.FLM, FLAGDAY1.FLM, ID5.FLM, JURASSIC.FLM, MORPROMO.FLM, PLANES.FLM, REDALERT.FLM, SIDEM2D.FLM, SIDEM2S.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3CD.FLM, SPLANES.FLM, SZ4.FLM, TACPREV.FLM, TOTSED.FLM, ULTRA.FLM, V-5.FLM |
| `7F20` | H | 12 | CPU_ACT1.FLM, DC10.FLM, DPLANES.FLM, EXPLODE.FLM, PLANES.FLM, RES.FLM, REVENGE.FLM, REXBRUCE.FLM, SPLANES.FLM, SZ2.FLM, UNIFORM.FLM, V-5.FLM |
| `7F21` | H | 24 | AC.FLM, AFTERBRN.FLM, APPROACH.FLM, COL3-1.FLM, CPU_ACT1.FLM, DPLANES.FLM, FLAGDAY1.FLM, FLASH.FLM, INTRO2A.FLM, INTRUD2.FLM, INTRUDER.FLM, MORPROMO.FLM, PLANES.FLM, POE3.FLM, PREV2.FLM, QFILES.FLM, RES.FLM, REVENGE.FLM, REXBRUCE.FLM, RUMBLCOP.FLM, SPLANES.FLM, SZ2.FLM, TACPREV.FLM, THEM.FLM |
| `7F22` | C | 20 | COL5-5.FLM, CPU_ACT1.FLM, DPLANES.FLM, FLAGDAY1.FLM, GAVIN.FLM, INTRO2A.FLM, INTRUD2.FLM, PLANES.FLM, PREV.FLM, PREV2.FLM, RES.FLM, REVENGE.FLM, REXBRUCE.FLM, SIDEM2D.FLM, SIDEM2S.FLM, SPLANES.FLM, SZ2.FLM, SZ3PROMO.FLM, UNIFORM.FLM, V-5.FLM |
| `7F29` | C | 5 | DPLANES.FLM, PLANES.FLM, SIDEM2D.FLM, SIDEM2S.FLM, SPLANES.FLM |
| `7F2A` | D | 5 | ARBOR1.FLM, BALANC.FLM, BRNSTRM.FLM, COL3-1.FLM, TOTSED.FLM |
| `7F2C` | C | 13 | ARBOR1.FLM, BEARS.FLM, BOZTRLR.FLM, CITY.FLM, DPLANES.FLM, FLAGDAY1.FLM, INCOMMIN.FLM, PITJET3A.FLM, PLANES.FLM, REXBRUCE.FLM, SIDEM2D.FLM, SIDEM2S.FLM, SPLANES.FLM |
| `7F32` | C | 15 | AFTERBRN.FLM, PART01D.FLM, PITJET3A.FLM, PITJET3B.FLM, PITTJET2.FLM, POE3.FLM, RES.FLM, REXBRUCE.FLM, SFAPROMO.FLM, SIDEM3D.FLM, SIDEM3S.FLM, SIDM3BD.FLM, TTRAILER.FLM, WOW#1.FLM, WOW#3.FLM |
| `7F38` | D | 2 | JOSH.FLM, ROMROD.FLM |

### 3.1 Differences from the 2026-10-23 hand-run census

* **Counts reproduce.** 3,432 unique chunks, 3,368 clean and 14 `TAP`-only match. The hand run listed 49 blocked models because it keyed by shape ID; the tool counts 50 variants, since `7E22` has one in group A and one in group D (the hand run's "last one scanned" problem, now reported both ways).
* **Group A (`ANIMATE`), D (`SHADE1`) and the `TAP` group are unchanged** in shape IDs. Old group E (`GOSUB`, `7E3B`, `7F03`) is group F here.
* **Old group C's order was wrong.** Its models block on `BVGT`, with `PUSHCENTRE` behind it, not the reverse: a lenient decode of `INTRO.ALL` `7F09` stops at offset `0x0C34` on `0x02FD`. `BVGT` therefore has no prerequisite to be the blocking opcode, though the centre stack is still needed for a full decode.
* **"Ends at `MOVECENTRE`" was a walk artefact.** The hand run stopped there; with every opcode-table width in the skip table the walk reaches `RETURN` in every group and finds masked `GOSUB`, `POPCENTRE`, `PUSHRELMAT`, `POPRELMAT`, `ROTX`, `ROTZ` and `GOTO`. That splits old B into B (`6403`–`641B`) and E (`7F18`, `7F1B`), and old C into C, H (`7F20`, `7F21`) and J (`7F1C`). `POPCENTRE`, listed as never reached, is reached in all of them.
* **New scope.** `.RES` entries, loose `.BIN` models and film use were not in the hand run. They add groups G and I (`GTX.RES` bodies, also as loose `.BIN`), K (`TESTTEXT.BIN`, `OP_TEXTURE`) and L (`UFO2.BIN`).

---

## 4. Limits

* **Linear walk.** Branches, `GOTO` and `GOSUB` are stepped over, not followed, and the walk ends at the first `OP_RETURN`. Code after the main `RETURN`, including `GOSUB` targets, is not walked and may hold further masked opcodes.
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
