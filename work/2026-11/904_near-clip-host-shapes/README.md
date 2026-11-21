---
title: "near-clip-host-shapes"
started: 2026-11-21
issue: 904
outcome: ""
---

# near-clip-host-shapes

## Handoff

- `ctry` 926 is the grass tile hosting the hero aircraft's and shadows' windows; its loss is theirs ([journal](journal.md)).
- `bomb` 1756 loses to the police car's door, which our 0.5 m near plane cuts away; `DBG_NEAR=0.1` adopts on the heuristic track ([`sweeps/near-clip.toml`](sweeps/near-clip.toml), [`switches/DBG_NEAR.diff`](switches/DBG_NEAR.diff)).
- Next: set `DEFAULT_NEAR_CLIP` to 0.1 in `crates/stunt-render/src/camera.rs`, run `mise run parity` on the committed tree, `mise run parity-repin`, and open the PR with the pictures in `images/`.
