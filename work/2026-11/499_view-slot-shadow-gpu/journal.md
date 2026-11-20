# Journal: #499 the view slot's shadow on the GPU and against `BRETT.FLM`

## 2026-11-20: the GPU judge, and the view slot's shadow against `BRETT.FLM`'s capture

**Question**: [#499](https://github.com/neilsh/stunt-reel/issues/499)'s local half after [#750](https://github.com/neilsh/stunt-reel/issues/710) (the view slot's shadow) and [#727](https://github.com/neilsh/stunt-reel/issues/727) (the code-8 box height) merged: does `mise run judge` on the GPU hold the seven reference films, and does the view slot's shadow reproduce the black band in `BRETT.FLM`'s capture?

**Method**: on `3ef1de54` (`crates/` tree `be47270`), local-windows, NVIDIA GeForce RTX 4070 Laptop GPU.
The baseline is the same tree with the view slot's shadow matrix dropped (`shadow_matrix: (a.casts_shadow && !a.view).then(...)` in `scene/film.rs`, a scratch edit not committed), which draws what the renderer drew before #750.
`mise run parity -- --jobs 4` on each, the reports copied, then `mise run judge -- <baseline reports> <candidate reports> --track evidence`.
For `BRETT.FLM`, which is not a parity reference, `stuntreel --headless` over the capture's tick range with the archive `captures/vault-brett/archives/BRETT.ALL`, and `stuntreel parity --reference captures/vault-brett/frames` on each render, once per tree; then the index-0 pixels of rows 150 to 184 counted on every captured frame, and `parity_probe.make_strip` for the pictures.
Round 2 lowered `DEFAULT_NEAR_CLIP` from 0.5 m to 0.05 m in a scratch build and rendered `BRETT.FLM` again; round 3 printed the view actor's eye, position and box top from a scratch `eprintln!` for ticks 430, 638 and 715 (the requested ticks 431, 639 and 716 print as 430, 638 and 715).
None of the scratch edits is committed.

**Result**:

- **GPU judge, seven reference films.** Candidate and baseline agree to four decimals on every film's SSIM and IoU (ctry 0.9190, intro 0.8629, land 0.8945, balloon 0.8842, traintnl 0.8635, bomb 0.8463, location 0.8395), index agreement is equal on every scored frame (0 better, 0 worse), no class loss moves and no frame falls by more than 0.005; the winner line is `none adopts (best run=candidate: no film rises)`.
  No reference film shows a view slot with a shadow, as [#510](../510_view-slot-shadow/journal.md) found, so this is a no-regression result.
  The depth ties of the shadow's 1 mm lift therefore went untested on the GPU: no reference frame draws a view slot's shadow.
  The same run's scores equal `expected/gpu.toml`'s to seven decimals, measured on `178c279`, so the gpu tables were repinned to `be47270` in their own commit.
- **`BRETT.FLM`, GPU.** `mean_ssim_scored` 0.8496017 without the view slot's shadow, 0.8498567 with it (+0.00026), IoU 0.98659176 for both, 123 of 130 frames scored, index agreement 0.869038 to 0.869073.
  One captured frame of 130 changes: tick 716, SSIM 0.8061 to 0.8375, index agreement 0.7922 to 0.7966.
  The capture's black band is 4,856 index-0 pixels in rows 150 to 184 on each of its 20 view-slot frames (ticks 409 to 452 and 606 to 761); ours is 0 pixels on 19 of them and 257 on tick 716.
  The pictures: [tick 639](images/brett-639-view-shadow.png) (no band in ours) and [tick 716](images/brett-716-view-shadow.png) (a thin black line along the bottom), each the capture, the baseline and the candidate left to right.
  So the view slot's shadow is drawn and moves the score the right way where it shows, but it reproduces about 5 % of the band on one frame and none on the rest.
- **Round 2, near clip 0.05 m.** Our rows 170 to 184 are the clear index (233, blue) on every view-slot frame, which `[Supported Inference]` is the ground nearer than the 0.5 m near plane, not drawn, where the capture has road under (or black over) it.
  With 0.05 m the road fills those rows, the index-0 count is 22 on 19 frames and 3,327 on tick 716, `mean_ssim_scored` falls to 0.8492168 (index agreement rises to 0.8708134), tick 716 gains a further 0.0266 and 19 frames move by more than 0.005, the worst down 0.0074 (tick 738).
  The band does not appear on the other 19 frames, so the near plane alone does not explain it.
- **Round 3, the view actor.** At ticks 430, 638 and 715 the camera eye equals the view slot's position (`y` 0.1509 m, the car's shape `0x415C`), the box-top probe returns none, and the slot's yaw is 90.00 degrees at 430, 89.94 at 638 and 88.24 at 715.
  Why the shadow's footprint vanishes on 19 frames while it reaches the bottom rows on tick 716 is not found.

**Verdict**: the GPU judge half is adopted as a no-regression result (the evidence track's film-mean branch has no film that rises, as for #750 and #834 on lavapipe).
The `BRETT.FLM` comparison does not confirm item 1: the shadow is queued and drawn, but its footprint on screen is about 5 % of the capture's band on one frame and nothing on 19, and no hypothesis of the three rounds explained it, so the rest goes to [#840](https://github.com/neilsh/stunt-reel/issues/840) rather than a fourth round.
Item 2 stays deferred ([#726](https://github.com/neilsh/stunt-reel/issues/726)) and item 3 is not exercised by `BRETT.FLM`.

**Lives in**: [`hero-shadow.md`](../../../research/parity/hero-shadow.md) question 10.
