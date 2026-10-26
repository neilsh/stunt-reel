# The gate keeps no compiler cache

## Status

accepted; nothing is configured. The `sccache` entries in
[ADR 0013](0013-worktrees-share-one-writable-tool-cache.md) and
[ADR 0016](0016-the-gate-runs-independent-lanes.md) are superseded by this record.

## Context

A cold `mise run check` — a fresh worktree after `mise run init`, so `target/` is empty —
takes 62–64 s and is almost entirely cargo compiling dependencies. Each worktree then keeps that
build output, about 20 GB of `target/debug`. [ADR 0013](0013-worktrees-share-one-writable-tool-cache.md)
and [ADR 0016](0016-the-gate-runs-independent-lanes.md) both deferred `sccache` as the lever for
sharing the compiled dependencies of one cold build with the next worktree.

The spike measured compiler wrappers (`RUSTC_WRAPPER`, no cargo wrapper) against an adoption rule
agreed before measuring: adopt the lowest cold-gate time, provided it reaches 25 s, hits across
worktrees at different paths, works under DSH's `workspace-write` sandbox, falls through when the
cache server is down, and leaves the warm gate and a one-crate-edit loop no more than 10% slower
(15 s warm per ADR 0016; 18 s measured here). The store was to live in the shared `.cache` with a
10 GB cap.

Measurements are from a 16-logical-core Windows workstation, outside the file sandbox unless a
section says otherwise; "cold" is a gate or step in a second worktree after the first worktree
primed the store, so hits cross worktree paths. The candidates were `sccache` 0.19.0 and `kache`
1.2.2.

## Evidence

| wrapper | `CARGO_HOME` | cold | warm | one-crate edits |
| --- | --- | --- | --- | --- |
| none | per worktree | 62–64 s | 18.0 s | 20.9 s, 23.8 s |
| `sccache` 0.19.0 | per worktree | 74.3 s, 0 hits | 17.2 s | 30.0 s |
| `sccache` 0.19.0 | one absolute path | 61.7 s, 181 hits / 575 misses | 17.8 s | 31.4 s |
| `sccache` 0.19.0 + `--remap-path-prefix` | one absolute path | 0 hits | — | — |
| `kache` 1.2.2 | per worktree | 48.7 s | hung | 32.1 s (first) |
| `kache` 1.2.2 | one absolute path | 32.8 s, 33.2 s | 18.2 s, 18.4 s | 31.3 s (first), 24.3 s, 23.9 s |

- **`sccache` does not fit the shape of a cargo build here.** Priming an empty store cost about
  75 s (against 63 s with no cache). It cannot cache incremental builds, build scripts or
  proc-macros, so a gate still runs about 440 uncacheable compiler calls. It hashes
  `--remap-path-prefix` into the key, so remapping every worktree to one path makes every hit
  miss; hitting across worktrees needs one absolute `CARGO_HOME` and no remapping.
- **`kache` halves the cold gate, but only with one absolute `CARGO_HOME`.** Registry source
  paths are part of its key, so per-worktree values give no hits; pointing every task at one
  absolute path gave 91% hits in the second worktree and 32.8–33.2 s cold. That conflicts with
  ADR 0013's `{{config_root}}/.cache/cargo`, which resolves per checkout by design; one way to
  derive the primary's path inside `mise.toml` is
  `git rev-parse --path-format=absolute --git-common-dir`. Its default store is under
  `%LOCALAPPDATA%`, so the shared store also needs `KACHE_CACHE_DIR` on the checkouts' volume.
- **`kache` saves no disk.** The store adds about 1 GB while the worktree still needs its own
  `target/`, and its stats show every restore copied (1.3 GiB copied, 0 B no-copy), not linked.
  A compiler cache shares compile work, not build output, so the ~20 GB per worktree was never
  this lever's to remove.
- **`kache` is young.** 1.0.0 shipped on 2026-10-05, 1.2.2 on 2026-10-15, 2.0.0-rc.1 on
  2026-10-25, with about 8k downloads at the time; its comparison page described an older
  release. A missing wrapper binary fails the build hard, while an unusable store fell through to
  a plain `cargo check` (5.6 s), which is the fallback that matters.

## Under the sandbox

In a scratch worktree under DSH's `workspace-write` file sandbox, `kache`'s background daemon
cannot start: `kache daemon start` fails in 0.14 s ("daemon candidate exited before readiness:
exit code: 1") and `daemon.log` records `error: opening daemon readiness channel: Access is
denied. (os error 5)`. The wrapper does not fail with it: it falls back to the local store, reads
and writes it through the shared `.cache` junction (a direct probe, then the index grew as
restores were recorded), and every compiler call in a cold run hit. What it costs is per-call
overhead with no daemon: 10 sequential one-crate `rustc` calls took 0.97 s plain against 3.58 s
through the wrapper (about 0.26 s per call), and cold `mise run lint-rust` (48 crates) took
14.0–14.9 s through kache against 20.8–21.6 s without, over three consecutive pairs. The first
such cold run, after the store had been idle, took 46.0 s; that one-off is unexplained and worth
knowing before trusting a first build.

The store was primed outside the sandbox and read by sandboxed runs without trouble, so the "one
store shared by sandboxed and unconfined runs" poisoning question had no bite in this test.
`sccache` was not re-tested under the sandbox: it was already ruled out on gain.

## Decision

Compiler caching stays out of the gate. No task in [`mise.toml`](../../mise.toml) sets
`RUSTC_WRAPPER`, no cache tool is pinned, and there is no cache store. Checked against the agreed
rule:

- **25 s cold:** not reached; `kache`'s best was 32.8 s.
- **Hits across worktrees at different paths:** only with one absolute `CARGO_HOME`, an exception
  to ADR 0013's per-checkout path with no benefit beyond the cache itself.
- **Works under `workspace-write`:** builds do, but in a degraded local-store mode; the daemon
  the design assumes is denied, and losing it adds per-call cost.
- **Warm and edit within 10%:** warm is (18.2–18.4 s against 18.0 s); edits are borderline
  (24.3 s and 23.9 s against 20.9 s and 23.8 s) and the first edit after a cold restore is about
  10 s slower.
- **Disk:** no saving at all, and its store is one more thing to clean.

## Considered Options

- **Adopt kache behind an opt-in flag.** Rejected: it meets no criterion fully, and it would add a
  pinned tool, a store, a daemon, and an absolute-`CARGO_HOME` exception to ADR 0013 for a
  cold gate still over the target.
- **Adopt sccache.** Rejected: three regressions and a zero-hit remap; the cache cannot touch the
  incremental and proc-macro work that dominates a warm gate.
- **Raise the target to about 35 s and adopt kache.** Rejected: a target set to the number just
  measured is not a target, and the other criteria still fail.
- **`mbx` (mr-boxington 1.27).** Not tested: it wraps cargo and manages `target/` rather than
  only `rustc`, which would reopen ADR 0008's and ADR 0013's target-directory decisions. A
  separate spike if cold-compile cost becomes urgent.
- **Do nothing.** Chosen.

## What enforces this

Nothing has to be switched off, which is the point: a wrapper that is not configured cannot run.
The decision is visible where an adoption would be — `RUSTC_WRAPPER` on the cargo tasks in
[`mise.toml`](../../mise.toml) and a `[tools]` pin — so a future change is a reviewable diff that
must cite this record and re-measure against the same rule.

## Consequences

- The cold gate stays 62–64 s outside the sandbox; inside a sandboxed session its `lint-rust`
  step alone measured 20.8–22.8 s cold without a cache. The 25 s target is recorded as unmet
  rather than softened.
- The compiler-cache lever is settled for now: both named candidates have measured evidence, and
  the sandbox client/server question ADR 0013 deferred is answered — the daemon channel is denied,
  while local-store caching survives.
- Reopening is a re-measure, not a re-derivation. Reopen if `kache` drops the shared-`CARGO_HOME`
  requirement, restores with hardlinks, or gets a sandbox-compatible daemon channel; if `sccache`
  learns to cache proc-macros or build scripts; if `mbx` earns its own spike; or if the cold gate
  becomes the dominant cost again.
- Not part of this decision, and not chased here: an intermittent `renderer_test` hang (about one
  gate run in three, with and without a cache) and a leaked `renderer_test` process seen from
  another worktree on 2026-10-25.
