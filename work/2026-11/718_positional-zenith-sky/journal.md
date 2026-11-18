# Journal

## 2026-11-18: A positional rule for the zenith sky

**Question**: which positional rule counts the capture's zenith sky at 224 to 226 as sky without counting the shape paint [#616](https://github.com/neilsh/stunt-reel/issues/616) attributed (`traintnl`'s wall rectangle and rear-car windows, `bomb`'s emblem, `location`'s helicopter windows), and what does it do to each film's `mean_iou_scored`?

**Method**: three rules on the 224 to 226 pixels, all applied over the 4-connected runs of 224 to 226 pixels of each capture plane: (A) the run reaches row 0 or touches a 227 to 238 pixel, the issue's candidate; (C) the run reaches row 0; (F) the run reaches row 0 and touches column 0 and column 319.
Pixel counts over every captured frame of the seven `VAULT` references, from the capture planes alone (a scratch script, not committed); crops of `location` tick 1090 and `traintnl` tick 265 looked at, with the counted runs marked (not committed).
IoU: one lavapipe render of all seven films (`mise run parity -- --software-only`, which reproduced every pinned lavapipe figure), then each rule built into `capture_sky_mask` and the same render re-scored (`mise run parity -- --no-render`).
A fourth rule for the sky the balloon cuts off, (G) F or a run overlapping the previous captured frame's sky, was counted on the capture planes only: the scorer scores frames one at a time.

**Result**: the table in [`method.md`](../../../research/parity/method.md) section 2.0 gives each film's IoU and counted pixels under A, C and F.

* A counts 1,469 `location` pixels mid-screen: on tick 1090, 38 pixels of 226 at rows 123 to 130 are the edge of a helicopter window whose glass is a 227 to 238 gradient, so the run touches the band.
  It also counts 1,023 `intro` pixels at rows 93 to 101 (not looked at) and `traintnl`'s 132.
* C counts 79 `traintnl` pixels at tick 265, rows 0 to 11, columns 30 to 41: a window of the red rear car, clipped by the top edge.
* F counts only `bomb`'s 59,520 zenith pixels (the top five rows, full width) and 1,039,844 of `balloon`'s 1,123,487; none on the other five films.
  IoU: `balloon` 0.6408895 -> 0.7185649, `bomb` 0.9128993 -> 0.9625786, the other five unchanged to seven digits.
* G adds 77,063 `balloon` pixels to F (16,983 and 15,119 on tick 243, 41,003 on tick 144) and none on any other film.

**Verdict**: adopt F: it is the only rule of the three that counts none of the attributed paint.
A and C are ruled out ([`method.md`](../../../research/parity/method.md#ruled-out)).
G is a follow-up, [#745](https://github.com/neilsh/stunt-reel/issues/745): it needs the scorer to carry each frame's sky mask to the next.

**Lives in**: [`method.md`](../../../research/parity/method.md) section 2.0; [`attribution.md`](../../../research/parity/attribution.md) section 7.
