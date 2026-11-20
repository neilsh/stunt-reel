# Journal: #624, `OP_BVGT` reads the angle bank

## 2026-11-19: `OP_BVGT` reads `bank.word(var)` at draw time and `location` rescores unchanged

- **Question**: does wiring `OP_BVGT` to read the angle bank at draw time pass the `stunt-core` contract tests and change `location`'s score under the current `PREVIOUS_FRAME_TICKS = 0.0`?
- **Method**:
  - Updated `Vm::bvgt` (`crates/stunt-core/src/sod/vm.rs`) to read `var`, record `var` in `DecodeRecord::bank_operands`, and branch when `self.bank.word(var) >= val` (unsigned, matching `PLAYONE` `0x9C23`).
  - Added `test_bvgt_branches_when_bank_word_is_at_or_above_threshold` in `crates/stunt-core/src/sod/vm_tests.rs`.
  - Rescored `location` on lavapipe (`mise run parity -- --films location --software-only`) and rendered capture-beside-render panels at ticks 837, 848 and 881 (`mise run frame -- --film location --ticks 837,848,881 --no-build --software-only`).
- **Result**:
  - `mise run check-rust` passes (5/5 steps).
  - `location`: `ssim 0.8383  iou 0.9796  idx 0.846  scored 732/745` (`expected.lavapipe` `0.8382851`, delta `-0.0000009` on `llvmpipe` LLVM 15 vs LLVM 20).
  - With `PREVIOUS_FRAME_TICKS = 0.0` (#693), bank word `0x12` is `0` at every tick, so `BVGT 0x12, 0x0FA0` still takes the fallthrough (solid-blade) arm on every frame.
  - Capture-beside-render panels: [`location_837.png`](images/location_837.png), [`location_848.png`](images/location_848.png), [`location_881.png`](images/location_881.png).
- **Verdict**: `BVGT` now reads the angle bank at draw time; `location` is unchanged under `PREVIOUS_FRAME_TICKS = 0.0`, and choosing the line arm on spun frames awaits a non-constant frame-spacing rule.
- **Lives in**: [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md#3-location-the-rotors-solid-blades-on-every-tick).
