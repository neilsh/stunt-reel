# Journal: the SOD gates `BZLT`, `BVIS`, `REJVEC` and `REJ2D`

## 2026-11-12: the gate handlers

- **Question**: What do `BZLT` (`0x0318`), `BVIS` (`0x0183`), `REJVEC` (`0x01B0`) and `REJ2D` (`0x01C2`) do in `PLAYONE.EXE`, and where does a gated section end?
- **Method**: `mise run vm-handler` for each opcode's dispatch slot, then `mise run disasm` over `0x94D8..0x9640`, `0x9BB3..0x9C40`, the object entry `0x9100..0x9200`, `OP_VECTORS` (`0x9C51`), the projector `0x9CF1` and the normal routine `0xB621`, on `build/re/playone.img`. Writers of `work:0x806F` and `0x8088` came from `mise run xref`. The Patch #3 image (`mise run unlzexe` of `corpus/siarchive/Films/NewPLAY/PLAYONE.EXE`) was searched byte for byte for each handler.
- **Result**:
  - `IFVIS` (`0x9BCC`), `BVIS` (`0x9BB3`) and `BZLT` (`0x9BE5`) all skip with `add si, [es:si]` while `SI` points at the size word, so a section ends `size` bytes from the size word. `vm.rs` counted from the word after it, one word late.
  - `BZLT` reads `reg, val, size`. It computes `(val >> work:0x806F) - work:0x8088` and compares the register's z word (`+0x4454`) with it, signed (`jg`). Above runs the section; otherwise it is skipped. `work:0x806F` is `CH − CL`, stored at `0x9111..0x9113` by the object entry, and `OP_VECTORS` shifts each register's high word right by it (`0x9C5A..0x9C7C`).
  - `BVIS` is `IFVIS` with the test inverted (`je` where `IFVIS` has `jne`).
  - `REJVEC` reads `(p, b, e)` per face. It dots `e − b` with `p + o`, shifts the x and y products right by twice `work:0x810C` (`0x951E..0x9533`) and scales the z point term by `work:0x810A` (`0x953F`). The flag is the sign of the sum.
  - `REJ2D` reads `(a, b, c)` and computes `P2 − P1` on the projected words `+6`, `+8`, with `P1 = (a.x − b.x)(b.y − c.y)` and `P2 = (a.y − b.y)(b.x − c.x)`. The flag is the sign. The projector stores `(x + o.x) · 256 / (z + o.z) + centre`, and y the same, with no sign change.
  - The five gate handlers occur byte for byte in the Patch #3 image, at `0x87CF` (`REJVEC`), `0x88B7` (`REJ2D`), `0x8DBE` (`BVIS`), `0x8DD7` (`IFVIS`) and `0x8DF0` (`BZLT`). `REJ` and the projector differ only in a relative call.
- **Verdict**: `[Established]` for the instructions. For points in front of the eye, `REJ2D` is the `REJ` test of the same triple. `REJVEC` is `(e − b) · (p − eye)` in model space, the zoom undone. `BZLT`'s section runs while the register's true depth over `2^(1 + 0x229E)` exceeds `val` in the shape's metres. These three readings are `[Supported Inference]`, from algebra on the handlers. Implemented in `vm.rs` as `FacesEye` gates and the new `VisibilityCondition::BeyondDepth`, which `stunt-render` tests per frame.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.6; [`memory-map.md`](../../../research/playone-exe/memory-map.md) section 3 and section 1.1.

## 2026-11-12: which stock shapes reach the gates

- **Question**: Which stock shapes' census walks reach the four gates, or nest one section inside another? Does the corrected section end change any stock polygon's gate?
- **Method**: `mise run sod-census` (331 archives, 3,703 unique models) on this branch, with temporary switches, none committed:
  - `DBG_BVGT_BOTH` also walked the arm of each `BVGT` the walk does not take.
  - `DBG_NEST` printed each section that starts inside another.
  - A print listed the opcode word at each section's true end.
  
  `stuntreel sod-trace` on `INTRO.ALL` `0x7F09` checked the nesting print. A byte scan of the `.RES` files looked for the word `0x0318` followed by a multiple of 12.
- **Result**:
  - The census reports 0 models stepping over an unimplemented opcode, as before, with or without both `BVGT` arms. These runs were on the branch before the handlers went in, with `BZLT` and `BVIS` still skip-table entries (a reach is reported as a step-over) and `REJVEC` and `REJ2D` without a width (a reach stops the walk), so no walk reaches any of the four. The census on the final code reports the same counts.
  - With the handler's end, no section starts inside another. With the old end, `0x7F09` alone shows 90: back-to-back sections, each one word too long.
  - The words at the 120,375 true section ends are 102,536 `IFVIS`, 13,845 `RETURN`, 3,070 `SORTON`, 713 `LINECOL`, 79 `COLOR`, 37 `PUSHCENTRE`, 36 `BVGT`, 31 `IPG`, 24 `MOVETO`, 3 `GOSUB` and one `0x0333`. None draws by itself; the targets of the 3 `GOSUB` and 36 `BVGT` were not checked.
  - The byte scan matches `0x0318` hundreds of times. In the 12 contexts printed from `VEHICLES.RES`, each sits in a run of register offsets, as register 66 (`0x0318 = 66 × 12`); the rest were not classified, and the census, not the scan, is the evidence.
- **Verdict**: No census walk exercises the four gates or a nested section, and no drawing opcode starts at a corrected end. `[Bounded Observation]` for this walk: `BVLT` is not followed, and code no branch reaches is not walked.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.6; [`sod-opcode-coverage.md`](../../../research/formats/sod-opcode-coverage.md) section 3.1; [`attribution.md`](../../../research/parity/attribution.md) section 2 and Ruled out.

## 2026-11-12: scoring the section end and the gates

- **Question**: Does the corrected section end, with the new gates, move any reference film?
- **Method**: `mise run sweep -- --var DBG_IFVIS_END=0,1 --jobs 4`, where 0 kept the old end and 1 the handler's. Then `mise run parity -- --jobs 4` on the final code, compared with `references.toml`'s expected tables. RTX 4070 Laptop GPU.
- **Result**: Both sweep variants score CTRY 0.8996, INTRO 0.8417, LAND 0.8654, BALLOON 0.8030, TRAINTNL 0.8518, BOMB 0.8101 and LOCATION 0.8080, and the sweep warns that the variants tie. The switch was wired: the nesting print changes with it. The final code scores every film within 0.0000001 of its expected table: CTRY 0.8996226, INTRO 0.8417162, LAND 0.8653927, BALLOON 0.8029933, TRAINTNL 0.8518055, BOMB 0.8101363 and LOCATION 0.8080049, with the IoU unchanged. Those are the tables of the time, measured at `587a07ca` (crates tree `ac91b987`). After merging #420 the films were re-scored on the merged tree (crates tree `a3e940f8`, committed as `faf9535b`), and each matches #420's pin within 1e-7: CTRY 0.9015289, INTRO 0.8436601, LAND 0.8661891, BALLOON 0.8096847, TRAINTNL 0.8547746, BOMB 0.8129055 and LOCATION 0.8098241. `references.toml` pins that tree.
- **Verdict**: Evidence-backed track (image `0x9BCC`, `0x9BB3`, `0x9BE5`, `0x94D8`, `0x95C0`). No film falls and none rises, as expected when no census walk reaches the gates and no drawing opcode starts at a corrected end. The change is kept as a decoder fix that leaves the render as it was. Its scores need no new pin; after the merge `references.toml` repins only the `crates` tree to the merged one.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.6.

## 2026-11-12: the INTRO conifers

- **Question**: Are `INTRO.FLM`'s "conifers drawn as round bushes" (grader note on tick 3295, [`attribution.md`](../../../research/parity/attribution.md) section 2) a gate effect?
- **Method**: `mise run frame -- --film intro --ticks 3290,3301 --var DBG_IFVIS_END=0,1 --scale 2`, then a 160 × 100 crop of tick 3301's top left. Tick 3295 is not in the current capture; 3290 and 3301 are the nearest.
- **Result**: Ours draws conifers there, not round bushes, with or without the change. The capture shows a denser field of two-tone conifers past the `STUNT` letters, where ours has fewer, in one faint shade.
- **Verdict**: Not an effect of the four gates, which no census walk reaches. The round bushes went with [#399](https://github.com/neilsh/stunt-reel/issues/399)'s view-facing trees. The sparser field is filed as [#426](https://github.com/neilsh/stunt-reel/issues/426).
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 10.
