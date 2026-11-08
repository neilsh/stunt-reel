# Journal: VAULT films in the parity corpus

## 2026-11-07: TOD on a superset archive

- **Question**: Does `PLAYONE.EXE` play a film from the superset archive (every stock shape) in place of the film's own `.ALL`, as our renderer does?
- **Method**: `TOD.FLM` (`corpus/stuntisl/VAULT`) staged beside the superset of [`linking.md`](../../../research/makeone-exe/linking.md) section 7, captured with `mise run capture-ref -- --out` on the unpatched and the Patch 3 `PLAYONE`, at `b05da8e`. Colour index pages paired by `film_tick` against a recapture of the film's own archive.
- **Result**: Both builds ran to film tick 1409 and kept 129 frames, with the ground drawn purple and green. On the unpatched build, 43 of 110 paired pages are identical against the superset (median 3 pixels differing, 90th percentile 634), against 84 of 119 for two captures of the film's own archive (median 0, 90th percentile 589). The superset leaves out the two `SPRITES.RES` palette items (`0x801E`, `0x8042`) the film's own archive holds.
- **Verdict**: control. The superset stays for our renderer only; the palette cause is a hypothesis from one film ([#301](https://github.com/neilsh/stunt-reel/issues/301)).
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) section 7.2.

## 2026-11-07: five VAULT films become reference films

- **Question**: What does each retail `VAULT` film score at the commit it joins the parity loop ([#246](https://github.com/neilsh/stunt-reel/issues/246))?
- **Method**: Each film captured on the unpatched `PLAYONE` from the unpatched `make-all` archive its manifest rebuilds, then `mise run parity` on the RTX 4070 at `740c608` and again at `4170cc3` for the `expected.gpu` tables, with the same scores. Not a renderer change; each film is scored only against its own capture, so its figures do not compare with another film's.
- **Result**:
  - `vault-land` (`LAND.FLM`): SSIM 0.8666, IoU 0.9857, index agreement 0.723, 97 of 103 frames scored; 103 frames over film ticks 12 to 1134, archive `3420036…` ([`vault-land.toml`](../../../manifests/all/vault-land.toml)).
  - `vault-balloon` (`BALLOON.FLM`): SSIM 0.7991, IoU 0.6351, index agreement 0.463, 107 of 108 scored; 108 frames over ticks 12 to 1190, archive `86628c5…` ([`vault-balloon.toml`](../../../manifests/all/vault-balloon.toml)).
  - `vault-traintnl` (`TRAINTNL.FLM`): SSIM 0.8514, IoU 0.9656, index agreement 0.849, 112 of 112 scored; 112 frames over ticks 12 to 1233, archive `076750b…` ([`vault-traintnl.toml`](../../../manifests/all/vault-traintnl.toml)).
  - `vault-bomb` (`BOMB.FLM`): SSIM 0.7991, IoU 0.9067, index agreement 0.743, 316 of 339 scored; 339 frames over ticks 13 to 3730, archive `282553d…` ([`vault-bomb.toml`](../../../manifests/all/vault-bomb.toml)).
  - `vault-location` (`LOCATION.FLM`): SSIM 0.7907, IoU 0.9788, index agreement 0.764, 732 of 745 scored; 745 frames over ticks 12 to 8262, archive `4a427bd…` ([`vault-location.toml`](../../../manifests/all/vault-location.toml)).
- **Verdict**: control (baselines).
- **Lives in**: [`references.toml`](../../../research/parity/references.toml), each film's row and its `expected.gpu` table.

## 2026-11-07: recapture noise and build floor

- **Question**: How far does a recapture move each reference film's score, and do separately built binaries of one revision add spread behind the 0.002 adoption floor ([#299](https://github.com/neilsh/stunt-reel/issues/299))?
- **Method**: One recapture per `VAULT` film (`<data root>/bench/<slug>/recapture/`), scored with `mise run parity-bench -- run --film <film> --recapture <dir>`; per-frame \|Δ\| of whole-frame `ssim`. Three binaries of `740c608`'s renderer (the gate's release build and two `mise run build-at` builds) rendering all seven films on the RTX 4070. Measurement only.
- **Result**: σ 0.0154 / 0.0168 / 0.0094 / 0.0126 / 0.00038 for LAND / BALLOON / TRAINTNL / BOMB / LOCATION over 89 / 100 / 99 / 273 / 732 paired frames; median \|Δ\| 0 on all five: most pages identical, and 24 to 39% of paired pages on the four short films differing, some by thousands of pixels. On `vault-balloon` tick 265 the reference page agrees best with the render at tick 264 (index agreement 0.580; 0.409 at 267) and the recapture's page with tick 267 (0.530). CTRY and INTRO could not be paired: their 2026-10-31 captures sit 3 ticks after the stride plan's goals on 90 of 121 and 86 of 346 frames, while the `VAULT` captures land on the goal or up to 3 ticks after it, mostly on it; they share 7 and 11 scored ticks with a recapture, below the bench's 20, and pairing by nearest tick (σ 0.0121 over 112 CTRY pairs, 85 of them 3 ticks apart) measures motion. The three binaries rendered all seven films to byte-identical render trees and identical scores.
- **Verdict**: control. Only `vault-location` takes a `noise_sigma` (0.00038); on the other four σ would call Δ below 0.01 to 0.017 noise ([#305](https://github.com/neilsh/stunt-reel/issues/305)). CTRY and INTRO wait for their Patch 3 recaptures ([#300](https://github.com/neilsh/stunt-reel/issues/300)).
- **Lives in**: [`method.md`](../../../research/parity/method.md) § 2.2.1 and § 3; [`references.toml`](../../../research/parity/references.toml).
