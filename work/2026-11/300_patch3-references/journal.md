# Journal: reference films move to Patch 3

## 2026-11-08: seven reference films recaptured on Patch 3

- **Question**: Does any reference film's score drop by 0.01 or more when its archive is rebuilt with the Patch 3 `MAKEONE` and it is recaptured on the Patch 3 `PLAYONE` ([#300](https://github.com/neilsh/stunt-reel/issues/300))?
- **Method**: `mise run make-all` and `mise run capture-ref` with `--game-root <data root>/builds/patch3` for each `corpus/stuntisl/VAULT` film. `CTRY.FLM` and `INTRO.FLM` are byte-identical to the demo's copies, and the retail folder has no sibling `.ALL`, so their Patch 3 archive is the one played. Each row's builds and `all_sha256` were changed first, since the tools refuse a build the row does not name. Scored on the RTX 4070 by the `comparing-references` procedure: `mise run parity` on the unpatched references, then `mise run parity -- --no-build` on the candidates, with one binary at `ff576ba` (`crates` `f55202b`). The baseline equalled every film's committed `expected.gpu` table. Not a renderer change.
- **Result** (SSIM, IoU and index agreement over scored frames; unpatched reference → Patch 3):
  - `ctry`: 0.8986 → 0.8971 (−0.0015); IoU 0.9897 → 0.9897; idx 0.903 → 0.902; scored 114/121 → 114/121. Archive `9de1bc1…` (the demo's, 71,216 bytes) → `cb58d95…` (126,328 bytes).
  - `intro`: 0.8337 → 0.8306 (−0.0031); IoU 0.9856 → 0.9852; idx 0.833 → 0.827; scored 209/346 → 210/347. Archive `27935a3…` (the demo's, 207,826 bytes) → `2dc8f62…` (375,425 bytes).
  - `land`: 0.8666 → 0.8688 (+0.0022); IoU 0.9857 → 0.9853; idx 0.723 → 0.732; scored 97/103 → 97/103. Archive unchanged (`3420036…`).
  - `balloon`: 0.7991 → 0.7977 (−0.0014); IoU 0.6351 → 0.6351; idx 0.463 → 0.456; scored 107/108 → 107/108. Archive `86628c5…` → `e8d852f…`.
  - `traintnl`: 0.8514 → 0.8521 (+0.0008); IoU 0.9656 → 0.9653; idx 0.849 → 0.851; scored 112/112 → 112/112. Archive `076750b…` → `a649413…`, with `SCENERY4.RES` items 210, 229 and 240 added.
  - `bomb`: 0.7991 → 0.7986 (−0.0005); IoU 0.9067 → 0.9055; idx 0.743 → 0.739; scored 316/339 → 316/339. Archive `282553d…` → `b1a4848…`.
  - `location`: 0.7907 → 0.7918 (+0.0011); IoU 0.9788 → 0.9783; idx 0.764 → 0.765; scored 732/745 → 733/747. Archive unchanged (`4a427bd…`).
- **Verdict**: adopted. No film dropped by 0.01; the largest move is INTRO's −0.0031, under the 0.01 threshold. Every row now names `patch3` for both builds, with no `reason`, and the `expected.gpu` tables are re-measured on the new pins.
- **Lives in**: [`references.toml`](../../../research/parity/references.toml); the archive differences in [`patch3.md`](../../../research/playone-exe/patch3.md) § 3.

## 2026-11-08: recapture noise on Patch 3

- **Question**: How far does a second Patch 3 capture move each reference film's score, `CTRY` and `INTRO` included?
- **Method**: One recapture per film (`<data root>/bench/<slug>/recapture/`; the unpatched recaptures were moved to `recapture-unpatched/`), then `mise run parity-bench -- run --film <film> --recapture <dir>` against the renders at `ff576ba`. Median, p95, largest |Δ| and identical index pages were computed with the bench's own pairing and `ssim` metric (`stunt_reel.bench.run`).
- **Result**: σ (`ssim`) 0.0052 / 0.0194 / 0.0051 / 0.0109 / 0.0062 / 0.0124 / 0.00012 for CTRY / INTRO / LAND / BALLOON / TRAINTNL / BOMB / LOCATION. Paired 104 / 172 / 88 / 95 / 102 / 265 / 732, of which 77 / 94 / 61 / 56 / 71 / 153 / 729 were identical. Median |Δ| was 0 on all seven. CTRY and INTRO now pair: all 121 and 347 frames of the new captures sit on the current plan's ticks. CTRY's recapture σ is 0.0052, against 0.00030 for its 2026-10-31 pair.
- **Verdict**: control. Only LOCATION takes a `noise_sigma` (0.00012). On the other six the noise is heavy-tailed, and one σ would call real deltas noise ([#305](https://github.com/neilsh/stunt-reel/issues/305)). CTRY's 0.000303 is dropped: it measured the unpatched pair.
- **Lives in**: [`method.md`](../../../research/parity/method.md) § 2.2.1; [`references.toml`](../../../research/parity/references.toml); [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 2.

## 2026-11-08: Patch 3 in cloud sessions

- **Question**: Does `mise run game-builds` work on the cloud corpus, which leaves out `RES/MUSIC?.ESS`, `.XMI`, `.XMM` and `.XMP`?
- **Method**: `build_trees` on a copy of `corpus/stuntisl` without those files, with `corpus/patches`; file list and the five replaced files compared with the full-corpus `builds/patch3`.
- **Result**: It built both trees. The Patch 3 tree lacks only the six `.XMI`/`.XMM`/`.XMP` files (the patch supplies the `.ESS` ones). `MAKEONE.EXE`, `PLAYONE.EXE`, `SPRITES.RES`, `COMMNSND.SMP` and `SNDFX2.SMP` matched byte for byte. No archive manifest reads an excluded file.
- **Verdict**: adopted. The `corpus-patches` archive is added to `manifests/cloud-assets.toml`, and the SessionStart hook runs `game-builds` after `fetch`. Whether a cloud session scores all seven films is unverified until the new archives are uploaded and a session runs.
- **Lives in**: [`docs/cloud-sessions.md`](../../../docs/cloud-sessions.md).
