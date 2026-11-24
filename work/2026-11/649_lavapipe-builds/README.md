---
title: "Lavapipe builds are compared by score only, not pixel by pixel"
started: 2026-11-24
issue: 649
outcome: "Measured: mesa-dist-win 25.2.8 and 26.2.6, the canonical lavapipe and the GPU on all seven films of `crates` `d897adcc`, pixel by pixel and by score; recorded in `lavapipe.md` § 7. Step 4 (Ubuntu 26.04's Mesa 26.0.8) skipped."
---

# Lavapipe builds are compared by score only, not pixel by pixel

The [journal](journal.md) holds the measurement, with its raw figures in [`figures.txt`](figures.txt).

Spike step 4 (Ubuntu 26.04's `mesa-vulkan-drivers` 26.0.8 under WSL 2) was skipped: the machine's `Ubuntu` 26.04.1 distro had that Mesa and Rust from rustup on 2026-11-16 (#642's journal) and has no `mise` or `uv`, no checkout of the repository and no Linux-side data root, so it needs those set up first, and steps 1 to 3 already answer the issue's question with the canonical lavapipe as a third build.
Left open, in `lavapipe.md`'s open question 3: what sets LOCATION 722 and 780's band and BOMB 3446 to 3730's row.
