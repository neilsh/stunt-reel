# Journal: the per-frame `SP_1NODE` gate and the lens exponent

## 2026-11-11: why CTRY drew no hill fins

- **Question**: Which `SP_1NODE` branch does `PLAYONE` take for the `OP_TAP` hill fins in `CTRY`'s airfield shot ([#394](https://github.com/neilsh/stunt-reel/issues/394)), and why does our walk take the other?
- **Method**: A temporary trace in `world/scenery.rs` printed every fin placement with the gates it stands behind, walking both branches of every node the camera path comes near (`DBG_LOD_FRAME=1`), on `CTRY` and `INTRO` at `1308da0` plus the change. View-space depth to each gate node came from the cameras in `build/parity/ours/ctry_current/render.json`.
- **Result**:
  - `0x0402`–`0x0404` stand behind one node: raw `(-128, 0, 3200)`, `ext` 2220, `splitdist` 2176. `0x0405`–`0x0408` stand behind raw `(3021, 0, 2173)`, `ext` 2954, `splitdist` 2500. `0x0202`–`0x0208` stand behind an outer node at raw `(1024, 0, -7168)` and inner nodes of `ext` 825 to 1173, which `CTRY`'s path stays too far from.
  - At tick 287 the two nodes are 2539 and 3831 m deep, against thresholds of 2175 and 2499 at the default lens. The static rule drew both stand-ins (path distance 3243 m against 1643), and so does the per-frame gate on the depth as `lod.md` section 2.2 read it. Halved, the depths are 1269 and 1915 and both subtrees are kept, on every tick from 270 to 309, which covers the runs (armed at 290 and 300) that saw `0x0402`, `0x0403`, `0x0406` and `0x0407` drawn.
  - A second cause hid the fins on both films: every placed fin (`0x0402`–`0x0404`, both films) failed with `AnchorOutOfRange { anchor: 81 }`. `shifted_anchors` failed a placement when any anchor of the table left `i16` once less the placement, but no fin taps anchor 81. That is why `INTRO`, whose walk did place `0x0402`–`0x0404`, never drew them, and why #254 saw no scored frame change.
- **Verdict**: Both fixed. The world now drops a TAP placement for an overflow only when an anchor its stream taps (read from `trace_sod`) overflows. The gate fix is the next two entries.
- **Lives in**: [`lod.md`](../../../research/playone-exe/lod.md) section 4.2; [`world-scene.md`](../../../research/playone-exe/world-scene.md) open question 3.

## 2026-11-11: the depth the gate compares

- **Question**: The fins need half the depth `lod.md` assumed. Does the code say so?
- **Method**: `mise run disasm` over `0x20A7..0x2160` and `0x88FB..0x895D` of the unpatched image (`mise run unlzexe`).
- **Result**: `0x0824:06B0` (image `0x88FB`) multiplies the point by each matrix row with `imul word` and sums into 32 bits; the depth row's sum is `DI:CX`. `0x20BF..0x211C` use `DI` as depth, and `0x211E` is `mov cx, di`: the gate compares the **high word**. A raw coordinate times a Q15 row is `2^15` times the rotated value, so the high word is half of it. The depth row is already shifted right by `0x229E` (`0x12F5..0x1303`). The frustum test confirms the units: `0x20E2..0x20EE` adds `ext >> (0x229E + 1)` to `DI`. So `CX = depth >> (0x229E + 1)`, and the true-depth threshold is `2^(0x229E + 1)` times `half + (splitdist − half) × 0x22A4 / 0x10000`. The Patch #3 image the captures ran was not decoded here (`unlzexe` finds no LZEXE 0.91 loader in `NewPLAY/PLAYONE.EXE`); `lod.md` section 1.2 has its patch site's bytes equal to the unpatched site's.
- **Verdict**: Adopted as the reading of `CX`. `[Established]` for the instructions; `[Supported Inference]` that the rows are Q15 and the accumulated position is relative to the eye.
- **Lives in**: [`lod.md`](../../../research/playone-exe/lod.md) section 2.2.

## 2026-11-11: rescoring the per-frame gate

- **Question**: Does the per-frame gate, with the lens exponent ([#255](https://github.com/neilsh/stunt-reel/issues/255)) and with the halving above, beat the static rule?
- **Method**: Evidence-backed track (image `0x2121..0x2147`, `0x211E`, `0x120A..0x124D`). One build with `DBG_LOD_FRAME` (0 static, 1 per-frame) and `DBG_LOD_EXP` (0 true depth, 1 shifted by `0x229E`, 2 shifted by `0x229E + 1`); `mise run sweep` on all seven reference films, RTX 4070. The adopted code, without switches, was committed as `123a2d9` and rescored with `mise run parity`, and compared against the static rule's render with `stuntreel parity --compare`.
- **Result** (mean SSIM over scored frames; `CTRY`, `INTRO`, `LAND`, `BALLOON`, `TRAINTNL`, `BOMB`, `LOCATION`):
  - Static rule (as rendered at `1308da0`): 0.8973, 0.8344, 0.8656, 0.8008, 0.8511, 0.7998, 0.7909.
  - Per-frame, true depth: 0.8961, 0.8339, 0.8555, 0.8014, 0.8403, 0.7900, 0.7822.
  - Per-frame, shifted by `0x229E`: 0.8961, 0.8340, 0.8565, 0.8014, 0.8489, 0.7900, 0.7832.
  - Per-frame, shifted by `0x229E + 1` (`123a2d9`): 0.8995, 0.8404, 0.8654, 0.8030, 0.8518, 0.8098, 0.8068. IoU 0.9902, 0.9857, 0.9849, 0.6352, 0.9655, 0.9090, 0.9783.
  - Changed frames, closer / further (verdict line): `CTRY` 99 / 17 of 121, `INTRO` 129 / 45 of 347, `LAND` 34 / 31 of 103, `BALLOON` 62 / 3 of 108, `TRAINTNL` 81 / 22 of 112, `BOMB` 209 / 47 of 339, `LOCATION` 516 / 114 of 745. Worst single ticks: `LOCATION` 4500 −0.030, `INTRO` 2103 −0.010, `BOMB` 3302 −0.0105, `BALLOON` 397 −0.010. Best: `LOCATION` 3862 +0.135. The compare sheet's most improved `LOCATION` tick, 5292, shows a ship the static rule had swapped for its stand-in.
  - `INTRO` camera 1 (lens 44236): the 7 scored ticks in 1216–1290 lose 0.0012 to 0.0023 each, the 10 in 2511–2624 lose 0.0012 to 0.0022; mean loss over the 17 is 0.0018.
- **Verdict**: Adopted, the `0x229E + 1` reading: no film falls by more than 0.002 (`LAND` −0.0002) and five rise by more than 0.002. The variants without the halving are rejected. The zoomed `INTRO` ticks are left open.
- **Lives in**: [`lod.md`](../../../research/playone-exe/lod.md) sections 4.1, 5 and 6; `research/parity/references.toml` expected tables.
