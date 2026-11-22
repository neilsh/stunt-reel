# Journal

## 2026-11-22: the polygon clipper read for a near plane

- **Question**: at what depth does `PLAYONE`'s polygon clipper cut a polygon that crosses the eye plane, in view units and in metres at each `scale_index`?
- **Method**: static, in the unpatched image, `main` at `9549ef5f`: `mise run re-tool -- disasm` over `0x9100 0x9180` (the object entry), `0x9CF1 0x9DB5` (both projectors), `0xC4C0 0xC6B8`, `0xC6AF 0xC8A0` and `0xC88E 0xC9D4` (the clipping vertex copier, its edge clipper and whole-view test) and `0x31CF 0x3230` (the view-position normaliser).
  Nothing traced live.
- **Result**:
  - `0x9100` puts the clipping projector `0x1AFA` (image `0x9D3A`) in `work:0x8082` and the clipping copier `0x42CE` (image `0xC50E`) in `work:0x8080` when its bounding test fails (`0x9167..0x9173`).
  - `0x9D3A` adds the origin words to a register for `(x', y', z')` and sets bit 0 for `z' ≤ 0` (`jle` at `0x9D50`), bits 1 and 2 for `x' ≥ z'` and `x' < −z'`, bits 3 and 4 for `y'`; behind the eye (`0x9D91..0x9DA9`) a side bit of each axis is always set too, since `x' ≥ z'` or `x' + z' < 0` holds for every `x'` when `z' ≤ 0`.
  - `0xC50E` drops an edge whose ends share an outcode bit, bit 0 included (`0xC596`), and hands each other edge with a flagged end to `0xC6AF`, which shifts the outside end's outcode right by 2 (`0xC6BF`) and so never reads bit 0.
    For each side bit it divides the outside end's distance to that plane by the edge's change in it (`div si` at `0xC6ED`, `0xC729`, `0xC764`, `0xC7A1`), keeps the largest fraction, interpolates the crossing (`0xC7B2..0xC7E3`, `0xC81B..0xC84C`) and writes it on a screen edge 256 pixels from the centre (`0xC802..0xC80F`, `0xC86B..0xC87B`).
  - When no edge survives and the outcodes OR to at least `0x1E` (`0xC5DA`), `0xC88E` fills the view if the polygon's cut by `x' = 0` (crossings from `0xC906`) crosses `y' = 0` at `z' ≥ 0` (`0xC8E2..0xC901`).
  - No instruction in `0xC50E..0xC9D4` compares a depth with a positive constant: depth enters through the side-plane distances and those sign tests.
  - So the clip volume is the pyramid `−z' ≤ x' < z'`, `−z' ≤ y' < z'`, apex at the eye: the cut is at depth 0 whatever `scale_index`, `work:0x806F` or the lens.
    The depth is quantised to one register unit, which `0x31CF` sets from the object's distance (`s` from the largest coordinate's magnitude, `0x31D5..0x3217`): for coordinates each under 16 m, `s ≤ 5` and the origin's unit is at most `2^-11` m before any halving in the rotation and the lens shift.
- **Verdict**: `PLAYONE` has no near plane; the renderer's needs one above 0, so the value is the least the depth buffer tolerates.
- **Lives in**: [`sod-vm-lines-spans.md` § 8.13](../../../research/playone-exe/sod-vm-lines-spans.md#813-the-clip-volume-has-no-near-plane).

## 2026-11-22: near planes nearer than 0.1 m on the evidence track

- **Question**: since `PLAYONE` cuts at the eye (the entry above), does a near plane nearer than our 0.1 m default score better?
- **Method**: `main` at `9549ef5f` with the temporary switch `DBG_NEAR` replacing `near_clip` in `compute_proj_matrix` ([`switches/DBG_NEAR.diff`](switches/DBG_NEAR.diff), #904's), on the RTX 4070 while another worker rendered on it.
  Track: evidence-backed (image `0xC6AF`, the clipper that has no near plane).
  Targets, quoted before the sweep: `--target bomb:1915-2048`.
  `mise run sweep -- --var DBG_NEAR=0.1,0.05,0.02,0.01 --track evidence --record work/2026-11/907_playone-near-plane --topic "near plane at the eye" --target bomb:1915-2048 --images work/2026-11/907_playone-near-plane/images --jobs 4`
- **Result**: the figures are [`sweeps/near-plane-at-the-eye.toml`](sweeps/near-plane-at-the-eye.toml); `mise run judge -- --recheck` on it prints the same winner line.
  Film means against 0.1 m:
  - 0.05 m: `ctry` −0.0000197, `intro` −0.0000358, `land` −0.0000116, `balloon` +0.0002016, `traintnl` +0.0000239, `bomb` −0.0000342, `location` −0.0000947; no frame falls by more than 0.005 (the worst −0.0029, `location` 3697), and `location` 3840 and 3862 rise by 0.0059 and 0.0067.
  - 0.02 m: `balloon` +0.0003465, the other six −0.0000358 (`traintnl`) to −0.0003438 (`location`); 2 frames fall by more than 0.005, both `location`, the worst −0.0055 at 2223.
  - 0.01 m: every film falls, −0.0001084 (`ctry`) to −0.0007458 (`location`); 39 frames fall by more than 0.005 (`location` 21, `intro` 7, `balloon` 6, `bomb` 5), the worst −0.0105 at `location` 2223.
  - The 13 `bomb` target frames score the same at all four values (target index change −0.0000 at each).
  `mise run frame --var DBG_NEAR=0.1,0.05` at `location` 3862 and `balloon` 738 (its film's largest rises, +0.0067 and +0.0036) shows no geometry 0.1 m cuts away: the changed pixels are the balloon flag's stripes and the castle's detail, where coplanar polygons tie in depth (judged by eye).
  Pictures: [`bomb-1915`](images/bomb-1915-near-plane-at-the-eye.png), [`bomb-1948`](images/bomb-1948-near-plane-at-the-eye.png), [`bomb-1981`](images/bomb-1981-near-plane-at-the-eye.png), [`bomb-2036`](images/bomb-2036-near-plane-at-the-eye.png) (capture, 0.1 m, 0.05 m).
- **Verdict**: "winner: DBG_NEAR=0.05 adopts (evidence, film means; target idx -0.0000 attribution; worst target frame -0.0000 bomb:2036) (noise floor +/-0.002; winner is ~within noise)".
  Not landed: the coordinator kept 0.1 m, since 0.05 m's largest film change (+0.0002) is a tenth of the 0.002 noise floor and comes from depth ties, while it halves `Depth24Plus`'s precision (1.2 m at 1 km) and ADR 0054 assumes 0.1 m.
  Whether to lower it is [#955](https://github.com/neilsh/stunt-reel/issues/955), for the owner.
- **Lives in**: [`attribution.md` § 2](../../../research/parity/attribution.md#2-current-breakdown), [`sod-vm-lines-spans.md` § 8.13](../../../research/playone-exe/sod-vm-lines-spans.md#813-the-clip-volume-has-no-near-plane).
