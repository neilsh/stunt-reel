---
title: "Single-film headless lavapipe renders run on one core and leave other cores idle"
started: 2026-11-22
issue: 916
outcome: "stuntreel --workers N renders one film in N child processes and joins byte-identical stores; parity_run budgets jobs x workers"
---

# Single-film headless lavapipe renders run on one core and leave other cores idle

Lavapipe draws one device's queue on one thread, so a single-film render leaves cores idle; #918 found child processes scale and in-process devices do not.

## Outcome

- `stuntreel --workers N` ([`workers.rs`](../../../crates/stunt-cli/src/workers.rs)) runs N children with `--shard K` and `LP_NUM_THREADS=1`, each rendering a contiguous run of whole film seconds ([`shard_samples`](../../../crates/stunt-cli/src/playback.rs)), and joins their stores with `merge_render_dirs` ([`merge.rs`](../../../crates/stunt-score/src/render_store/merge.rs)).
- `mise run parity -- --workers N` fits jobs x workers to the cores and 953 MiB per process, and starts the longest capture first.
- Timings and the seven-film byte-identity check: [journal](journal.md), lifted into [`lavapipe-render-time.md` § 5](../../../research/parity/lavapipe-render-time.md#5-multi-vkdevice-in-process-versus-child-processes).
