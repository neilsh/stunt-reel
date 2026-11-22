---
title: "Read the near plane PLAYONE's polygon clipper cuts at"
started: 2026-11-22
issue: 907
outcome: "PLAYONE's polygon clipper has no near plane: it cuts only at the view pyramid's sides (0xC6AF), at depth 0; an evidence-track sweep's 0.05 m win came from depth ties, so 0.1 m stays and lowering it is #955"
---

# Read the near plane PLAYONE's polygon clipper cuts at

## Handoff

- `PLAYONE`'s polygon clipper has no near plane: it cuts at the four side planes through the eye ([`sod-vm-lines-spans.md` § 8.13](../../../research/playone-exe/sod-vm-lines-spans.md#813-the-clip-volume-has-no-near-plane), [journal](journal.md)).
- The evidence-track sweep ([`sweeps/near-plane-at-the-eye.toml`](sweeps/near-plane-at-the-eye.toml)) picked 0.05 m on a `balloon` rise of +0.0002 from depth ties; the coordinator kept 0.1 m, and the owner's choice is [#955](https://github.com/neilsh/stunt-reel/issues/955).
- Open: whether the clipping line routine `0xBB83` also cuts only at the side planes (not read).
