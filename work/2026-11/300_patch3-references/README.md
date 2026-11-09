---
title: "Reference films are captured on the unpatched builds, not Patch 3"
started: 2026-11-08
issue: 300
outcome: ""
---

# Reference films are captured on the unpatched builds, not Patch 3

All seven reference films are recaptured on Patch 3 from Patch 3 `MAKEONE` archives and promoted; none moved by more than 0.0031 SSIM ([journal](journal.md)). Recapture noise on Patch 3 is in [`method.md`](../../../research/parity/method.md) § 2.2.1.

## Handoff

- Done: rows name `patch3` with no `reason`; `expected.gpu` re-measured at `ff576ba`; `noise_sigma` only on LOCATION; manifests rebuilt by `make-all` on `builds/patch3`; `corpus-patches` added to `manifests/cloud-assets.toml` and `game-builds` to the cloud hook; `corpus-patches` and `captures` packed.
- Left: `mise run cloud-assets -- upload corpus-patches captures` from the primary machine, then a cloud session that reports `ready` and runs `mise run parity` on all seven films with no refusal. That is the issue's last acceptance box.
- The unpatched reference captures are kept in `<data root>/backup/pre-300/`, and their recaptures in `<data root>/bench/<slug>/recapture-unpatched/`.
