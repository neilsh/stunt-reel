---
title: "A LOCATION render peaks at 1.1 GB and nothing says where it goes"
started: 2026-11-18
issue: 645
outcome: ""
---

# A LOCATION render peaks at 1.1 GB and nothing says where it goes

Issue #645; the cloud half is #705. The lavapipe breakdown, and freeing the world mesh after
upload (`FilmScene::release_world_mesh`, called by `run_headless`), are in
[`journal.md`](journal.md) and
[`research/parity/evidence-limits.md` § 3](../../../research/parity/evidence-limits.md#3-what-is-not-yet-evidence).

## Handoff

Left for a `local-only` follow-up on the RTX 4070 Laptop, which closes #645 and writes this
README's `outcome`:

- Peak and steady RAM (and VRAM) for LOCATION and CTRY on the GPU, before and after the PR that
  freed the mesh, beside the Linux figures in `evidence-limits.md` § 3.
- `frames.zst`, `layers.zst` and `palettes.zst` byte-identical before and after on the GPU over
  every reference film's captured ticks.

Not started: a smaller world vertex format. The world's three device buffers (257 MiB) are about
half of LOCATION's steady RSS once the mesh is freed, but the shader reads `normal` for the
world's 268,704 line vertices, so dropping it needs another way to draw them.
