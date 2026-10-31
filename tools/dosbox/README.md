# DOSBox configuration

Capture, probing, `make-all` and `play` run on dosbox-automation 0.85.1 and need no checked-in
conf: `python/stunt_reel/tac/staging.py` renders one per run beside a staged mount under the
data root, with a free web-server port chosen at launch ([ADR 0025](../../docs/adr/0025-capture-runs-are-plans-not-sessions.md)).
The DOSBox-X profiles that used to live here are retired; what they established is in
[`research/playone-exe/dosbox-x-legacy.md`](../../research/playone-exe/dosbox-x-legacy.md).

| File | Used by | Purpose |
|---|---|---|
| `dosbox-utils.conf` | by hand | Period utilities from `build/utils`, no control port ([`research/stunt-exe/sets.md`](../../research/stunt-exe/sets.md)); written for DOSBox-X and not rerun on dosbox-automation |
