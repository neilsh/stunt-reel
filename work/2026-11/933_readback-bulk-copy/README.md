---
title: "Readback copies each plane out one byte at a time, 17 to 32% of the render loop"
started: 2026-11-22
issue: 933
outcome: "read_back copies each readback row whole instead of byte by byte, cutting readback_copy 66.9%-92.0% on Windows lavapipe and 81.0%-86.7% on the RTX 4070 (12.1%-22.7% of each cell's before-loop); loop medians fell 4.0%-28.4% in a contention-driven scatter, so the copy cut is the figure to quote, and 28 of 28 stores on the seven reference films are byte-identical with unchanged scores on both adapters."
---

# Readback copies each plane out one byte at a time, 17 to 32% of the render loop

#931's post-#914 profile left `read_back`'s byte-at-a-time iterator as the largest phase with a planned fix: 17.2%-21.8% of the loop on Windows lavapipe and 26.6%-31.8% on the RTX 4070.
`97e0676e` reserves each plane's `Vec` once and appends each row's first `row_bytes` with `extend_from_slice`, keeping the signature and the `RunOnDrop` unmap guard.

- Probe: [#931's `probe.patch`](../931_post-914-render-profile/probe.patch), `git apply` on the control; the change's `read_back` body is rewritten from the patch by hand (`strip_pitch_padding` inside `t_copy`, with `drop(_unmap)` as the probe has it), as [the journal](journal.md#2026-11-22-row-wise-readback-copy-on-windows-lavapipe-and-the-rtx-4070) records.
- Journal: [journal.md](journal.md), the timing sweep and the seven-film store check on both adapters.
- Next: nothing from this item; [open question 1](../../../research/parity/lavapipe-render-time.md#open-questions) keeps only the `FilmScene::frame` half.
