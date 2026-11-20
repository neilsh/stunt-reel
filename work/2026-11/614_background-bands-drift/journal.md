# Journal

## 2026-11-20: Strict rule on every reference film after the sky drawer

**Question**: on current `main`'s render, do the committed `background` bands of the six non-`ctry` reference films still follow the strict rule of [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou)? On `crates` tree `7aeabce` (#505) the rule had admitted `traintnl` 164, which the committed row lacks, and `bomb` 195 carried 140 actor px (#614).
`ctry`'s row is held to the no-actor-pixel test alone (#505), so it was checked too.

**Method**: `mise run parity` on `main` at `b631982b` (#617 merged), `crates` tree `5ad0346`, RTX 4070; every film matched `expected.gpu` to 1e-7.
A scratch script (not committed) ran the § 3 snippet on each film and printed, for every index where the committed row and the rule disagree (and for chosen indices), its capture share, layer shares, ground agreement and our actor pixels over all scored frames.
It scored each band with `parity_probe.py iou`'s window and every-2nd-frame sample at #505's shifts (0,0), (0,-15), (0,+10), (+15,0), (+25,+25), with the window around the moved silhouette, as #505's script did.
At (0,0) it matches `parity_probe.py iou` to four decimals (`traintnl` 0.3424, and `balloon` 0.7143 and `ctry` 0.5391 with the new rows).
Track: none; no render change, so no sweep and no repin.
[#616](https://github.com/neilsh/stunt-reel/issues/616) closed with `CAPTURE_SKY_INDICES` still `227..=238` (it added the 224 to 226 zenith by position), so the rule's sky test is unchanged and no band needed rechecking against it.

**Result**:

* *Five rows already follow the rule.* Rederived, `intro`, `land`, `traintnl`, `bomb` and `location` give their committed rows exactly.
  The drift #505 saw is gone the other way: `traintnl` 164 now carries 1,376 actor px in 50 of 112 scored frames, so the rule leaves it out, as the row does; `bomb` 195 carries 145 px in 14 frames and stays out, as the row has it.
* *`balloon` 228 and `ctry` 236 now carry actor pixels.* `balloon` 228 (0.43 % of the capture) has 4 px in 3 frames; `ctry` 236 (0.76 %) has 6 px in 2 frames.
  Each fails only the no-actor test.
  Which change between `7aeabce` and `5ad0346` moved our actors' indices was not traced.
* *IoU, before and after*, with the shift test, (0,0) / (0,-15) / (0,+10) / (+15,0) / (+25,+25):

  | Film | Row | Covered | Shift test | Frames |
  |---|---|---|---|---|
  | `balloon` | with 228 | 57.3 % | 0.7237 / 0.5152 / 0.5861 / 0.5471 / 0.3947 | 52 |
  | `balloon` | `[229,238]` | 56.9 % | 0.7143 / 0.5115 / 0.5806 / 0.5443 / 0.3924 | 52 |
  | `ctry` | with 236 | 85.4 % | 0.5417 / 0.1534 / 0.1956 / 0.2012 / 0.0920 | 38 |
  | `ctry` | `[228,235]` | 84.6 % | 0.5391 / 0.1521 / 0.1956 / 0.2003 / 0.0920 | 38 |

  The unchanged rows score `intro` 0.1503 (89 frames, ratio 0.96, (0,-15) beats (0,0)), `land` 0.1886 (47, 0.52), `traintnl` 0.3424 (44, 0.53), `bomb` 0.2823 (129, 0.44) and `location` 0.0967 (78, 1.04: (+25,+25) scores 0.1002, above (0,0)).
  `ctry` rederived whole gives `[162,164] [228,235] [238,238]`, 24.3 % covered, IoU 0.0892, and every shift beats (0,0), as on `7aeabce`.
* *Sky indices stay out on `land` and `intro`.* `land`'s 229 to 238 carry 5,621 actor px (202 to 859 per index, in 49 to 95 frames); `intro`'s 227 to 238 carry 1,982, 784 of them at 237.
* *208 and the sky drawer.* Since #617 our render draws index 208 as sky below the lowest band edge, so capture 208 now falls partly on our layer 0: 46 % on `bomb`, 11 % on `balloon`, 7 % on `location`.
  The rule's sky branch admits only 227 to 238, so 208 would leave a band if over half of it fell on our sky, though PLAYONE's sky drawer paints it.

**Verdict**: `balloon` drops 228 (IoU 0.7237 to 0.7143) and `ctry` drops 236 (0.5417 to 0.5391), the strict rule's no-actor test applied as #505 applied it to `ctry` 237; the other five rows are unchanged, shown to follow the rule.
No capture `sha256` or `all_sha256` changed.

**Lives in**: [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou) and the `balloon` and `ctry` rows of `research/parity/references.toml`.
