# Journal: distilling `sod-vm.md`

The dated results of [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) as of commit `2a289b9`, moved here verbatim when the note was distilled to current truth. Only relative link paths changed; a section number in the moved text names a section of the note (`git show 2a289b9:research/playone-exe/sod-vm.md`).

## 2026-11-01: GVPOLY painted flat, and the running colour

From section 8.5:

The renderer first painted each such polygon flat at `base` plus the mean of its vertices' levels: grey-ramp pixels moved toward the capture's (`CTRY` 3.7k -> 33.8k against 52.4k, `INTRO` 120k -> 44.5k against 49.8k) but SSIM did not rise ([parity log](../../2026-10/parity-log/log.md)).

Before the ramp word was read, `INTRO.FLM` tick 1009 drew the triplane's fuselage grey and its wings bright pink where the capture has a red fuselage and dark red wings (capture above, ours below): [`intro-1009-gvpoly-running-colour.png`](../aircraft-render/images/intro-1009-gvpoly-running-colour.png).

_Found 2026-11-01 by the aircraft render round 2; see the [parity log](../../2026-10/parity-log/log.md)._

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: the SHADE light measured

From section 8.5, **The light**:

Measured with `DBG_SHADE_LIGHT`, all shapes decoded under one light: the stand-in 0.8646 / 0.7986 (CTRY / INTRO), the world light 0.8641 / 0.8128, its negation `(-99, -32766, 17)` and the 180-degree-about-Z form `(-99, -32766, -17)` both 0.8646 / 0.7986 (the 99 and 17 move no shade across a ramp step, so only the sign of y matters). The world light for scenery with the stand-in for actors scored 0.8646 / 0.7986 exactly: no scenery shade that reaches the screen moves, and the whole gain is on the aircraft.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: per-vertex GVPOLY index scored

From section 8.5, **Interpolation**:

The renderer now gives each vertex its own index (`base` plus that vertex's level, the fraction dropped) and interpolates it in screen space (`@interpolate(linear)`), rounding to a whole index per fragment (`[I3]`): CTRY 0.8641 -> 0.8642, INTRO 0.8128 -> 0.8166 (`DBG_GVPOLY_INTERP`).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.5.

## 2026-11-05: the facing sign measured

From section 8.6:

Measured 2026-11-05 ([parity log](../../2026-10/parity-log/log.md)): CTRY 0.8645 -> 0.8646, INTRO 0.7973 -> 0.7986; the opposite sign gives 0.8061 / 0.7366, which fixes the sign. The old reading (condition 1 as `D^2 <= 1000 m^2`, everything else drawn) had no binary basis.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.6 and Ruled out.

## 2026-11-06: the OP_VECTORS turn swept

From section 8.7, **Adopted**:

* **Parity** (sweep, RTX 4070): `CTRY.FLM` 0.8725 → 0.8986, `INTRO.FLM` 0.8273 → 0.8337, IoU unchanged. At `CTRY` tick 499 the biplane matches the capture, wing stripes included, which the hand-picked mirror culled ([log row](../../2026-10/parity-log/log.md)).

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.7.

## 2026-11-11: view-facing shapes scored

From section 8.8, **Adopted**:

At `INTRO.FLM` tick 2080 the hill pines, missing before, now stand facing the camera as in the capture; at tick 3301 the foreground pines still draw. `mean_ssim_scored` (RTX 4070 Laptop): CTRY 0.89960 → 0.89962 and INTRO 0.84177 → 0.84172, both under the 0.002 floor; of the other reference films only LOCATION moves by more than 0.0001, 0.80682 → 0.80800.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.8.

## 2026-11-11: lines scored

From section 8.10:

The change was adopted, every reference film's score rising, measured against main's ribbons restored by a temporary switch on the same commit: `CTRY` 0.8996 to 0.9015, `INTRO` 0.8418 to 0.8437, `LAND` 0.8654 to 0.8662, `BALLOON` 0.8030 to 0.8097, `TRAINTNL` 0.8518 to 0.8548, `BOMB` 0.8101 to 0.8129, `LOCATION` 0.8068 to 0.8088. Each of `INTRO` camera 1's scored ticks gains 0.0034 to 0.0060: its power line about 437 m away, drawn by `ZLINETO` spans, is two continuous one-pixel cables, as the capture shows, where the 0.03 m ribbons came to scattered dots.

**Lives in** [`sod-vm.md`](../../../research/playone-exe/sod-vm.md) § 8.10.
