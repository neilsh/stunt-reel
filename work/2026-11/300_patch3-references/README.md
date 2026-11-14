---
title: "Reference films are captured on the unpatched builds, not Patch 3"
started: 2026-11-08
issue: 300
outcome: "All seven reference films are recaptured and pinned on Patch 3; `corpus-patches` and `captures` are packed from the post-#305 pins and uploaded to R2. The cloud check that a session scores all seven films moved to #455."
---

# Reference films are captured on the unpatched builds, not Patch 3

All seven reference films are recaptured on Patch 3 from Patch 3 `MAKEONE` archives and promoted; none moved by more than 0.0031 SSIM ([journal](journal.md)). Recapture noise on Patch 3 is in [`method.md`](../../../research/parity/method.md) § 2.2.1.

## Handoff

- Done: rows name `patch3` with no `reason`; `expected.gpu` re-measured at `ff576ba`; `noise_sigma` only on LOCATION; manifests rebuilt by `make-all` on `builds/patch3`; `corpus-patches` added to `manifests/cloud-assets.toml` and `game-builds` to the cloud hook. On 2026-11-13 `pack captures corpus-patches` reproduced the pinned keys in `manifests/cloud-assets.toml` (`captures-35905aea05fca4ea`, 3,562,356 bytes; `corpus-patches-914c42923b184754`, 4,219,879 bytes), so #305's repin already carried the current `captures` pack, and both were uploaded with `upload corpus-patches captures`.
- Left: #455, a cloud session that reports `ready` and runs `mise run parity` on all seven films with no refusal.
- The unpatched reference captures are kept in `<data root>/backup/pre-300/`, and their recaptures in `<data root>/bench/<slug>/recapture-unpatched/`.
