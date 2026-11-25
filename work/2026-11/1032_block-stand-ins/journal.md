# Journal: BOMB's far town and `OP_BLOCK`

## 2026-11-24: the far town's stand-ins draw no `OP_BLOCK`

- **Question**: at `bomb` tick 1904, which `SP_1NODE`s cover the far town, which branch our gate keeps, and why does the stand-in it draws show no houses?
- **Method**: on `e2c191d0`, a temporary `eprintln!` in `CameraTransform::lod_keeps_subtree` and in the scenery walk's `SP_1NODE` arm, one render of tick 1904 on the RTX 4070 (`stuntreel --at-ticks 1904`); then `stuntreel shape-views` and `stuntreel sod-trace` on the stand-ins it names, and `mise run re-tool -- vm-handler 0x2D9` and `disasm 0xA405 0xA490` on the unpatched image.
- **Result**:
  - The town is 71 gates at 1904; the camera sits about 160 to 470 m short of it.
    Its city blocks are `SP_1NODE`s of `ext` 32 to 63 and `splitdist` 100 (threshold 99) at `CX` 111 to 234, so our gate draws their stand-ins `0x0669`, `0x066A`, `0x066B`, `0x066E`, `0x066F`, `0x06D6` and `0x06DD`; the one block it descends, at `CX` 92, draws its houses' own stand-ins (`0x067C`..`0x06A6`, `ext` 6 to 11, `splitdist` 17 to 32).
    Every gate's verdict and stand-in: [`lod-1904.txt`](lod-1904.txt).
  - `shape-views` draws `0x066E` as 10 trees and nothing else, yet its stream holds 41 `BLOCK` (`0x02D9`) ops in 51 `COLOR`s; `0x0669` and `0x066B` likewise.
    `vm.rs` reads a `BLOCK`'s two words and draws nothing.
  - `PLAYONE`'s handler `0xA405` is `OP_SPHERE`'s (`0x9DB5`) with a square: it reads `reg, size`, skips when the register's flag byte `+0x0A` is set, takes `h = ((size · work:0x8070) >> 8) / (z + work:0x8088)` as `OP_SPHERE` takes its radius, plots one pixel (`0x7FFB`) at `h = 0`, and otherwise passes the screen rectangle `(sx − h, sy − h)`..`(sx + h, sy + h)` to `0xBECE` and the flat filler `0x8010`.
- **Verdict**: diagnosis: the far houses are missing because our decode drops `OP_BLOCK`, not because the gate picks the wrong branch.
- **Lives in**: [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.4, [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8.

## 2026-11-24: `OP_BLOCK` drawn as a cube

- **Question**: does drawing each `OP_BLOCK` raise the reference films?
- **Method**: switch [`switches/DBG_BLOCK.diff`](switches/DBG_BLOCK.diff) on `e2c191d0`: `DBG_BLOCK=1` draws a `BLOCK` as a solid cube of half-side `size` about its register, in the current colour, both windings, the three-dimensional stand-in for `0xA405`'s screen square as `vm.rs`'s icosahedron is for `OP_SPHERE`'s disc.
  Evidence-backed track (rule: image `0xA405`).
  `mise run sweep -- --var DBG_BLOCK=0,1 --track evidence --record work/2026-11/1032_block-stand-ins --topic block-cube --target bomb:1585-1585 --target bomb:1904-1904 --images work/2026-11/1032_block-stand-ins/images` on the RTX 4070.
- **Result**: figures [`sweeps/block-cube.toml`](sweeps/block-cube.toml).
  `bomb` rises from 0.8949 to 0.8957 and `land` from 0.9245 to 0.9248; `ctry`, `intro`, `balloon`, `traintnl` and `location` stay at 0.9385, 0.8937, 0.9059, 0.9107 and 0.8863.
  The target ticks rise by 0.0022 in SSIM at `bomb` 1585 and 0.0036 at 1904, pooled index agreement +0.0013; 21 `bomb` frames outside them move by more than 0.005.
  One frame falls by more than 0.005, `location` 2894 by 0.0068: its far houses on the skyline gain red and white blocks a few pixels off the capture's ([picture](images/location-2894-block-cube-guard.png)).
  At 1904 the town shows red and white houses where the capture does ([picture](images/bomb-1904-block-cube.png); capture, baseline, `DBG_BLOCK=1`, rendered on `e2c191d0` with the switch).
  LAND 89 shows its largest gain, 0.0029 ([picture](images/land-89-block-cube.png); capture, baseline, candidate, rendered on `e2c191d0` with `DBG_BLOCK=0,1`).
- **Verdict**: adopted, evidence-backed film-mean branch: `bomb` and `land` rise, no film falls.
  The committed `block_polygons` keeps one winding per face, clockwise from outside, where the switch drew both; the near faces are the same, and the repin on the canonical lavapipe measures the committed code.
- **Lives in**: [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, [`prop-shape-loss.md`](../../../research/parity/prop-shape-loss.md) § 2.4.
