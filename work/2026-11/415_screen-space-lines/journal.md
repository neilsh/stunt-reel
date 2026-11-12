# Journal: SOD lines one pixel wide on screen

## 2026-11-11: the ZLINETO draw path read statically

- **Question**: What does `PLAYONE` draw for `MOVETO`/`ZLINETO`? `vm.rs` drew a segment as two 0.03 m world ribbons, a stand-in taken from the opcode names (`sod-opcodes.md` § 2.6).
- **Method**: The dispatch slots at image `0x8240 + opcode` (`26 C7 44 FE imm16`, target `imm16 + 0x8240`) read from the unpacked image `build/re/playone.img` in the data root (the unpatched build), then `mise run disasm` over the handlers and the routines they call: `0x968D..0x9696`, `0x9696..0x96A7`, `0x9BAA..0x9BB3`, `0xBB83..0xBCC1`, `0x7FD2..0x8010`, `0x7511..0x7571`; a byte search for writers of `work:0x807E`. The Patch #3 image was not read.
- **Result**:
  - `MOVETO` (`0x00A2`) is `0x968D`: `mov [0x41EC], ax`, the operand (a register's byte offset), and nothing else. `ZLINETO` (`0x00BD`) is `0x9696`: `BX = [0x41EC]`, `[0x41EC] = ` the operand, `call [0x807E]`. `LINECOL` (`0x00B4`) is `0x9BAA`, which stores its word at `[0x41EA]`. All three run with `DS` the work segment.
  - `0x9100` writes `work:0x807E` beside `work:0x8080`: `0x3994` at `0x914F` (with `0x4794` at `0x9155`) and `0x3943` at `0x9167` (with `0x42CE` at `0x916D`), VM-segment offsets, so image `0xBBD4` or `0xBB83`.
  - `0xBBD4` reads both endpoints' screen words from the register arena (`[reg + 0x4456]`, `[reg + 0x4458]`), clips the segment to the rectangle at `work:0x41C0..0x41C6` (`0xBBF3`, interpolating with `imul`/`idiv`; carry set when it is outside), and calls the gateway `0:7FD2`. `0xBB83`, the variant for the clipping case, was not read line by line.
  - `0x7FD2` loads `DI = [0x41EA]` (or `DI = 0` at `0x7FEB` when `work:0x806C` is set, the shadow draw) and calls the driver slot `DS:[0x2244]`, the third word of the table copied from `DS:0x10A4`: `0x7511`.
  - `0x7511` is a Bresenham line. It orders the endpoints by column (`cmp ax,cx`, `xchg`), sets `SI = ±320` by the sign of `dy`, and when `|dx| >= |dy|` stores `|dx| + 1` pixels with `stosb`, one per column, stepping a row when the error term borrows; otherwise `|dy| + 1` pixels, one per row (`dec si`, `adc di,si`). Both endpoints are drawn, the colour is the low byte of `DI`, and there is no depth test.
- **Verdict**: `ZLINETO` draws a one-pixel Bresenham line from the pen register to its operand register, with both endpoints and in the `LINECOL` colour: one pixel per column when `|dx| >= |dy|`, one per row otherwise. `[Established]` for the instructions of the unpatched image (static, not run). The pen is a register offset, so `PLAYONE` draws from the register's value at `ZLINETO` time; `vm.rs` keeps the point at `MOVETO` time. `0x7511` draws one pixel for coincident endpoints; whether the clipper `0xBBF3` passes such a segment was not read.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) section 8.10; [`memory-map.md`](../../../research/playone-exe/memory-map.md) sections 1 and 3; [`sod-opcodes.md`](../../../research/formats/sod-opcodes.md) section 2.6.

## 2026-11-11: one-pixel screen lines scored on the seven reference films

- **Question**: Does drawing every SOD line (`ZLINETO` and two-vertex `POLYZ`/`GVPOLY`/`GVPOLY16`) one Mode 13h pixel wide on screen, rather than as 0.03 m world ribbons, move the reference films' scores?
- **Method**: Commit `d0e1e911` (`crates` tree `b0c3846`): `vm.rs` emits each line as one two-vertex polygon, tessellation makes it a quad of zero world width whose corners carry the vector to the other endpoint (`SodVertex::flags` bits 3 to 5), and the vertex shader moves each corner half a pixel across the line's minor screen axis and half a pixel past its endpoint along the major one, so the rasteriser covers one pixel per column (`|dx| >= |dy|`) or per row, both ends included, as `0x7511` draws. A temporary `DBG_OLD_LINES=1` restored main's ribbons; `mise run sweep -- --var DBG_OLD_LINES=1,0 --no-build` scored both on all seven films. `mise run parity` on the clean commit gave the expected tables. Per-tick deltas from the two renders' `report.json` for `CTRY`, `INTRO` and `BALLOON`, and `mise run frame -- --var DBG_OLD_LINES=1,0` pictures of the largest movers. The switch is not committed. Track: evidence-backed (`0x7511` above; `sod-vm.md` § 8.9 for the two-vertex polygons, `[Supported Inference]`).
- **Result**:

  The ribbon column is the sweep's `DBG_OLD_LINES=1` render on the same commit, which reproduces main; it matches main's `references.toml` pins of #417 (measured on `c4e373a`) to four places. After merging main the `crates` tree is unchanged (`b0c3846`) and `mise run parity` gives the same seven scores.

  | Film | Ribbons | Screen lines | Δ |
  |---|---|---|---|
  | `CTRY` | 0.8996 | 0.9015 | +0.0019 |
  | `INTRO` | 0.8418 | 0.8437 | +0.0019 |
  | `LAND` | 0.8654 | 0.8662 | +0.0008 |
  | `BALLOON` | 0.8030 | 0.8097 | +0.0067 |
  | `TRAINTNL` | 0.8518 | 0.8548 | +0.0030 |
  | `BOMB` | 0.8101 | 0.8129 | +0.0028 |
  | `LOCATION` | 0.8068 | 0.8088 | +0.0020 |

  - Every `INTRO` camera 1 tick scored (lens 44236, ticks 1222–1288 and 2520–2619) gains 0.0034 to 0.0060. At tick 1244 the power line about 437 m away is drawn as two continuous one-pixel cables, as the capture draws it; the ribbons left scattered dots.
  - The largest per-tick gains are `BALLOON` 298 (+0.0561) and 496, `INTRO` 2443 and 1112, and `CTRY` 574 and 584 (+0.013). At `BALLOON` 364 (−0.0184) and 376 (−0.0115) the parachute's shroud lines go from several pixels wide to one, as in the capture; why that tick's score falls was not traced. At `INTRO` 848 (−0.0073) our render has a long line across the field where the capture shows a road elsewhere, so drawing it whole adds pixels the capture does not have there.
  - At `CTRY` 574 the shadow's tail boom, a line in the hero shape, is a one-pixel black line where the capture shows a filled shape; that difference is older than this change.
- **Verdict**: Adopted on the evidence-backed track: no film's score falls and all seven rise (it would pass the heuristic track too, `BALLOON` gaining more than 0.004). The expected `gpu` tables in `references.toml` are updated from `d0e1e911`.
- **Lives in**: [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) sections 8.9 and 8.10.
