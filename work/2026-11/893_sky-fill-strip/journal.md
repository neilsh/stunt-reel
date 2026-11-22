# Journal

## 2026-11-22: Where the sky drawer stops the 0xD0 fill, read statically

**Question**: Which row does `PLAYONE`'s sky drawer `0x8C45` stop its `0xD0` fill at, so that a capture rule can tell the fill strip from the 208 ocean below it?

**Method**: `mise run re-tool -- disasm 0x8C45 0x8F10` on the unpatched image (`corpus/stuntisl/PLAYONE.EXE`), read statically; nothing traced live, the Patch #3 image not read.

**Result**:
- The walk keeps the previous edge's endpoints in `work:0x7450..0x7458` and puts each edge it projects in `0x745C..0x7464` before `0x8E6C` fills between them (`0x8D64..0x8D73`).
- When the walk ends, by an edge off screen or after edge 14, `0x8D94..0x8DB6` sets the closing edge to the view rectangle's bottom row `work:0x41C6`, from its left pixel `0x41C0` to its right pixel `0x41C2`; when `work:0x80C8` is negative (the screen's vertical points the other way) it takes the top row `0x41C4` and swaps the ends.
  `0x8D0D` raised `0x41C6` by one before the walk and `0x8DBC` lowers it after, and `0x8E6C`, in the branch read (`0x8EA4..0x8EB3`, both `work:0x80C2` and `0x80C8` non-negative; the branches at `0x8F22` and `0x8F99` not read), fills to one row above the closing edge, so the last band reaches the view's last row (184 on a 185-row view, [`memory-map-vm.md`](../../../research/playone-exe/memory-map-vm.md) row `0x41C0..0x41C6`).
- After edge 14 the band counter `work:0x41B8` is 0, so that last band is the `0xD0` fill (`0x8E6C`, colour `0xEF - k`, `0xD0` at `k = 0`).
- So the drawer computes no horizon row for the fill: it paints everything from edge 14 to the bottom of the view, and only the scene, drawn after the sky, bounds the strip a capture shows.
  Where the scene's ocean is index 208 too ([`attribution.md`](../../../research/parity/attribution.md) section 5), strip and ocean meet with no other index between them.

**Consequence for the issue's rule**: below the edge-14 line, the first non-208 pixel in a column is the first scene pixel of another index, so where the captured ocean meets the strip, a rule that counts the column's 208 down to that pixel counts the ocean with it.
In a column where band 238 lies directly above the strip, that reach would match #844's column-run variant, which started from sky counted directly above rather than from the edge-14 line (the match is inferred, not tested), which lowered `location` by 0.0278780 and raised its `ocean_render_only` to 0.0013581 ([a roll-independent fill rule](../844_score-sky-as-sky/journal.md#2026-11-20-a-roll-independent-fill-rule)).
This run does not measure the issue's rule; it predicts the rule fails the issue's adoption bar on `location` unless a lower bound other than the first non-208 pixel stops it, and the only bound the drawer's geometry offers is the sea horizon, which #893 puts out of scope.

**Verdict**: Static finding recorded; the edge-line rule is neither built nor scored.

**Lives in**: [`palette-and-shading.md`](../../../research/formats/concepts/palette-and-shading.md#sky-bands), Sky Bands; [`memory-map-main.md`](../../../research/playone-exe/memory-map-main.md) row `0x8C45`; [`method.md`](../../../research/parity/method.md) section 2.0.
