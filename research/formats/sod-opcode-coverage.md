# `.SOD` Opcode Coverage: Blocking-Opcode Work Queue

* **Evidence**: corpus census of every compiled `.SOD` model in `corpus/` (`.ALL` and `.RES` archive entries and loose `.BIN` files), walked by the census mode of the evaluator in [`crates/stunt-core/src/sod/vm.rs`](../../crates/stunt-core/src/sod/vm.rs) (`walk_sod`), and joined to the films that place each shape.
* **Scope**: which shapes are Partial SODs, their blocking opcode, the masked opcodes behind it, the films that use them, and the order to implement the opcodes in. Terms follow [`GLOSSARY.md`](../../GLOSSARY.md).
* **Tier**: `[Bounded Observation]` throughout (see § 4).
* **Owns**: the implementation queue for unhandled `.SOD` opcodes. Opcode semantics and operands stay in [`sod-opcodes.md` § 1](sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes); binary evidence stays in [`playone-exe/`](../playone-exe/).

§ 3 is the output of `mise run sod-census -- --format markdown` (§ 5). A first census was hand-run on 2026-10-23 with a throwaway hook in `vm.rs`; § 3.1 records where the tool's output differs from it.

---

## 1. Summary

The census of 2026-11-01 (after the `SORTON` walk, the centre and matrix stacks, `GOTO`/`GOSUB`, `ROTX`/`ROTY`/`ROTZ`, `BVGT` and the four `SHADE` opcodes got handlers, commit `cddd583`) walks 331 archives. Of the 3,432 unique `MODEL_%04X.SOD` chunks, 3,391 walk to `OP_RETURN` with nothing stepped over (3,368 on 2026-10-24) and 14 stop only at `OP_TAP` because the census supplies no anchor table (a census artefact, not a gap). Groups B to J of the 2026-10-24 census are gone. What is left:

| Opcode or stop | Mnemonic | Seen as |
| :---: | :--- | :--- |
| `0x01F8` | `OP_ANIMATE` | blocking (group A, 28 models) |
| `0x00F3`, `0x0168`, `0x02BE` | `OP_POLYZ`, `OP_GVPOLY`, `OP_GVPOLY16` with two vertices | stop (groups B to D, 7 models: `7E09`, `7E0C`, `7E1F`, `7E48`, `7F24`, `7F34`, `7F35` and the `PIPER`/`SHUTTLE` loose `.BIN` copies) |
| `0x0333` | `OP_TEXTURE` | ends the walk (loose `TESTTEXT.BIN` only; the opcode table gives no width) |
| `0x022E` | `OP_TAP` | blocking without anchors; implemented, see [`sod-vm.md`](../playone-exe/sod-vm.md) |

Groups B to D are new: the two-vertex polygons sit in `SORTON` subtrees past the first `RETURN`, which no earlier walk reached. Strict decodes fail on them; lenient and census decodes stop there and keep the geometry before (`SodStopReason::MalformedPolygon`). Whether `PLAYONE` draws a two-vertex polygon as a line, or the walk has desynchronised before it, is open (§ 4).

---

## 2. Work Queue

| # | Implement | Unblocks (shape IDs) | Film use | Evidence for semantics |
| :---: | :--- | :---: | :--- | :--- |
| 1 | `OP_ANIMATE` | 28 (group A) | 191 paired films; `0105`–`010C` and `3A80` each in 39–130, including `INTRO.FLM` and `CTRY.FLM` (`0107`) | `[Established]` dispatch and blit, [`sod-animate.md`](../playone-exe/sod-animate.md); selector and `.FLM` mapping open |
| 2 | Two-vertex `POLYZ`/`GVPOLY`: a line, or a walk desync before it | 7 (groups B to D) | 20 films; `7F24` and `7F35` in `PLANES.FLM` and `DPLANES.FLM` | none yet: check the `SORTON` targets in front of each stop first |

The handlers added on 2026-11-01 are community readings (FreeFlight `siobj.cpp`, si-tools) or `[Hypothesis]` (`SHADE`, [`sod-vm.md` § 8.5](../playone-exe/sod-vm.md#85-polygon-colour-at-shade-time)); the animation variables `ROT*` and `BVGT` read are zero (a resting pose), so articulated parts draw at rest.

---

## 3. Census

Models are unique by content; a shape ID is `MODEL_xxxx.SOD`, other archive entries are named `ARCHIVE:ENTRY`. "Models" counts unique archive models in the group; loose `.BIN` files are listed separately. "Films placing" counts films whose paired `.ALL` holds one of the group's models under a shape ID the film's `create` opcodes place.

Generated 2026-11-01 (UTC) by `stuntreel sod-census --format markdown`. 331 archives: 3703 unique models, 3654 walk clean to RETURN, 14 stop only at `TAP` without anchors, 35 step over an unimplemented opcode; 3432 of them are `MODEL_%04X.SOD` chunks (3391 clean, 14 TAP-only, 27 unimplemented). 393 loose `.BIN` models add 146 unique (142 clean, 0 TAP-only, 4 unimplemented). Film use: 719 `.FLM`/`.TKE` films decoded, 427 without a paired `.ALL`, 18 placed shape IDs missing from the paired archive.

| Group | Unimplemented opcodes in order | Ends at | Models | Shape IDs | Loose `.BIN` | Films placing |
| :---: | :--- | :--- | :---: | :--- | :--- | :---: |
| A | `ANIMATE` | `RETURN` | 28 | `0105`–`010C`, `3A80`, `7C06`, `7C14`, `7C1B`, `7C1C`, `7C2C`–`7C2E`, `7C34`, `7E22`, `7E26`, `7E49`, `DSTAR-84.RES:DEATH STAR`, `GAME.RES:0003.BIN`, `GAME.RES:0004.BIN`, `GAME.RES:0005.BIN`, `GAME.RES:0006.BIN`, `GAME.RES:0007.BIN`, `GAME.RES:0008.BIN`, `GAME.RES:0009.BIN`, `GAME.RES:000A.BIN`, `GAME.RES:000B.BIN`, `PRODTOOL.RES:36000X36000`, `SPRTTEST.RES:MAC LOGO 1000`, `SPRTTEST.RES:MAC LOGO 2000`, `SPRTTEST.RES:MAC LOGO 3000`, `SPRTTEST.RES:MAC LOGO 4000`, `SPRTTEST.RES:MAC LOGO 500`, `SPRTTEST.RES:MAC LOGO 5000`, `SPRTTEST.RES:MAC LOGO 6000`, `SPRTTEST.RES:SPRITE TEST` | `DAVEFIRE.BIN`, `DETHSTAR.BIN`, `DSTAR2.BIN`, `EXP1.BIN`, `EXP2.BIN`, `EXP3.BIN`, `EXP4.BIN`, `EXP5.BIN`, `EXP6.BIN`, `EXP7.BIN`, `EXP8.BIN`, `MAC1000.BIN`, `MAC2000.BIN`, `MAC3000.BIN`, `MAC4000.BIN`, `MAC500.BIN`, `MAC5000.BIN`, `MAC6000.BIN`, `MAC7000.BIN`, `MINE.BIN`, `SMOKE.BIN` | 191 |
| B | none | `0x00F3 (polygon with fewer than three vertices)` | 3 | `7E0C`, `7E48`, `7F24`, `PLANES.RES:BOEING 747` | `PIPER.BIN`, `PIPER2.BIN`, `PIPER3.BIN` | 7 |
| C | none | `0x0168 (polygon with fewer than three vertices)` | 2 | `7E09`, `7E1F` | — | 3 |
| D | none | `0x02BE (polygon with fewer than three vertices)` | 2 | `7F34`, `7F35`, `PLANES.RES:MILITARY P51`, `PLANES.RES:SPACE SHUTTLE` | `747WSHUT.BIN`, `SHUTTLE2.BIN` | 10 |
| E | none | `0x0333 (no width)` | 0 | — | `TESTTEXT.BIN` | 0 |
| — | `TAP` (no anchors supplied) | `RETURN` | 14 | `0202`–`0208`, `0402`–`0408`, `SCENERY1.RES:0000.BIN`, `SCENERY1.RES:0001.BIN`, `SCENERY1.RES:0002.BIN`, `SCENERY1.RES:0003.BIN`, `SCENERY1.RES:0004.BIN`, `SCENERY1.RES:0005.BIN`, `SCENERY1.RES:0006.BIN`, `SCENERY3.RES:0000.BIN`, `SCENERY3.RES:0001.BIN`, `SCENERY3.RES:0002.BIN`, `SCENERY3.RES:0003.BIN`, `SCENERY3.RES:0004.BIN`, `SCENERY3.RES:0005.BIN`, `SCENERY3.RES:0006.BIN` | — | 0 |

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
| `7C06` | A | 1 | PART01D.FLM |
| `7C14` | A | 1 | PART01D.FLM |
| `7C1B` | A | 1 | PART01D.FLM |
| `7C1C` | A | 1 | PART01D.FLM |
| `7C2C` | A | 1 | PART01D.FLM |
| `7C2D` | A | 1 | PART01D.FLM |
| `7C2E` | A | 1 | PART01D.FLM |
| `7C34` | A | 1 | PART01D.FLM |
| `7E09` | C | 1 | TALISD.FLM |
| `7E0C` | B | 1 | YODA.FLM |
| `7E1F` | C | 3 | AFTERBRN.FLM, REDB.FLM, TALISD.FLM |
| `7E22` | A | 1 | TTRAILER.FLM |
| `7E26` | A | 1 | TTRAILER.FLM |
| `7E48` | B | 1 | YODA.FLM |
| `7E49` | A | 2 | NEWFX.FLM, PART01D.FLM |
| `7F24` | B | 6 | DPLANES.FLM, DRUGLORD.FLM, JURASSIC.FLM, PITTJET1.FLM, PLANES.FLM, SPLANES.FLM |
| `7F34` | D | 5 | COWS.FLM, END3.FLM, FLAGDAY1.FLM, ID5.FLM, SFAPROMO.FLM |
| `7F35` | D | 6 | AWACS747.FLM, DPLANES.FLM, END3.FLM, PLANES.FLM, REXBRUCE.FLM, SPLANES.FLM |

### 3.1 Differences from the earlier censuses

* **2026-11-01.** Groups B to J (the centre stack, `GOSUB`, the matrix stack, rotations, `BVGT`, `SHADE1`) decode to the end; the walk now follows `SORTON`, `GOTO` and `GOSUB`, which exposed the two-vertex polygons of groups B to D. The 2026-10-24 census (309 archives; 3,368 clean, 50 blocked chunks) is in git history.
* **Counts reproduce** (2026-10-24 against the hand run). 3,432 unique chunks, 3,368 clean and 14 `TAP`-only match. The hand run listed 49 blocked models because it keyed by shape ID; the tool counts 50 variants, since `7E22` has one in group A and one in group D (the hand run's "last one scanned" problem, now reported both ways).
* **Group A (`ANIMATE`), D (`SHADE1`) and the `TAP` group are unchanged** in shape IDs. Old group E (`GOSUB`, `7E3B`, `7F03`) is group F here.
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
