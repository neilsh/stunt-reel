---
title: "Readback copies each plane out one byte at a time, 17 to 32% of the render loop"
started: 2026-11-22
issue: 933
outcome: "read_back copies each readback row whole instead of byte by byte, cutting readback_copy 66.9%-92.0% on Windows lavapipe and 81.0%-86.7% on the RTX 4070 and loop wall 4.0%-28.4%, with all 28 stores on the seven reference films byte-identical and their scores unchanged on both adapters."
---

# Readback copies each plane out one byte at a time, 17 to 32% of the render loop

#931's post-#914 profile left `read_back`'s byte-at-a-time iterator as the largest phase with a planned fix: 17.2%-21.8% of the loop on Windows lavapipe and 26.6%-31.8% on the RTX 4070.
`20d8371f` reserves each plane's `Vec` once and appends each row's first `row_bytes` with `extend_from_slice`, keeping the signature and the `RunOnDrop` unmap guard.

- Probe: [#931's `probe.patch`](../931_post-914-render-profile/probe.patch), applied with `git apply`.
- Journal: [journal.md](journal.md), the timing sweep and the seven-film store check on both adapters.
- Next: nothing from this item; [open question 1](../../../research/parity/lavapipe-render-time.md#open-questions) keeps only the `FilmScene::frame` half.
