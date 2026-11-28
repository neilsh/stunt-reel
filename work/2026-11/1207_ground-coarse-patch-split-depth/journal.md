# Journal

## 2026-11-28: the coarse patches draw by split depth; four reference captures were missing

`[Bounded Observation]`, the code at the commit that adds `world/ground_split.rs`, on the WSL Ubuntu 24.04 lavapipe.

- **Question**: does drawing a coarse ground patch only past its `SP_GROUND` split distance and its finer patches within it (`PLAYONE.EXE` image `0x239C`, [`world-scene.md`](../../../research/playone-exe/world-scene.md) section 2) raise any reference film's `mean_ssim_scored`?
- **Track**: evidence-backed, image offset `0x239C`; no `--target` range, since the rule is the criterion.
- **Groups found** (`SCENERY.scn` and `MAP.BIN` of the corpus's FreeFlight copy, read by a throwaway test): 12 coarse patches, each matching exactly one `SP_GROUND` node by split distance (`c >> 1`), patch count and a centre within one raw unit of the coarse polygon's mean corner.
  Records 68 and 82 share a split distance and a patch count; their centres, 1,100 units apart, tell them apart.
  All 12 verify, so none keeps the old draw.
- **Depth unit**: the gate is the `SP_1NODE` branch gate with an extent that leaves its threshold at `splitdist`, so the depth word is the high word of the depth row, as for props, and `splitdist` is not detail-scaled.
- **Method**: `mise run sweep -- --var DBG_GROUND_SPLIT=0,1 --films intro,balloon,traintnl`, the switch uncommitted, on a data root whose `intro`, `balloon` and `traintnl` captures match their `references.toml` pins.
- **Result**: the two variants score the same to four decimals on each of the three films (intro 0.9247, balloon 0.9091, traintnl 0.9221); the worst frame moved by -0.0001 and no frame fell by more than 0.005.
  This is a subset with no verdict: the adoption rule judges every reference film.
- **Blocked**: the `ctry`, `land`, `bomb` and `location` captures in the data root no longer match their pins (the sweep stops with `it was replaced, so repin it in a reviewed commit or restore it`); the pinned captures are in the R2 archive `v2/captures-289c5e30f095da44.tar.zst`, which needs the R2 key pair this session lacks.
  Which films see the groups is untested here: the 12 centres lie from raw `(3275, 0, -7)` to `(-4317, -76, -4064)`, and the three films measured show no effect.
- **Verdict**: not judged. The change is committed on its branch and not adopted; `expected/lavapipe.toml` is not repinned.
- **Lives in**: nothing yet. On adoption, `world-scene.md` section 2 loses its `#1207` gap sentence.
