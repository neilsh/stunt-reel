# Journal: #480 opcode numbering above `0x0333` on the two builds

## 2026-11-17: no census walk reaches the shifted opcodes, and `SOD.H` numbers the patched build

**Question**: [#480](https://github.com/neilsh/stunt-reel/issues/480), from [`patch3.md`](../../../research/playone-exe/patch3.md) Open question 1: the unpatched `PLAYONE.EXE` has 108 dispatch slots and Patch #3's 107, so an opcode word from `0x0345` up names a different handler on each build. Did Patch #3 re-encode the `.SOD` streams it ships, which numbering do the shipped streams use, and which build do the `SOD.H` names of [`sod-opcodes.md`](../../../research/formats/sod-opcodes.md) number?

**Method**: at `ce9fe79`, in a cloud session, on the data root's `builds/unpatched` and `builds/patch3` trees (`PLAYONE.EXE` `3c93493c…` and `fc532c94…`).

1. Every `RES/` file of the two trees compared byte for byte, and the items of the two `SPRITES.RES` compared item by item with `res_items` from [`superset_all.py`](../../../python/scripts/superset_all.py) (a one-off script, not committed).
2. `mise run sod-census` over the data root's `corpus/` (`stuntisl`, `stisldem`, `siarchive/Developer/FreeFlight`, `patches`).
3. The dispatch slots `0x0318..0x03C3` of both images followed to their handlers with `re_tool.slot_target` (`--vm-seg 0x754 --work-seg 0x14BF` for the patched image), and the handlers read with `mise run re-tool -- disasm` (`0xA228..0xA370` patched, `0x988F..0x98D0` and `0xB01D..0xB170` unpatched).

**Result**:

* **The patch replaces no `.SOD` stream.** Of the 27 `RES/` files, 24 are byte-identical; the other three are `SPRITES.RES`, `COMMNSND.SMP` and `SNDFX2.SMP`. The unpatched `SPRITES.RES` has 85 items and the patched 84. Items 1 to 83 are identical, the patched item 84 is the unpatched item 85 (1,670 bytes), and the dropped unpatched item 84 is a 9,398-byte `FORM`/`ILBM` image (320 × 200 in its `BMHD`). No item of either `SPRITES.RES` starts with the `.SOD` word `0x000C`. So both builds play the same `.SOD` bytes.
* **No census walk reaches an opcode above `0x0333`.** The census walked 31 archives: 2,425 unique models, 2,411 to `RETURN` with nothing stepped over, 14 stopping only at `TAP` for want of anchors, none stepping over or stopping at any other opcode. `vm.rs` handles no opcode above `0x0333`, so a walk that reached one would have stepped over it (a `CENSUS_SKIPS` entry) or stopped. The 2026-11-12 census of 331 archives in [`sod-opcode-coverage.md`](../../../research/formats/sod-opcode-coverage.md) § 1 (3,432 unique chunks) had the same outcome; only the loose `TESTTEXT.BIN` stopped, at `0x0333`.
* **The patched handlers match the `SOD.H` names in order.** Patched slots and handlers:

  | Opcode | Patched handler | What it does | `SOD.H` name |
  |---|---|---|---|
  | `0x033C` | `0xA349` | `call 0xA37B`, then the flat fill `0:7319` (unpatched `0:8010`) | `OP_VECELLIPSE` |
  | `0x0345` | `0xA357` | `call 0xA37B`, then reads one word `n` and stores the span table at `work:0x423E + n` (0 on failure) | `OP_VECELLSL` |
  | `0x034E` | `0xA228` | `int3` | `OP_LETTER` |
  | `0x0357` | `0xA229` | reads `count`, `reg`, then `count` pairs into the 2D words `work:0x4456`/`0x4458` of 12-byte registers | `OP_VECTORS2D` |
  | `0x0360` | `0xA246` | `BX = DX = 0` | `OP_CLR2D` |
  | `0x0369`, `0x0372` | `0xA24E`, `0xA25E` | load, store `BX`/`DX` from register `reg` | `OP_GET2D`, `OP_PUT2D` |
  | `0x037B`, `0x0384`, `0x038D` | `0xA273`, `0xA287`, `0xA297` | add then halve, add, subtract register `reg` | `OP_INT2D`, `OP_ADD2D`, `OP_SUB2D` |
  | `0x0396`, `0x039F` | `0xA2AF`, `0xA2BB` | `shl`, `sar` by the operand | `OP_SHL2D`, `OP_SHR2D` |
  | `0x03A8` | `0xA2C7` | `count`, `dst`, `src`: `count` registers set to `src` plus `BX`/`DX` | `OP_BLOKADD2D` |
  | `0x03B1` | `0xA2F4` | `reg`, `r`: `call 0xC144`, then the flat fill | `OP_CIRCLE` |
  | `0x03BA` | `0xA314` | `reg`, `r`, `n`: `call 0xC144`, then the span table stored at `work:0x423E + n` | `OP_CIRCLESL` |

  A 2D negate sits between `SUB2D` and `SHL2D` (`0xA2A7`, `neg bx; neg dx`); no slot from `0x0318` up jumps to it. The unpatched build has the same run one slot later (`int3` at `0xB01D` for `0x0357`, `VECTORS2D` at `0xB01E` for `0x0360`, `CIRCLESL` at `0xB109` for `0x03C3`, the ellipse pair at `0xB13E`/`0xB14C` for `0x0345`/`0x034E`) after its extra slot `0x033C` (`0x988F`). That handler skips eight bytes while `work:0x806B` is clear; in shadow mode (`work:0x806C` set) it fills flat through `call [0x8080]` and `0:8010`; otherwise it builds the polygon's edges with `0xC9D4`, writes the corner words `0x0000`, `0x1000` and `0x1F00` at `work:0x4252..0x4266` for two runs of `0xCA5D`, and draws through `0:77E5`, the same gating as `OP_TEXTURE` (`0x0333`, which skips ten bytes).
* **`OP_LETTER` has no handler on either build.** Its slot jumps to an `int3`, as `OP_HUGETAP`'s does, so it has no operand width; `CENSUS_SKIPS` gave it two words.

**Verdict**: adopted as findings. The patch re-encoded nothing: no `.SOD` stream changed, and no census walk reaches an opcode above `0x0333`, so the shift changes the drawing of no model the census walks (`[Bounded Observation]`, bounded by the corpora walked and by paths the walk does not take, such as the untaken arm of each `BVGT`). The `SOD.H` names number the patched build (`[Established]`, static: the handlers do what the names say, in order); on the unpatched build, an opcode `n` from `0x0345` up is the patched `n - 9`, and its `0x033C` is an opcode `SOD.H` does not name. `CENSUS_SKIPS` drops `LETTER` and takes `BLOKADD2D` (3 words) and `CIRCLESL` (3 words) from the patched handlers; the census counts do not change.

**Lives in**: [`patch3.md` § 4.1](../../../research/playone-exe/patch3.md#41-the-patched-build-has-one-dispatch-slot-fewer), [`sod-opcodes.md` § 1](../../../research/formats/sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes), `CENSUS_SKIPS` in [`vm.rs`](../../../crates/stunt-core/src/sod/vm.rs).
