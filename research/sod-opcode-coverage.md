# `.SOD` Opcode Coverage: Blocking-Opcode Work Queue

* **Evidence**: corpus census of every `.SOD` model in `corpus/**/*.RES` and `corpus/**/*.ALL`, run through the lenient evaluator in [`crates/stunt-core/src/sod/vm.rs`](../crates/stunt-core/src/sod/vm.rs).
* **Scope**: which shapes are Partial SODs, their blocking opcode, the masked opcodes behind it, and the order to implement them in. Terms follow [`GLOSSARY.md`](../GLOSSARY.md).
* **Tier**: `[Bounded Observation]` throughout (see § 4).
* **Owns**: the implementation queue for unhandled `.SOD` opcodes. Opcode semantics and operands stay in [`formats/sod.md` § 3.2](formats/sod.md#32-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes); binary evidence stays in [`playone-exe/`](playone-exe/).

The census in § 3 was hand-run on 2026-10-23 with a throwaway hook in `vm.rs`, since reverted. It will be replaced by the output of a committed `stuntreel sod-census` tool (§ 5).

---

## 1. Summary

Of 3,432 unique `.SOD` models (deduplicated by content across 309 archives), 3,368 decode to `OP_RETURN`. 63 stop: 14 at `OP_TAP` only because no anchor table was supplied (a census artefact, not a gap), and 49 at an opcode the evaluator does not implement. Seven opcodes account for every stop:

| Opcode | Mnemonic | Seen as | Operands assumed for the skip (from § 3.2) |
| :---: | :--- | :--- | :--- |
| `0x007E` | `OP_PUSHCENTRE` | blocking | none |
| `0x0090` | `OP_MOVECENTRE` | masked behind `PUSHCENTRE` | `reg_off: u16` |
| `0x0144` | `OP_SHADE1` | blocking | `normal_reg: u16, ramp: u16` |
| `0x01A7` | `OP_GOSUB` | blocking | `rel_offset: i16` |
| `0x01F8` | `OP_ANIMATE` | blocking | `reg_off, parameter, selector, count: u16`, then `count` resource IDs |
| `0x02FD` | `OP_BVGT` | masked behind `PUSHCENTRE` | `reg: u16, val: i16, rel_off: i16` |
| `0x022E` | `OP_TAP` | blocking without anchors | implemented; see [`sod-vm.md`](playone-exe/sod-vm.md) |

`OP_POPCENTRE` (`0x0087`) was never reached: every model that pushes a centre stops at `MOVECENTRE` first. Treat it as masked and implement it with the centre stack.

No other unimplemented opcode from § 3.2 was reached by any model under the limits in § 4.

---

## 2. Work Queue

Ordered by models unblocked, with film use noted where known. Each item's done-check is that its models decode with no stop in a lenient run, and that the next census shows no new masked opcode behind it.

| # | Implement | Unblocks | Film use known | Prerequisite | Evidence for semantics |
| :---: | :--- | :---: | :--- | :--- | :--- |
| 1 | `OP_ANIMATE` | 20 | `Ac.flm` drives `0x0105`, `0x0108` via `SIF_ANIMATES` | none | `[Established]` dispatch and blit, [`sod-animate.md`](playone-exe/sod-animate.md); selector and `.FLM` mapping open |
| 2 | Centre stack: `PUSHCENTRE`, `MOVECENTRE`, `POPCENTRE` | 13 | none known | none | community table only |
| 3 | `OP_BVGT` | 10 | `INTRO.FLM` places `0x7F09` ([`parity-findings.md`](parity-findings.md)) | item 2 | community table only |
| 4 | `OP_SHADE1` | 4 | none known | none | community table; `OP_SHADE2` is `[Hypothesis]` in [`formats/INDEX.md`](formats/INDEX.md) |
| 5 | `OP_GOSUB` | 2 | none known | none | community table; subroutine bodies were not scanned (§ 4) |

For `INTRO.FLM` parity, items 2 and 3 together outrank item 1: `0x7F09` needs both.

Item 2 may expose further masked opcodes: `MOVECENTRE` was the last opcode the census could reach in those 23 models.

---

## 3. Census (hand-run 2026-10-23)

<!-- Replace this section with `stuntreel sod-census --format markdown` output once the tool lands. -->

Models are listed by shape ID (`MODEL_xxxx.SOD`).

| Group | Unimplemented opcodes in order | Ends at | Models | Shape IDs |
| :---: | :--- | :--- | :---: | :--- |
| A | `ANIMATE` | `RETURN` | 20 | `0105`–`010C`, `3A80`, `7C06`, `7C14`, `7C1B`, `7C1C`, `7C2C`, `7C2D`, `7C2E`, `7C34`, `7E22`, `7E26`, `7E49` |
| B | `PUSHCENTRE` | `MOVECENTRE` | 13 | `6403`, `6405`, `6407`, `6408`, `640C`, `640D`, `6411`, `6414`, `6415`, `6416`, `641B`, `7F18`, `7F1B` |
| C | `PUSHCENTRE`, `BVGT` | `MOVECENTRE` | 10 | `7F02`, `7F09`, `7F0F`, `7F1C`, `7F20`, `7F21`, `7F22`, `7F29`, `7F2C`, `7F32` |
| D | `SHADE1` | `RETURN` | 4 | `7E17`, `7F0A`, `7F2A`, `7F38` |
| E | `GOSUB` | `RETURN` | 2 | `7E3B`, `7F03` |
| — | `TAP` (no anchors supplied) | `RETURN` | 14 | `0202`–`0208`, `0402`–`0408` |

---

## 4. Limits

* **Linear walk.** Branches, `GOTO` and `GOSUB` are skipped over, not followed, and the walk ends at the first `OP_RETURN`. Code after the main `RETURN`, including `GOSUB` targets, was not scanned and may hold further masked opcodes.
* **Assumed operand widths.** Skips use the widths in [`formats/sod.md` § 3.2](formats/sod.md#32-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes), which come from `SOD.H`, not the binary (`OP_ANIMATE` and `OP_TAP` excepted). A wrong width desynchronises the walk, so a group's "ends at" opcode may be an artefact; group B is the likeliest case.
* **Keyed by shape ID.** Where archives carry different bytes under one ID, the last one scanned is reported. This moved `7E22` from `SHADE1` (first census) to `ANIMATE`; both variants exist.
* **Loose `.BIN` models not scanned.** Compiled SODs stored as `.BIN` beside `MAP.BIN` (see [`verify_schemas_corpus.py`](../python/scripts/verify_schemas_corpus.py)) were outside this census.

A group's tier moves to `[Established]` once its opcodes have real handlers and its models decode to the end.

---

## 5. Regenerating

Pending: a `stuntreel sod-census` subcommand and `mise run sod-census` task (corpus-only, like `verify-corpus`). Its design, as agreed:

* `vm.rs` gains a walk mode that skips unimplemented opcodes by a width table kept beside the real handlers; implementing an opcode deletes its skip entry.
* Scans `.RES`, `.ALL` and loose `.BIN` models, reports per-shape blocking and masked opcodes, and joins each blocked shape to the `.FLM`/`.TKE` films that place it.
* `--format markdown` prints § 3, which is pasted here in place of the hand-run table.
