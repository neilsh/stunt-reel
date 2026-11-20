# SOD `ROT*` census and scenery posing: implementation plan (2026-11-18)

**Goal:** Measure every stock `.SOD` shape in the corpus that executes `OP_ROTX`, `OP_ROTY` or `OP_ROTZ` (split by placement role and view-facing flag), pose view-facing props per frame if any run `ROT*` (filing a follow-up issue if static `SCENERY.scn` props do), and record the findings in `research/`.

**Issue:** [#681](https://github.com/neilsh/stunt-reel/issues/681) (blockers [#271](https://github.com/neilsh/stunt-reel/issues/271) and [#693](https://github.com/neilsh/stunt-reel/issues/693) have landed on `main`).

---

## Global Constraints

- Never commit proprietary assets, executables or files from `corpus/`.
- Tests run offline on synthetic fixtures in `tests/fixtures/` or inline test builders.
- Conform to `[I1]`–`[I8]`.
- Keep `crates/stunt-core/src/contracts/shape/mod.rs` untouched (`DecodeRecord` stays unchanged).
- Start every Markdown sentence on its own line (`docs/development.md`), and never break inside a link or code span.
- Run a fresh reviewer pass (`AGENTS.md` § 3.5) on this plan before committing it and on `research/` edits before pushing, and run `mise run check` before committing code or finishing.

---

### Task 1: `stunt-core` `ROT*` and `SCENERY.scn` census helpers

**Files:**
- Modify: `crates/stunt-core/src/sod/vm.rs`
- Modify: `crates/stunt-core/src/sod/mod.rs`
- Modify: `crates/stunt-core/src/sod/vm_tests.rs`
- Modify: `crates/stunt-core/src/world/scenery/mod.rs`
- Modify: `crates/stunt-core/src/world/mod.rs`
- Modify: `crates/stunt-core/src/world/scenery/tests.rs`

**Steps:**
- [ ] In `crates/stunt-core/src/sod/vm.rs`:
  - Define `RotUse { pub opcode: u16, pub operand: u16 }` (`Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord`).
  - Define `RotAudit { pub header_flags: u8, pub rot_uses: Vec<RotUse>, pub stop: Option<SodStop>, pub returned_at: Option<usize> }` with `pub const fn faces_view(&self) -> bool` checking `HEADER_FACES_VIEW`.
  - Add `walk_all_bvgt: bool` and `rot_uses: Vec<RotUse>` to `Vm` (defaulting `walk_all_bvgt` to `false` in `run_vm` so `decode_sod*`, `trace_sod` and plain `sod-census` are unchanged).
  - In `Vm::rotate`, record each `(opcode, operand)` in `self.rot_uses` (sorted, without duplicates).
  - In `Vm::bvgt`, when `self.walk_all_bvgt` is `true` and `target = operand_at + rel < self.data.len()`, increment `self.subs_run` (flagging `SodStopReason::MalformedBranch` past `MAX_BRANCHES`), push `(target, self.current_visibility, self.visibility_scope_end)` onto `self.branch_resume`, and fall through so both arms execute (if `target` is out of range, flag `MalformedBranch` regardless of `val`).
  - Add `pub fn census_rotations(data: &[u8]) -> Result<RotAudit, SodError>` running `Vm` with `Policy::Census`, `walk_all_bvgt = true`, no anchors, `ShadeLight::WORLD_0X2D` and `AngleBank::REST`.
  - Re-export `RotAudit`, `RotUse` and `census_rotations` from `crates/stunt-core/src/sod/mod.rs`.
- [ ] In `crates/stunt-core/src/world/scenery/mod.rs` and `world/mod.rs`:
  - Define `SceneryShapes { pub shapes: BTreeSet<u16>, pub stop: Option<ScnStop> }` and `pub fn scenery_shape_ids(scenery: &[u8]) -> SceneryShapes`.
  - Walk `ScnWalk` with `LodChoice::Both` so both `SP_1NODE` far stand-ins (`obj != 0`) and near subtrees (`SP_LEAF` `obj != 0`) are collected, ignoring model filtering.
  - Re-export `SceneryShapes` and `scenery_shape_ids` from `crates/stunt-core/src/world/mod.rs`.
- [ ] Add unit tests in `vm_tests.rs` (both `OP_BVGT` arms walked regardless of `val`, `ROT*` deduplication, `OP_TAP` stepped over to reach later `ROT*`, `decode_sod` / `trace_sod` unchanged) and `world/scenery/tests.rs` (`SP_1NODE` stand-in + near `SP_LEAF` both collected, `0` skipped).
- [ ] Verify with `mise run test-rust -- -p stunt-core`.

---

### Task 2: `stuntreel sod-census --rot` CLI mode and `.RES` / `SCENERY.scn` joins

**Files:**
- Modify: `crates/stunt-cli/src/sod_census.rs`

**Steps:**
- [ ] Add `--rot` (`bool`) and optional `--scenery <FILE>` (`Option<PathBuf>`) to `Args`.
- [ ] Update `.RES` scanning in `scan_corpus`:
  - Keep plain `sod-census` data (`Scan::models`, `Variant::shape_ids`, `Variant::entry_names`, `Report::shaped`) untouched (including skipping region 0 in `scan.models`) so default `stuntreel sod-census` output stays identical.
  - Call `stunt_core::vfs::res_regions(&data)` per `.RES` file into a separate `--rot`-only `.RES` index map (`res_files` + `res_variants`).
  - When `regions.index < SHAPE_INDEX_LIMIT` (`0x80`) and regions count fits in `u8` (`1..=255`), assign shape ID `u16::from_le_bytes([item, regions.index])` to every region starting with `0x000C` (including region 0 / item 1 for scenery `.RES`, while naturally ignoring prop name tables that do not start with `0x000C`), without calling `link::shape_chunks` across duplicate packages.
- [ ] Auto-discover `SCENERY.SCN` (case-insensitive filename) during `scan_corpus`, or use `--scenery` if passed, keeping `(scn_path, bytes)` so resolution can match each `SCENERY.SCN` against the nearest ancestor package subtree holding `.RES` shapes first (falling back deterministically and reporting if an ID resolves to different model bytes across packages), and call `scenery_shape_ids` to record all scenery shape IDs and any `ScnStop`.
- [ ] Join placements across three sources:
  - Paired `.FLM`/`.TKE` actors via `<NAME>.ALL`, and unpaired `.FLM`/`.TKE` actors via nearest ancestor package `.RES` shapes (counting unresolved placements and `.RES`-resolved unpaired films separately).
  - `SCENERY.scn` shape IDs via nearest ancestor package `.RES` shapes (counting any unresolved IDs).
- [ ] Implement `--rot` report formatting for `--format text` and `--format markdown`:
  - Tally unique archive and loose `.BIN` models with `!rot_uses.is_empty()`, split orthogonally by placement role (`actor`, `scenery`, `actor+scenery`, `unplaced`) and `faces_view`, distinct `(opcode, operand)` pairs (calling out operand `0x12`), and any non-clean `census_rotations` stops or decode failures.
  - Render grouped rows by `(rot_uses, faces_view)` showing opcodes and operands, `faces_view` flag, role breakdown, variant count, folded shape IDs (including `.RES` IDs), loose `.BIN` names, and placed film / scenery counts.
- [ ] Add offline unit tests in `sod_census.rs` covering `--rot` text/markdown output, `.RES` `(res_index << 8) | item` including item 1 (region 0), `SCENERY.scn` `SP_1NODE` + `SP_LEAF` join, orthogonal role + `faces_view` split, and paired-`.ALL` vs unpaired-`.RES` film resolution.
- [ ] Verify with `mise run test-rust -- -p stunt-cli` and `mise run check-rust`.

---

### Task 3: Fetch Google Drive corpus and run the census

**Steps:**
- [ ] Download the 4 `corpus-*.tar.zst` archives from Google Drive via `gdrive readonly download` and unpack them into `$STUNT_DATA_ROOT/corpus/` matching `python/stunt_reel/dataroot.py`.
- [ ] Run `mise run sod-census -- --rot --format markdown` and `mise run sod-census -- --rot --format text`.
- [ ] Inspect every stock shape reporting `ROT*` (with `stuntreel sod-trace` for `.ALL` shapes as needed) to verify roles (`actor`, `scenery`, `view-facing`), bank operands (`0x10`..`0x1A`), and whether any `ROT*` reads operand `0x12` or `0x16`.

---

### Task 4: Conditional posing for view-facing props (or follow-up issue)

- [ ] **Branch A — if any view-facing scenery prop (`SceneFrame::view_facing`) runs `ROT*`:**
  - Verify whether any view-facing shape reads bank operand `0x16` or uses `OP_TAP` (`anchored` vs `streams` in `scene/shapes.rs`), and disassemble `PLAYONE`'s scenery draw loop before assuming `animate = 0`.
  - Retain view-facing streams needed for re-decoding in `FilmScene::load_with_timeline` (`crates/stunt-core/src/scene/film.rs`).
  - Populate `ActorDraw::bank` on `view_facing` draws in `FilmScene::frame` (`angle_bank(tick, 0, record.bank, previous).only(&decode.bank_operands)`).
  - Add a per-shape `lit_props` cache and `Target::LitProp` in `SceneRenderer` (`crates/stunt-render/src/scene_renderer.rs`) so all instances of a view-facing shape sharing `(light, bank)` in a frame decode and upload once.
  - Check `crates/stunt-gltf/src/scene_frame.rs` to confirm whether `view_facing` needs handling there (currently it exports static `frame.actors` only).
  - Add offline unit tests in `crates/stunt-core/src/scene/film.rs` and `crates/stunt-render/tests/gpu/scene_renderer.rs`, and run a lavapipe sweep/parity check (downloading `captures-*.tar.zst` from Drive if needed).
- [ ] **Branch B — if any static `SCENERY.scn` prop (`World::ir`) runs `ROT*`:**
  - File a follow-up GitHub issue (`gh issue create`) to split bank-posed static scenery out of `World::ir`.
- [ ] **Branch C — if neither scenery nor view-facing shapes run `ROT*`:**
  - Leave rendering code unchanged and record the negative finding.

---

### Task 5: Research notes, fresh review and quality gate

**Steps:**
- [ ] Add dated journal entries to `work/2026-11/681_sod-rot-census/journal.md`.
- [ ] Update `research/playone-exe/angle-bank.md` with the `[Bounded Observation]` `ROT*` census table, answer and close open question 1 (`0x12` with `ROT*`), and cite the journal via `_Source:_`.
- [ ] Update `research/playone-exe/sod-vm-execution.md` § 8.7 to reflect the census and posing result (`recording-findings`).
- [ ] Update `work/2026-11/681_sod-rot-census/README.md` `outcome` in the finishing commit.
- [ ] Have a fresh reviewer subagent read the `research/` diff, cited notes, census figures and linking docs (`docs/ARCHITECTURE.md`), resolving any issues reported.
- [ ] Run `mise run check -- --full` and confirm zero warnings or failures.
