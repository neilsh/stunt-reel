# Journal: edges a pixel off on the worst frames (#1168)

## 2026-11-28: the worst frames lose to the page they are paired with, not to edge placement

**Question.**
Which way, and by how much, do edges sit off the capture's on the seven frames #1168 names, and which candidate (page or camera, a clipper crossing, a deep anchor, edge-walk rounding, sprite placement, truncation still undrawn) explains the offsets?

**Method.**
`main` at `57c59687` (`crates/` tree `47d5603`), rendered on the canonical lavapipe under WSL (`llvmpipe (LLVM 20.1.2, 256 bits)`) with `mise run parity -- --films location,intro,bomb,land --software-only`.
The data root's `location`, `bomb` and `land` captures no longer match `research/parity/references.toml`, so the pinned `captures` archive (`v2/captures-289c5e30f095da44.tar.zst`, sha256 matching its pin in `manifests/cloud-assets.toml`) was downloaded with the owner's `wrangler` login into a private data root; all four films' captures there hash to their pins, and every film's score equals its `expected/lavapipe.toml` row to 0.0000001.
No capture hash or expected score was repinned.
Per frame: `parity-probe -- register --with-props` (render ticks ±4, page shifts ±6 px; [`data/register-*.txt`](data/)), then the new `parity-probe -- edges` ([`probes.md` § 12](../../../research/parity/probes.md#12-edge-offsets-edges)) at render offsets −2 to +4 from the page the scorer pairs (`--offset`; [`data/edges-offsets-*.txt`](data/)).
[`scripts/summarise_offsets.py`](scripts/summarise_offsets.py) sums each offset's mismatched pixels over the layer classes, picks the offset with the fewest and splits that offset's moves by side of the view centre ([`data/summary.txt`](data/summary.txt)).
Per-frame SSIM at a later page comes from `mise run parity -- --no-render --retime <k> --no-build` for `k` = 1, 2, 3, read by [`scripts/retimed_ssim.py`](scripts/retimed_ssim.py) ([`data/retime-ssim.txt`](data/retime-ssim.txt)); [`scripts/slot_words.py`](scripts/slot_words.py) prints the frames' slot words ([`data/slots.txt`](data/slots.txt)) and [`scripts/film_wide.py`](scripts/film_wide.py) counts, per film, the scored frames a later page raises by more than 0.05 ([`data/filmwide.txt`](data/filmwide.txt)).

**Result.**
Every frame still scores as the issue measured at `ff7f73b`, and none is dropped.
At offset +1 the `edges` mismatch counts equal the issue's index-map counts exactly on `location` 2003 (props 3,981, terrain 161, ocean 41), `location` 2080 (3,724, 69, 49), `intro` 1343 (actors 1,686, props 970) and `bomb` 2971 (props 11,999, actors 1,303, terrain 1,106), and at offset 0 on `intro` 2696 (2,938, 2,165), `intro` 1508 (actors 10,027) and `land` 540 (actors 3,830, uncovered 1,540; terrain 1,704 and props 896 against the issue's 1,714 and 880).
On each frame that offset lands on the tag (+1 where the scorer pairs the tag minus one, 0 where it pairs the tag), so the issue's sheets fit our page at the tag, not the page the scorer pairs; that page is the tag minus one on `location` 2003, 2080 and `intro` 1343 (`slot_clock` the tag minus one, `slot_ticks` 1) and on `bomb` 2971 (clock 2971, ticks 2).

| Frame | SSIM `ff7f73b` | SSIM `main` | `register` time; page | Mismatched as scored | Fewest, at offset | SSIM at offset +1, +2, +3 | Class |
|---|---|---|---|---|---|---|---|
| `location` 2003 | 0.691 | 0.6911 | +1 +0.085; 0, 0 | 9,929 | 4,183 at +1 | 0.8890, 0.6883, 0.5410 | page a tick off |
| `location` 2080 | 0.695 | 0.6954 | +1 +0.086; 0, 0 | 9,823 | 3,842 at +1 | 0.8902, 0.7529, 0.6257 | page a tick off |
| `intro` 1343 | 0.773 | 0.7729 | +1 +0.319; −1, −2 +0.358 | 5,344 | 2,656 at +1 | 0.9013, 0.7695, 0.6791 | page a tick off |
| `intro` 1508 | not given | 0.7678 | no backdrop edges | 10,664 | 5,517 at +2 | 0.8300, 0.8672, 0.5735 | page two ticks off, then sprite |
| `intro` 2696 | 0.810 | 0.8095 | +4 +0.438; −6, +3 +0.564 (440 px) | 5,103 | 3,570 at +3 | 0.8181, 0.8519, 0.8802 | page three ticks off |
| `land` 540 | 0.792 | 0.7920 | +2 +0.311; +1, −1 +0.332 | 7,979 | 7,979 at 0 | 0.7977, 0.8001, 0.7615 | page a row off (mixed with time by layer) |
| `bomb` 2971 | 0.810 | 0.8097 | 0 +0.000; −1, 0 +0.013 | 6,274 | 6,274 at 0 | 0.6157, 0.4668, 0.3950 | page a column off |

Over the seven frames the page with the fewest mismatched pixels has 34,021 against 55,116 as scored, 38% fewer, all of it on the five `location` and `intro` frames.
`register`'s `time` best (render tick ±4, no shift) agrees with the `edges` count's best offset on `location` and `intro` 1343; on `intro` 2696 it compares 440 backdrop pixels and takes +4 where the count and SSIM take +3.
Film-wide these frames are exceptions: a page one to three ticks later raises 3 of `location`'s 732 scored frames and 5 of `intro`'s 209 by more than 0.05, and none of `bomb`'s or `land`'s (earlier pages were not scored).

What is left at each frame's best offset, by side of the view centre (pixel centres against (160, 92.5); counts are four-neighbours where the capture shows our index, "toward" meaning nearer the centre on that axis; [`data/summary.txt`](data/summary.txt)):

* **One sign on both sides of the centre, on the world's layers.**
  `bomb` 2971's props lie a column left in the capture on both sides (left of the centre 1,098 left against 279 right, right of it 1,091 against 226) and mostly a row down (1,416 against 708 above, 971 against 634 below); its terrain the same way.
  `land` 540's uncovered sky, terrain, props and actors all lie a row up (sky 708 against 0; terrain 294 against 3 above the centre and 650 against 69 below).
  `location` 2003's props at +1 lie a row up on both sides (1,268 against 664 above, 607 against 112 below), and `intro` 1343's props a row up on both (134 against 9 above, 260 against 160 below) and a column left on the left (211 against 117 left of the centre), the right near even (128 against 100).
  The page shift that fits them gains little where it is the whole page's (`bomb` 2971 +0.013).
* **Away from the centre on both sides, on frames whose best page is not the paired one.**
  `location` 2003's props at +1 lie a column away on both sides (322 against 190 left of the centre, 251 against 164 right), and at +2 a column toward it on both (491 against 238, 434 against 177), which suggests the capture's page lies between our +1 and +2 there, `[Hypothesis]`: one sign flip on two frames, which a zoom, lens or per-slice interpolation difference could give too; a render at a camera interpolated half a tick on would test it.
  `location` 2080's props at +1 lie a column away on the left (301 against 161) and slightly on the right (312 against 240), and `intro` 2696's props at +3 a row away on both sides (68 against 9 above, 299 against 143 below; in x away on the left, 172 against 25, and even on the right, 49 against 41).
* **Toward the centre, on actors only.**
  `bomb` 2971's in x and y (130 against 45 left of the centre, 71 against 41 right; 321 against 48 above, 113 against 24 below) and `intro` 1508's in y (503 against 275 above, 974 against 183 below).
  `intro` 1343's and 2696's lie toward it in x on the left only (189 against 58 and 127 against 20), with the right even (119 against 114, 68 against 58); 2696's y is even too (7 against 4 above, 223 against 192 below).
  Their regions straddle the centre (`bomb` 2971's centroid 6.7 px left of it and 2.0 px above), so a capture actor narrower than ours and an actor truncated toward the centre give the same counts here.
  `intro` 1343's, 1508's and 2696's and `bomb` 2971's actor classes hold 1,686, 5,481, 2,482 and 1,227 mismatched pixels at their best offsets.
* **`intro` 1508's explosion sprite** lies a column left in the capture on both sides of the centre at +2 (1,257 against 206, 1,421 against 47), over its 5,481 actor pixels, while its props match (36 mismatched).

On `land` 540, `bomb` 2971 and `intro` 1343, no world-layer class of 100 or more mismatched pixels lies toward the centre on both sides of it on either axis at the frame's best offset, the signature of truncation the renderer does not yet draw.
`location` 2003 and 2080 cannot test it, since their props' sign in x follows the page: 2003's lie away on both sides at +1 and toward on both at +2 (above); on 2080 the right side goes from slightly away (312 against 240 at +1) to clearly toward (531 against 273 at +2) and the left from clearly away (301 against 161) to near even (339 toward against 267), so the sign follows the page on the right more than on the left, and in y its upper side lies up at both pages (1,510 against 444 at +1, 2,007 against 384 at +2) while its lower side goes from slightly down (532 against 378) to clearly up (958 against 111); `intro` 2696's props lie away on both sides in y at +3.
A deep anchor's precision loss cannot move a point by a pixel, from the instructions [`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre) cites: `0xB80E` shifts `z'` right by the fewest bits `n` that leave it under 2^15, so for `n ≥ 1` the divisor is at least 2^14, and the quotient then differs from `256 · x' / z'` by less than 2^-14 px for the floored `x'` plus less than 2^-14 of itself for the floored `z'`, under 257/16384 px (about 1/64) in all for an offset under 256 px from the centre, the clip volume's bound.
It can change a vertex's pixel only where the exact offset lies within about 1/64 px of a pixel's edge, so it cannot move thousands of a frame's edge pixels by a whole pixel.
The `region` lines give no clipper evidence: each frame's props or terrain form one region touching the view's border, so objects clipped at a view side cannot be told from interior ones.
Edge-walk rounding (wider or narrower than our fill) is not separated by this probe either, except where actors straddle the centre (above).

**Verdict.**
Control, nothing adopted.
The largest class, by mismatched pixels over the seven frames, is the page's timing: on five of the seven the page ADR 0057 pairs lies one to three ticks before the page with the fewest mismatched pixels, which has 30% to 61% fewer.
What is left after it is, on `land` 540, `bomb` 2971 and `intro` 1343's props, a page or camera offset of a row or a column with one sign across the centre; on `location`, a sign that follows the page, which suggests a capture page between two of ours (`[Hypothesis]`); and, on actors near the centre and the explosion sprite, offsets this probe cannot attribute.
No `PLAYONE` rule for vertex or edge placement results, so no renderer issue is filed; why the slot words name a page one to three ticks early on these frames is a follow-up.

**Lives in.**
[`framing-and-actors.md` § 4](../../../research/parity/framing-and-actors.md#4-background-misregistration-is-neither-one-time-offset-nor-one-page-shift), [`sod-vm-lines-spans.md` § 10 and Ruled out](../../../research/playone-exe/sod-vm-lines-spans.md#10-open-questions), [`sod-animate.md` Open questions](../../../research/playone-exe/sod-animate.md#open-questions), [`probes.md` § 12](../../../research/parity/probes.md#12-edge-offsets-edges).
