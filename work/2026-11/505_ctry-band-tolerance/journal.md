# Journal

## 2026-11-16: Strict rule on ctry and per-index tolerances

**Question**: does `ctry`'s band follow #501's strict rule once 237 is dropped, and what does that cost its actor IoU (0.5405 recorded)? Would a per-index tolerance on the actor test restore sky bands on `intro` and `land` and make the probe less sensitive to edges, without admitting an actor's pixels into a band (#505)?

**Method**: `mise run parity` on `crates` tree `7aeabce` (every film matched `expected.gpu`, measured on `3449b7b`, to 1.1e-6), RTX 4070. A scratch script (not committed) repeated the [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou) snippet with the actor test `actor[i] == 0` replaced by `actor[i] <= N` (N = 2, 10, 100) or `actor[i] <= x * capall[i]`, where `capall` counts the index's capture pixels over every scored frame (x = 0.01 %, 0.1 %, 1 %). Each band was scored with `parity_probe.py iou`'s window and every-2nd-frame sample, at the #490 shifts (0,0), (0,-15), (0,+10), (+15,0), (+25,+25). The script puts the window around the moved silhouette. At (0,0) it reproduces `parity_probe.py iou` (`ctry` 0.5402 from both), but its shifted figures differ from the #490 journal's by up to 0.015 (`ctry` (0,-15): 0.1533 against 0.1677), so they are compared within this entry only. Track: heuristic, no image offset; no render change, so no sweep.

**Result**:

* *`ctry`.* On this tree the committed band scores 0.5402 (0.5405 was `d2cd090`'s). Dropping 237, `[[192,199],[228,236],[238,238],[161,165]]`, scores 0.5369 and covers 85.4 % (85.9 % before). Shift test, (0,0) / (0,-15) / (0,+10) / (+15,0) / (+25,+25): 0.5402 / 0.1533 / 0.1944 / 0.2015 / 0.0920 with 237, 0.5369 / 0.1516 / 0.1943 / 0.2004 / 0.0920 without. Rederived whole, the strict rule gives `[[162,164],[228,236],[238,238]]`, 25.0 % covered, and IoU 0.0879 / 0.1163 / 0.1141 / 0.1064 / 0.1232: every shift beats (0,0). Why the rest of #485's band fails, per index (share of capture rows 0..184 on frames `[0::4]`; share on layers 0 to 2; ground agreement):

  | Index | Capture share | On layers 0-2 | Agreement | Fails |
  |---|---|---|---|---|
  | 161 | 1.81 % | 0.75 | 0.98 | 85 % layer test |
  | 165 | 0.00 % | 0.10 | 0.00 | size, layer, agreement |
  | 192 | 0.03 % | 0.96 | 0.71 | size, agreement |
  | 193 | 7.81 % | 0.01 | 0.84 | layer, agreement |
  | 194 | 17.83 % | 0.00 | 0.81 | layer, agreement |
  | 195 | 0.50 % | 0.80 | 0.95 | layer |
  | 196 | 31.34 % | 0.00 | 0.59 | layer, agreement |
  | 197 | 0.01 % | 0.32 | 0.71 | size, layer, agreement |
  | 198 | 0.99 % | 0.00 | 0.00 | layer, agreement |
  | 199 | 0.02 % | 0.02 | 0.00 | size, layer, agreement |

  None of 161, 165 and 192-199 carries an actor pixel; 237 has 9 px in 3 frames.
* *Tolerances.* Bands, coverage, admitted actor pixels and IoU per film and rule are the table in [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou). Full shift rows, (0,0) / (0,-15) / (0,+10) / (+15,0) / (+25,+25):

  | Film | Rule | Shift test |
  |---|---|---|
  | `intro` | strict | 0.1488 / 0.1571 / 0.1504 / 0.1439 / 0.1425 |
  | `intro` | `n<=2` | 0.1500 / 0.1588 / 0.1512 / 0.1451 / 0.1430 |
  | `intro` | `n<=10` | 0.1542 / 0.1636 / 0.1536 / 0.1487 / 0.1439 |
  | `intro` | `n<=100` | 0.2244 / 0.1732 / 0.2024 / 0.1925 / 0.1710 |
  | `intro` | `s<=0.01%` | 0.1977 / 0.1636 / 0.1816 / 0.1732 / 0.1589 |
  | `intro` | `s<=0.1%` | 0.2604 / 0.1862 / 0.2162 / 0.2203 / 0.1770 |
  | `intro` | `s<=1%` | 0.2877 / 0.1961 / 0.2269 / 0.2383 / 0.1807 |
  | `land` | strict | 0.1879 / 0.1283 / 0.1276 / 0.1617 / 0.0983 |
  | `land` | `n<=100`, `s<=0.1%` | 0.2299 / 0.1418 / 0.1399 / 0.1923 / 0.0992 |
  | `land` | `s<=1%` | 0.2502 / 0.1574 / 0.1475 / 0.2102 / 0.1004 |
  | `location` | strict | 0.1161 / 0.1025 / 0.1092 / 0.1079 / 0.1117 |
  | `location` | `n<=100` | 0.1163 / 0.1023 / 0.1093 / 0.1076 / 0.1115 |
  | `location` | `s<=0.01%` | 0.1277 / 0.0870 / 0.1000 / 0.0958 / 0.0667 |
  | `location` | `s<=0.1%` | 0.1742 / 0.1099 / 0.1231 / 0.1214 / 0.0731 |
  | `location` | `s<=1%` | 0.2462 / 0.1169 / 0.1485 / 0.1522 / 0.0800 |
  | `bomb` | strict | 0.2708 / 0.1602 / 0.1538 / 0.1895 / 0.1216 |
  | `bomb` | `n<=10` | 0.2726 / 0.1611 / 0.1545 / 0.1906 / 0.1217 |
  | `bomb` | `n<=100` | 0.2744 / 0.1616 / 0.1553 / 0.1917 / 0.1218 |
  | `bomb` | `s<=0.01%` | 0.4220 / 0.1873 / 0.2094 / 0.2681 / 0.1138 |
  | `bomb` | `s<=0.1%`, `s<=1%` | 0.4370 / 0.1912 / 0.2119 / 0.2754 / 0.1140 |
  | `traintnl` | committed row | 0.3392 / 0.1735 / 0.2206 / 0.2155 / 0.1834 |
  | `traintnl` | strict | 0.3423 / 0.1766 / 0.2233 / 0.2170 / 0.1837 |
  | `traintnl` | `n<=2` | 0.3436 / 0.1767 / 0.2241 / 0.2173 / 0.1844 |
  | `traintnl` | `n<=10`, `n<=100`, `s<=0.1%`, `s<=1%` | 0.3535 / 0.1781 / 0.2293 / 0.2234 / 0.1875 |
  | `traintnl` | `s<=0.01%` | 0.3504 / 0.1756 / 0.2289 / 0.2219 / 0.1874 |

  Rules not listed for a film give its strict band. `balloon` gives its committed band under every rule (its candidates carry no actor pixel). `land`'s sky indices 229-238 carry 199 to 946 actor px each, in 50 to 95 scored frames; `intro`'s 236 carries 664 px in 46 frames.
* *Render dependence.* On this tree `bomb` 195 carries 140 actor px in 14 frames (1 px in 1 frame on `d2cd090`), and the strict rule gives `traintnl` 164 (0 actor px), which its committed row lacks. Other films' rows are out of #505's scope and were left alone.

**Verdict**: `ctry`: adopted, 237 dropped (IoU 0.5402 to 0.5369 on `7aeabce`); the ground ramp and shade greens stay, since rederiving whole leaves a probe in which every shift beats (0,0). Tolerance: rejected, strict rule kept. An edge-sized tolerance (`n<=10`) admits 5 to 26 px and leaves `intro` and `location` as undiscriminating as before; the tolerances that make them discriminate admit actor paint in 34 to 84 frames per index, and `land`'s sky returns only at `s<=1%` (3,111 actor px).

**Lives in**: [`probes.md` § 3](../../../research/parity/probes.md#3-actor-window-iou-iou) and the `ctry` row of `research/parity/references.toml`.
