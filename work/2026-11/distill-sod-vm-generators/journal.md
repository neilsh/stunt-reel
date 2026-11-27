# Journal: distilling `sod-vm-generators.md`

The dated rounds and superseded results of [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) as of commit `714d723`, moved here verbatim when the note was distilled to current truth.
Only relative link paths changed.

## 2026-11-11: view-facing shapes scored

In `mean_ssim_scored` (RTX 4070 Laptop) `CTRY` and `INTRO` moved under the 0.002 floor; of the other reference films only `LOCATION` moved by more than 0.0001, 0.80682 → 0.80800.

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *Type-8 shapes turn with the camera's heading*.

## 2026-11-12: the disc's scale against a same-camera `BOMB` capture

`vm.rs` draws the disc as a 64-gon (the radius is checked, below; the count, under [the renderer's disc pixels](../../../research/playone-exe/sod-vm-generators.md#the-renderers-disc-pixels)) in the plane perpendicular to the raw register difference `regs[centre] − regs[axis]`, one face for each side, in the current colour, with `radius` in register units.
**Scale checked against a same-camera capture** ([#425](https://github.com/neilsh/stunt-reel/issues/425)).
`OP_SPHERE` shifts the radius product by 8 and divides by depth; this handler shifts by 16 (`0xA0A2..0xA0A6`: `imul [0x8070]`, high word) and leaves the perspective to the conic it builds, so the two shifts do not by themselves say the disc is 256 times smaller.
`BOMB` tick 2058 has a capture and a render from the same camera (the car body's left edge and the disc's centre column agree to 2 px), and the wheel disc's width agrees with `radius` in register units to about 2 px (one shape, ticks 2058 and 2070; a second shape is read below): at the rows 172 and 184 the capture is 77 and 91 px wide, the 16-gon 72 and 87 px, and a 64-gon 1 to 2 px under the capture; at tick 2070 the capture and the 64-gon differ by 1 to 2 px over four rows (`[Bounded Observation]`: two ticks, one shape, widths read off the palette index of the disc's flat colour).
The 16-gon is 4 to 6 % narrow and the 64-gon closes most of that gap; before [#898](https://github.com/neilsh/stunt-reel/issues/898) the remainder was unexplained, and [the renderer's disc pixels](../../../research/playone-exe/sod-vm-generators.md#the-renderers-disc-pixels) now gives `BOMB`'s wheel the capture's size.
A 32-gon, with the outline the disc then had, moved no film by more than 0.00015 SSIM and BOMB, LOCATION, LAND and INTRO fell (BOMB -0.00014), so it was not adopted then.
The `work:0x8108` rescale of the normal's depth difference (`0xA0DB..0xA0E8`) is `dz · 0x8108 · 2^(0x810C+1) >> 16`; with the view matrix's two screen rows scaled by `0x8108` in Q15 and the depth row shifted right by `0x810C` ([`memory-map-vm.md`](../../../research/playone-exe/memory-map-vm.md)), that makes the normal's three components share one scale, which `vm.rs` already has because it keeps the normal in the model frame, so no rescale is added (`[Supported Inference]`: read from the two sites, not verified live; a 2 px height gap at tick 2058 is unexplained).
The centre's depth is not rescaled: that is the lens squeeze below.

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *How the renderer draws the disc*.

## 2026-11-18: a `LOCATION` ground disc read on lavapipe and the GPU

**A ground disc, read on lavapipe and the GPU** ([#709](https://github.com/neilsh/stunt-reel/issues/709), [#689](https://github.com/neilsh/stunt-reel/issues/689); `[Bounded Observation]`, two ticks, one shape, widths read off index `0x4A`, the disc's flat colour, in both panels).
`LOCATION.ALL` shape `0x07C6` is one `OP_PERFDISK` of radius `0x2400` in colour `0x4A`, its normal along y: the stone circle's ground disc in `LOCATION.FLM`, lying flat and seen at a glancing angle across most of the screen, where `BOMB`'s wheel stands upright.
At ticks 6062 and 6161 (`mise run frame -- --film location --ticks 6062,6161 --software-only`, commit `9c9c6a5` (`crates/` tree `a00c4e7`)) the camera appears to match: the stones line up and the disc's far rim is row 76 in the capture, 77 in ours.
Stones stand on the rim, so only the ends a stone does not cover are read: at 6062 the right end of rows 106, 112 and 118 is at x 298, 300 and 299 in the capture and 299, 305 and 309 in ours; at 6161 the left end of rows 106, 112, 118 and 124 is at x 22, 19, 20 and 23 in the capture and 17, 14, 11 and 8 in ours.
The near rim is row 151 in the capture and 166 in ours.
So on this shape ours is the larger: it agrees at the far rim, reaches 1 to 15 px further at the sides and 15 rows nearer the camera, where on `BOMB` the 16-gon was 4 to 6 % narrow.
_Source: [the ground disc read on lavapipe](../425_perfdisk-radius/journal.md#2026-11-18-a-location-ground-disc-read-on-lavapipe)._
On the GPU (RTX 4070), at the same commit and ticks, every rim row and free end above reads the same as on lavapipe.
_Source: [the ground disc's widths re-read on the GPU](../689_perfdisk-depth-scale/journal.md#2026-11-20-the-ground-discs-widths-re-read-on-the-gpu)._

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *The lens squeeze*.

## 2026-11-18: the disc squeezed along depth by the lens zoom

At `LOCATION` ticks 6062 and 6161 the lens draws at 50.95° against the default 42.67°, a zoom of 0.820.

On lavapipe the near rim then reads row 153 at both ticks (capture 151, before 166), the far rim 75 and 76 (capture 76, before 77: still within 1 row of it, though 2 rows nearer the top at 6062), and the free ends of the rows quoted above 295, 299, 298 at 6062 and 21 on each row at 6161.
On the GPU (RTX 4070) the same rows and ends read identically.
_Source: [the GPU judge and rim re-read](../754_perfdisk-lens-squeeze/journal.md#2026-11-19-gpu-judge-and-rim-re-read)._
Adopted, evidence-backed: `LOCATION` rose by 0.0011 and the target frames' index agreement by 0.042; `CTRY`, `BALLOON` and `BOMB`, at the default lens, changed no frame, so `BOMB`'s wheel is as before; the other films moved by less than 0.00003.
The scores and pictures are in the journal.
_Source: [the disc squeezed along depth by the lens zoom](../754_perfdisk-lens-squeeze/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)._

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *The lens squeeze*.

## 2026-11-20: the shadow-mode skip adopted and the other skips scored

Of the skips, `vm.rs` reproduces the zero normal, and the renderer skips `FLAG_DISC` vertices (the disc triangles, and the `outline.rs` rim quads the disc had then) during actor shadow draws (`model.layer.y != 0`, reproducing `0xA045`), adopted evidence-backed on the seven reference films (RTX 4070: `intro`, `bomb` and `location` rose under +0.002, `land` and `traintnl` moved by −0.0000004, `ctry` and `balloon` unchanged; [#690](https://github.com/neilsh/stunt-reel/issues/690)).
The centre-depth (`0xA09A`) and eye-plane (`0xA156`) skips, tested for filled-disc triangles (`!FLAG_LINE && FLAG_DISC`, leaving `outline.rs` rim quads drawn) under temporary switches verified by positive controls, moved zero frames on the seven reference films and were not adopted (see Ruled out).
Scored against the seven reference films with `mise run parity` (RTX 4070).
_Source: [the handler read and the scores](../392_perfdisk/journal.md#2026-11-12-the-handler-read-to-its-end-and-drawn); [OP_PERFDISK shadow-mode skip](../690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-shadow-mode-skip-0xa045)._

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *How the renderer draws the disc*, and Ruled out.

## 2026-11-20: `INTRO`'s triplane wheels at a third lens, and the squeeze's bound

**A third shape, at 17.76°** ([#841](https://github.com/neilsh/stunt-reel/issues/841); `[Bounded Observation]`, four ticks of one shape on the GPU, widths read off the discs' flat colours in both panels).
Of every captured tick of `CTRY`, `LAND`, `INTRO`, `LOCATION` and `TRAINTNL`, the frame with the most disc pixels at a lens other than 42.67° and 50.95° whose camera matches the capture's shows `INTRO`'s triplane wheel at 17.76° (lens zoom 2.50); `LAND`'s at 11.16° hold at most 101 px of disc in a frame (tick 540, jet wheels 5 to 10 px across), and at `TRAINTNL`'s 14.84° ticks 232, 243 and 254 our train is not where the capture's is.
`INTRO.ALL` shape `0x7F04`, on the `IFVIS` branches these frames draw, draws a wheel as a tyre `OP_PERFDISK` of radius `0x0580` (colour `0x06`) and a hub of radius `0x0400` over it (`0x15` or `0x17`); other branches draw a lone disc of radius `0x0580` in colour `0x03`.
The discs' normal runs along the axle, so the wheel stands upright as `BOMB`'s does.
At 17.76° (ticks 1244 and 2553, `origin/main` `111970f`) the tyre's widest row is 16 px in the capture and 17 in ours, the hub's 9 and 11; at 42.67° (ticks 1101 and 2399) the near tyre's is 27 and 27 to 28, the hub's 19 and 20 at 1101 and 21 in both at 2399.
So the radius holds on this shape at both lenses to 2 px at those rows, ours never the narrower there: at 17.76° ours is 2 px (22 %) wider on the 9 px hub and 1 px (about 6 %) on the 16 px tyre, at 42.67° at most 1 px (about 5 %).
Below its widest rows, tick 1101's tyre is 3 to 4 px wider at rows 136 to 140 (capture 21, 17 and 11 px, ours 24, 20 and 15), which is the [#898](https://github.com/neilsh/stunt-reel/issues/898) offset.
The top rims agree to a row, but ours reaches 1 to 2 rows lower at the bottom of each disc whose bottom rim was read and is 1 to 3 rows taller in every disc whose rim rows were read (the 17.76° hub 9 × 8 px in the capture, 11 × 10 in ours).
So at 17.76°, at tick 1101 and on tick 2399's tyre ours was wider at the widest rows as well as lower at the bottom rim; [the renderer's disc pixels](../../../research/playone-exe/sod-vm-generators.md#the-renderers-disc-pixels) below gives the cause and the change ([#898](https://github.com/neilsh/stunt-reel/issues/898)).
These nearly face-on wheels barely feel the squeeze: forcing it to 1 changes 3 px of the frame at tick 1244 (17.76°), against 3,487 px at `LOCATION` tick 6062 at 50.95° (both measured for #841), so they test the radius at a telephoto lens but not the squeeze or the normal's depth rescale.
That control is at a different lens than the null results it supports: at the other lenses tested (`LAND` 11.16°, `TRAINTNL` 14.84°, `INTRO` 8.28°, `LOCATION` 22.10°) the switch moved 0 to 31 px of a frame on the ticks tested, and no large squeeze-sensitive disc was found there in the five films searched.
The seven films are bounded by [#754](https://github.com/neilsh/stunt-reel/issues/754)'s sweep, which scored their captured ticks with the squeeze off and on ([#899](https://github.com/neilsh/stunt-reel/issues/899); `[Bounded Observation]`, lavapipe, tree `191fa1a`, on a tree before #898, whose discs still drew a 16-gon fill with an unsqueezed one-pixel outline, so it bounds that renderer, not today's): it changed none of `CTRY`'s 121, `BALLOON`'s 108 or `BOMB`'s 339 ticks, which #754 puts at the default lens where the squeeze is 1, and outside `LOCATION`'s ticks 5953 to 6161 none moved by more than 0.00117 SSIM (`INTRO` 43 ticks, `TRAINTNL` 21, `LAND` 4, `LOCATION` 2).
_Source: [INTRO's triplane wheels](../841_perfdisk-third-shape/journal.md#2026-11-20-intros-triplane-wheels-at-the-default-lens-and-at-1776); [`BOMB`'s disc](../425_perfdisk-radius/journal.md#2026-11-12-the-discs-size-against-a-same-camera-bomb-capture); [the squeeze switch over seven films](../899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)._

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *How the renderer draws the disc* and *The lens squeeze*.

## 2026-11-22: the disc's pixels before and after #898

Before #898 the disc was a 16-gon drawn with the one-pixel outline every filled polygon gets ([`sod-vm-lines-spans.md`](../../../research/playone-exe/sod-vm-lines-spans.md) section 8.11), about its projected centre, which on our symmetric projection lies half a pixel below the top of row `92 + oy` for a centre `oy` pixels below the projection centre (`sky.rs`'s `to_pixel` takes the same centre).
Against `0xD11D` that adds a row from the outline, `2 · frac(r)` rows and columns from the untruncated radius `r`, and the centre's truncation, which is why `INTRO`'s wheels drew 1 to 3 rows taller, reached 1 to 2 rows lower and were up to 2 px wider, and `BOMB`'s wheel drew 62 × 62 against the capture's 61 × 60.

At the ticks read, every `INTRO` disc's rows are within a row of the capture's (the hubs at 1101, 2399 and 1244 and the 17.76° tyre exactly); `BOMB`'s wheel is 61 × 60 and 59 × 58 like the capture's, one row lower as before; `LOCATION`'s near rim is row 151 at both ticks as in the capture and its free ends lie within a pixel of the capture's on the rows no stone covers, while the two ends at 6161 that sit beside a stone lost their one-pixel sliver and the far rim gained a row above the capture's at both ticks (that row 9 px wide at 6062, 1 px at 6161).
Adopted, evidence-backed: on the GPU every reference film's SSIM rose or held (`location` +0.00038, `bomb` +0.00024, `traintnl` +0.00044, under the 0.002 noise floor) and one frame fell by more than 0.005 (`location` 6117, −0.0083), and lavapipe gave the same verdict on the same frame; the figures and pictures are in the journal.

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 8.8, *The renderer's disc pixels*.

## 2026-11-22: the ruled-out entries in full

* **`0xD11D`'s stepped ellipse or the disc's placement as the cause of `LOCATION`'s 15-row near rim** (section 8.8): not needed, since at ticks 6062 and 6161 the lens squeeze alone brings the near rim within 2 rows of the capture, keeps the far rim within 1 row and the free ends within 3 px ([the disc squeezed along depth](../754_perfdisk-lens-squeeze/journal.md#2026-11-18-the-disc-squeezed-along-depth-by-the-lens-zoom)); [#898](https://github.com/neilsh/stunt-reel/issues/898) draws its rows and centre for the smaller residues.
* **Dropping the disc's outline alone, for `INTRO`'s tall wheels** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): it takes a row off the top of each hub, not the bottom, so the hubs stay 1 to 2 rows taller than the capture's ([the disc's rows](../898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **Moving the disc up half a pixel, or onto `PLAYONE`'s centre pixel, without the truncated half-extent** (section 8.8, [#898](https://github.com/neilsh/stunt-reel/issues/898)): the hubs stay 1 to 2 rows tall, and as 16-gons both lose `LOCATION`'s ground-disc ends (the centre pixel alone dropped 7 `LOCATION` frames by more than 0.005) ([the disc's rows](../898_perfdisk-row-height/journal.md#2026-11-22-the-discs-rows-read-out-of-0xd11d-and-three-candidates-read-at-the-wheel-rows)).
* **`OP_SPHERE` faces wound counter-clockwise from outside** (section 8.8), the winding before #272.
  It draws only each sphere's far half; restoring it dropped 10 `LOCATION` frames by more than 0.005 and drew near tree crowns hollow where the capture fills them ([the sphere winding scored](../479_perfdisk-sliced-streamer/journal.md#2026-11-17-the-sphere-winding-scored-and-seen-beside-the-capture)).
* **`OP_PERFDISK` centre-depth skip (`< 0x80` signed, `0xA09A`) for filled-disc triangles on the seven reference films** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): under a temporary switch (`DBG_PERFDISK_ZMIN`) collapsing `!FLAG_LINE && FLAG_DISC` vertices (leaving `outline.rs` `FLAG_LINE` rim quads drawn) with `0x31CF`'s shift `s` mapped from `hi = floor(max |coord|)` in metres via 16.16 fixed point (`1 m = 1` in the high word, [`coordinates-and-units.md` § 2.1](../../../research/formats/concepts/coordinates-and-units.md#21-fixed-point-integer-bitfields), matching the magnitude up to 1 for negative fractional coordinates) and `work:0x810C`, the seven reference films scored identically to seven decimals and 0 frames moved; a one-frame positive control forcing `min_depth` 100,000x higher changed 4,178 px at `bomb` tick 2058 and 7,742 px at `location` tick 6062 ([the centre-depth sweep](../690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-centre-depth-skip-below-0x80-signed-0xa09a)).
* **`OP_PERFDISK` eye-plane skip (`0xA156`) for filled-disc triangles on the seven reference films** (section 8.8, [#690](https://github.com/neilsh/stunt-reel/issues/690)): under a temporary switch (`DBG_PERFDISK_EYEPLANE`) collapsing `!FLAG_LINE && FLAG_DISC` vertices (leaving `outline.rs` `FLAG_LINE` rim quads drawn) when the disc's minimum squeezed rim depth reaches the eye plane, the seven reference films scored identically to seven decimals and 0 frames moved; a one-frame positive control moving the eye plane 500 m forward changed 4,178 px at `bomb` tick 2058 and 7,739 px at `location` tick 6062 ([the eye-plane sweep](../690_perfdisk-skips/journal.md#2026-11-20-op_perfdisk-eye-plane-skip-0xa156)).
* **An actor disc's one-pixel outline left outside the lens squeeze** (section 8.8, [#899](https://github.com/neilsh/stunt-reel/issues/899)): the gap a static read of the vertex shader suggested needs outline corners that carry the disc flag, and a disc has had none since [#898](https://github.com/neilsh/stunt-reel/issues/898) (`outline.rs` `outlines`, test `a_disc_is_not_outlined`; [the outline read](../899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)).

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) Ruled out.

## 2026-11-22: the open questions as they stood

* **The other generators** (section 8.8, [#272](https://github.com/neilsh/stunt-reel/issues/272)).
  Closed: `OP_IPG` types 0, 2, 4 and 8 and `OP_SPHERE` read against their handlers, and type 6's operand width; `OP_VEC` has no handler.
  Closed by [#479](https://github.com/neilsh/stunt-reel/issues/479): type 6's registers (`BX` = 6, `DX` and `BP` as the previous handler left them; no model searched reaches it), the sphere faces against the captures, and `OP_PERFDISCSL` (no model searched uses a sliced op, so no disc is perforated).
  Closed by [#754](https://github.com/neilsh/stunt-reel/issues/754): the lens squeeze, the cause of `LOCATION`'s near rim.
  Closed by [#690](https://github.com/neilsh/stunt-reel/issues/690): the shadow-mode skip is applied (`0xA045`); under temporary switches verified by positive controls for filled-disc triangles, the centre-depth (`0xA09A`) and eye-plane (`0xA156`) skips moved zero frames on the seven reference films and remain unimplemented.
  Checked by [#841](https://github.com/neilsh/stunt-reel/issues/841): the radius on a third shape, `INTRO`'s triplane wheels, at 42.67° and 17.76° (four ticks, on the GPU; widest rows within 2 px).
  Closed by [#898](https://github.com/neilsh/stunt-reel/issues/898): the wheels' 1 to 3 extra rows, `0xD11D`'s rows and centre read and reproduced; open, whether `0xD11D`'s stepped spans below the centre row match the 64-gon's, which the rows read so far do not separate from the radius.
  Bounded by [#899](https://github.com/neilsh/stunt-reel/issues/899): the squeeze at the lenses the seven reference films' captured ticks use (`[Bounded Observation]`, lavapipe, tree `191fa1a`, scored SSIM and index agreement with the squeeze off and on, on a tree before #898, whose discs still drew a 16-gon fill with an unsqueezed one-pixel outline, so it bounds that renderer, not today's): `CTRY`, `BALLOON` and `BOMB` (default lens per #754, squeeze 1) changed no tick, and no tick outside `LOCATION`'s 5953 to 6161 (50.95°) moved by more than 0.00117 SSIM.
  The normal's depth rescale and the squeeze stay read but not verified live at any lens but 50.95°: the discs the captured ticks hold at other lenses are small (at most 356 px of a frame in the five films #841 searched), and the old-renderer sweep's changes there are at most 0.00117 SSIM, which may understate the effect on today's discs.
  _Source: [the squeeze switch over seven films](../899_perfdisk-lens-closeout/journal.md#2026-11-22-the-squeeze-switch-over-seven-films-and-the-disc-outline)._
  Closed by [#899](https://github.com/neilsh/stunt-reel/issues/899): a disc takes no outline since [#898](https://github.com/neilsh/stunt-reel/issues/898) (`outline.rs` `outlines`), so none escapes the squeeze.
  Open: whether actor `0x31CF` rounding changes any frame under `0xA09A` or `0xA156`; what `0xA1AB`'s term measures; and whether the archives outside this data root (the full `siarchive`) hold a sliced op or type 6.
  The type-8 trees are checked against `INTRO.FLM` ticks 2080 and 3301 and turn with the camera's heading (section 8.8, [#399](https://github.com/neilsh/stunt-reel/issues/399)).

**Lives in** [`sod-vm-generators.md`](../../../research/playone-exe/sod-vm-generators.md) § 10.
