# Journal: #681, stock `ROT*` census and scenery/view-facing check

## 2026-11-19: corpus `ROT*` census finds no scenery or view-facing reader and no `0x12` rotation

- **Question**: which stock `.SOD` shapes execute `OP_ROTX`, `OP_ROTY` or `OP_ROTZ`, which angle-bank operands they read (in particular whether any read `0x12` or `0x16`), and whether any scenery (`SCENERY.scn`) or view-facing (`HEADER_FACES_VIEW`) shape executes `ROT*` and therefore needs per-frame bank posing?
- **Method**: on branch `feat/681-sod-rot-census` (implementing `stunt_core::sod::census_rotations`, `stunt_core::world::scenery_shape_ids` and `stuntreel sod-census --rot`), audited the local corpus (`stisldem`, `stuntisl`, `siarchive/Developer/FreeFlight`, `patches`).
  `census_rotations` walks every model under `Policy::Census` (`AngleBank::REST`, `ShadeLight::WORLD_0X2D`, no anchors), following `OP_GOTO`, `OP_GOSUB`, `OP_SORT` and both arms of `OP_BVGT`, and collects distinct `(opcode, operand)` pairs from `OP_ROTX`, `OP_ROTY` and `OP_ROTZ` alongside `HEADER_FACES_VIEW`.
  `.RES` scanning via `res_regions` includes region-0 `0x000C` shapes (such as `SCENERY1.RES`..`SCENERY6.RES` item 1) without altering plain `sod-census` counts.
  Placements join paired `.FLM`/`.TKE` files via `<NAME>.ALL`, unpaired `.FLM`/`.TKE` files via nearest-package `.RES`, and FreeFlight's `SCENERY.scn` (`scenery_shape_ids` with `LodChoice::Both`, keeping both `SP_1NODE` far stand-ins and `SP_LEAF` children) via nearest-package `.RES`.
  Ran `mise run sod-census -- --rot --format markdown`, `mise run sod-census -- --rot --format text`, and `mise run sod-census -- --format text`.
  Cross-checked `INTRO.ALL` shapes `0x7F04`, `0x7F09`, `0x7F19`, `0x7F1A` and `CTRY.ALL` `0x7F37` with `stuntreel sod-trace`.
  Because `OP_BVLT` (`0x02F4`) remains in `CENSUS_SKIPS` and unreachable code is not walked, ran a raw byte scan across all 1,504 `.SOD` regions of `SCENERY1.RES`..`SCENERY6.RES`, all 64 `HEADER_FACES_VIEW` shapes in `.RES`, all `.RES` models and the four `.ALL` archives (`CTRY.ALL`, `INTRO.ALL`, `SCENE01.ALL`, `HIGHWAYD.ALL`) for `0x01DD` (`ROTY`), `0x02E2` (`ROTX`) and `0x02EB` (`ROTZ`) words and 4-byte `ROT*` + `0x10`/`0x12`/`0x16` patterns.
- **Result**:
  - **Scope and walk health.**
    Across `31` archives (`21` in `stuntisl/RES/`, `6` in `siarchive/Developer/FreeFlight/SIDATA/`, `4` `.ALL` archives) and `0` loose `.BIN` models, `sod-census --rot` audited `2,473` unique models (`48` more than plain `sod-census`'s `2,425` because of region-0 `.RES` models).
    All `22` `.FLM`/`.TKE` films (`4` paired `.ALL`, `18` unpaired resolved via `.RES`) and `1` `SCENERY.scn` (`FreeFlight/SIDATA/SCENERY.scn`) joined cleanly with `0` unresolved actor IDs, `0` unresolved scenery IDs, `0` cross-package `.RES` conflicts (`stuntisl/RES/SCENERY1..6.RES` are byte-identical to `FreeFlight/SIDATA/SCENERY1..6.RES`), `0` model walk stops, `0` walk failures, `0` scenery stops and `0` unreadable files.
    Plain `sod-census` (`walk_all_bvgt = false`) reported `0` unimplemented opcodes stepped over across all `2,425` non-region-0 models (meaning `0` `OP_BVLT` step-overs on those walked paths).
  - **Role and `faces_view` split.**
    Of the `2,473` unique models, `54` execute `ROT*`: `46` `actor` (`0` `faces_view`), `0` `scenery` (`0` `faces_view`), `0` `actor+scenery` (`0` `faces_view`), and `8` `unplaced` (`0` `faces_view`).
    Of those `54`, `52` are `PLANES.RES` aircraft (`0x7F02`..`0x7F38`, `45` placed across the `22` corpus films and `7` unplaced there: `7F0C`, `7F2A`, `7F32`, `7F33`, `7F34`, `7F36`, `7F38`) and `2` are `MILITARY.RES` models: `0x3E57` (`Black Hawk Heli.#2`, placed in `LOCATION.FLM`, `ROTY 0x14`, `ROTX 0x14`) and `0x3E39` (`Sov. Mobile ICBM`, unplaced in the `22` films, `ROTX 0x18`).
  - **Operands used (`0x12`, `0x16` and `0x10` are never read by `ROT*`).**

    | Opcode | Operand | Unique `ROT*` models |
    | :--- | :--- | :---: |
    | `ROTY` | `0x14` | 1 |
    | `ROTX` | `0x14` | 1 |
    | `ROTX` | `0x18` | 22 |
    | `ROTX` | `0x1A` | 20 |
    | `ROTZ` | `0x14` | 24 |
    | `ROTZ` | `0x18` | 22 |
    | `ROTZ` | `0x1A` | 22 |

    Groups (`A`–`K`, all `faces_view = no`):

    | Group | `ROT*` uses | `faces_view` | Roles | Models | Shape IDs | Films placing |
    | :---: | :--- | :---: | :--- | :---: | :--- | :---: |
    | A | `ROTZ 0x14` | no | actor: 10, unplaced: 3 | 13 | `7F04`, `7F05`, `7F07`, `7F11`, `7F18`, `7F19`, `7F24`, `7F26`, `7F2A`, `7F2D`, `7F36`–`7F38` | 10 |
    | B | `ROTX 0x18`, `ROTZ 0x18`, `ROTZ 0x1A` | no | actor: 8 | 8 | `7F1F`–`7F23`, `7F2E`, `7F30`, `7F35` | 4 |
    | C | `ROTX 0x1A`, `ROTZ 0x18`, `ROTZ 0x1A` | no | actor: 6, unplaced: 2 | 8 | `7F02`, `7F0B`, `7F0C`, `7F12`, `7F16`, `7F1C`, `7F2B`, `7F34` | 2 |
    | D | `ROTX 0x18` | no | actor: 6, unplaced: 1 | 7 | `3E39`, `7F0D`, `7F0F`, `7F17`, `7F1D`, `7F28`, `7F29` | 2 |
    | E | `ROTX 0x18`, `ROTX 0x1A` | no | actor: 4, unplaced: 1 | 5 | `7F09`, `7F0A`, `7F10`, `7F1E`, `7F32` | 5 |
    | F | `ROTX 0x1A`, `ROTZ 0x14` | no | actor: 5 | 5 | `7F15`, `7F1A`, `7F25`, `7F2C`, `7F2F` | 4 |
    | G | `ROTZ 0x14`, `ROTZ 0x18`, `ROTZ 0x1A` | no | actor: 3 | 3 | `7F13`, `7F14`, `7F1B` | 3 |
    | H | `ROTX 0x18`, `ROTZ 0x14`, `ROTZ 0x18`, `ROTZ 0x1A` | no | actor: 1, unplaced: 1 | 2 | `7F06`, `7F33` | 2 |
    | I | `ROTY 0x14`, `ROTX 0x14` | no | actor: 1 | 1 | `3E57` | 1 |
    | J | `ROTX 0x1A` | no | actor: 1 | 1 | `7F0E` | 4 |
    | K | `ROTX 0x1A`, `ROTZ 0x14`, `ROTZ 0x18`, `ROTZ 0x1A` | no | actor: 1 | 1 | `7F27` | 2 |

  - **Raw byte cross-checks.**
    Across all `1,504` `.SOD` regions of `SCENERY1.RES`..`SCENERY6.RES`, zero aligned 16-bit words match `0x01DD`, `0x02E2` or `0x02EB` anywhere in the byte stream (two unaligned odd-offset hits in `0x058D` and `0x06DE` cross word boundaries).
    Across all `64` `HEADER_FACES_VIEW` shapes in `.RES` (`55` across `SCENERY1`..`SCENERY6.RES`, `8` in `GAME.RES`, `1` in `PRODTOOL.RES`), zero bytes at any offset match `0x01DD`, `0x02E2` or `0x02EB`.
    Across all `.RES` `.SOD` regions and the four `.ALL` archives, zero 4-byte patterns pair `ROTX`/`ROTY`/`ROTZ` with operand `0x10`, `0x12` or `0x16`.
    `stuntreel sod-trace` on `INTRO.ALL` `0x7F04` (`ROTZ 0014`, `BVGT 0012 0FA0 000A`), `0x7F09` (`BVGT 0018 3E80 0016`, `ROTX 001A`, `BVGT 0018 36B0 0016`, `ROTX 0018`), `0x7F19` (`ROTZ 0014`, `BVGT 0012 1F40 000A`), `0x7F1A` (`ROTX 001A`, `ROTZ 0014`, `BVGT 0012 1770 000A`), and `CTRY.ALL` `0x7F37` (`ROTZ 0014`, `BVGT 0012 1F40 000A`) matches the census walk.
- **Verdict**: negative finding on scenery posing, view-facing posing and `0x12`/`0x16` `ROT*` readers; rendering code stays unchanged (actors alone draw posed from the angle bank, and scenery and view-facing shapes stay at rest).
  The audit covers the 31 retail/demo/FreeFlight archives unpacked from the data-root corpus (not community loose `.BIN`/`.ALL` packages outside it, such as the full 331-archive `siarchive` tree).
- **Lives in**: [`angle-bank.md`](../../../research/playone-exe/angle-bank.md) § 5 (and `## Ruled out` / `## Open questions`), and [`sod-vm-execution.md`](../../../research/playone-exe/sod-vm-execution.md) § 8.7.
