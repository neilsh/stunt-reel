# The gate keeps no compiler cache

## Status

accepted; nothing is configured. The `sccache` entries in
[ADR 0013](0013-worktrees-share-one-writable-tool-cache.md) and
[ADR 0016](0016-the-gate-runs-independent-lanes.md) are superseded by this record. Amended
2026-10-27 with a re-test on a ReFS Dev Drive; the decision stands (see "Re-test on a Dev
Drive").

## Context

A cold `mise run check` — a fresh worktree after `mise run init`, so `target/` is empty —
takes 62–64 s and is almost entirely cargo compiling dependencies. Each worktree then keeps that
build output: 2.1–2.4 GB for the gate's three target directories (`target/`, `target/check`,
`target/matrix`), measured per worktree. (The first draft of this record said about 20 GB; that
was the primary checkout's accumulated `target/`, not what a worktree needs.) [ADR 0013](0013-worktrees-share-one-writable-tool-cache.md)
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
  That was on NTFS; the Dev Drive re-test below shows restores without copying on ReFS. A
  compiler cache shares compile work, not build output, so it was never the lever for a
  worktree's own `target/`.
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

## Re-test on a Dev Drive

The repository moved to `E:`, a 50 GB ReFS Dev Drive (VHDX) with asynchronous Defender scanning on
(`C:` and `D:` stay NTFS with synchronous scanning). The same gate was run in two scratch
worktrees on `E:`, one absolute `CARGO_HOME`, each store on `E:`, a 240 s watchdog for the
`renderer_test` hang, and physical disk measured as the drop in free space on `E:` once it
settled. Single runs unless a count is given; "cold" is worktree B after worktree A primed the
store.

| case | cold | warm | one-crate edits | physical disk (A + B + store) |
| --- | --- | --- | --- | --- |
| none | 56.1 s, 57.3 s | 17.6 s | 19.5–19.7 s | 4.36 GB |
| `sccache` 0.19.0 | 63.0 s, 15.5% hits | hung | 20.0–23.0 s | 4.43 GB |
| `kache` 1.2.2 | 28.2 s, 29.0 s (3 runs completed, 1 hung) | 18.2–18.4 s | 20.5–22.4 s | 2.4–2.8 GB |
| seeded `target/`, no tool | n/a | 17.6 s, 0 crates compiled | n/a | about 0.3 GB |

- **The Dev Drive alone helps.** A cold gate is 55–63 s on `E:` against 62–64 s on `D:`, and a
  2.1 GB `target/` deletes in 1.4 s.
- **`sccache` still loses.** Its cold gate is slower than no cache and it saves no disk.
- **`kache` now halves the cold gate, still short of 25 s.** On the same ReFS volume it restores
  without copying (1.3 GiB no-copy, 34 KiB copied), so physical disk drops by 1.6–1.9 GB. Edits
  cost about a second more than with no cache. It still needs one absolute `CARGO_HOME` and a
  store on the volume, and its daemon is still denied under `workspace-write` (the sandbox result
  above was measured on `D:`; it was not repeated). Its stderr line "no daemon reachable ...
  starting one" is informational. A cached run can still hit the `renderer_test` hang.
- **Seeding beats it with no tool.** Copying a built `target/` into a new worktree with a
  cloning copier (`robocopy` 0.9 s, 0.29 GB physical on ReFS; `shutil.copytree` is not cloned)
  gives a 17.6 s gate with 0 crates compiled (20.6 s on `D:`), provided every worktree uses the
  same absolute `CARGO_HOME`; with per-worktree paths everything recompiles (69.9 s). It needs
  no cache tool, daemon or store, but it needs a template `target/` of the same `rustc`, and a
  worktree not on a cloning volume pays a full 2.1 GB copy (Orca worktrees on `C:` are NTFS). Its
  `workspace-write` behaviour (whether a restricted token can rewrite and delete files an
  unconfined clone created) was not tested.
- **`mbx` 1.27.0, tried afterwards, was no faster:** cold 72 s against 62–64 s without it. Under
  mise it clashes with ADR 0013's per-task `CARGO_HOME` (rustup "Access is denied" in the task
  environment), and with a store on `D:` its shim hit a hard-link/copy error.

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
- **Disk:** no saving on NTFS, and its store is one more thing to clean. On the Dev Drive `kache`
  saves 1.6–1.9 GB of physical disk, which does not outweigh the rest.

The Dev Drive re-test does not change the verdict: `kache`'s best cold gate is 28–29 s (still
over 25 s), it keeps the absolute-`CARGO_HOME` exception and the degraded sandbox mode, and it is
a young tool. The Dev Drive itself, a machine setup and not a repository change, delivered most
of the available gain.

## Considered Options

- **Adopt kache behind an opt-in flag.** Rejected: it meets no criterion fully, and it would add a
  pinned tool, a store, a daemon, and an absolute-`CARGO_HOME` exception to ADR 0013 for a
  cold gate still over the target.
- **Adopt sccache.** Rejected: three regressions and a zero-hit remap; the cache cannot touch the
  incremental and proc-macro work that dominates a warm gate.
- **Raise the target to about 35 s and adopt kache.** Rejected: a target set to the number just
  measured is not a target, and the other criteria still fail.
- **`mbx` (mr-boxington 1.27).** Tried after the first measurements: no faster (72 s cold), and
  it wraps cargo and manages `target/`, which would reopen ADR 0008's and ADR 0013's
  target-directory decisions. Rejected.
- **Seed a new worktree's `target/` from a built template.** Not adopted, kept as the reopen
  option. Measured 17.6 s on the Dev Drive with no tool, but it needs a shared absolute
  `CARGO_HOME` (an exception to ADR 0013), a template that only an unconfined run may write
  (test binaries every worktree executes), a `rustc` match check, a cloning copier, and a
  `workspace-write` test nobody has run. The minimal shape: `mise run init` copies the template
  into an empty `target/` with `robocopy` (Windows) or `cp -a --reflink=auto` elsewhere, and
  `CARGO_HOME` derives from `git rev-parse --path-format=absolute --git-common-dir`.
- **Do nothing.** Chosen.

## What enforces this

Nothing has to be switched off, which is the point: a wrapper that is not configured cannot run.
The decision is visible where an adoption would be — `RUSTC_WRAPPER` on the cargo tasks in
[`mise.toml`](../../mise.toml) and a `[tools]` pin — so a future change is a reviewable diff that
must cite this record and re-measure against the same rule.

## Consequences

- The cold gate stays 62–64 s on NTFS and 55–63 s on a Dev Drive outside the sandbox; inside a sandboxed session its `lint-rust`
  step alone measured 20.8–22.8 s cold without a cache. The 25 s target is recorded as unmet
  rather than softened.
- The compiler-cache lever is settled for now: both named candidates have measured evidence, and
  the sandbox client/server question ADR 0013 deferred is answered — the daemon channel is denied,
  while local-store caching survives.
- Reopening is a re-measure, not a re-derivation. Reopen if `kache` drops the shared-`CARGO_HOME`
  requirement, restores with hardlinks, or gets a sandbox-compatible daemon channel; if `sccache`
  learns to cache proc-macros or build scripts; if Cargo's cross-workspace build cache
  (rust-lang/cargo#5931, and the new build-dir layout stabilizing in 1.100, due 2026-11-12)
  supports build scripts and proc-macros; or if the cold gate becomes the dominant cost again, in
  which case seeding is the first thing to build and test under `workspace-write`.
- Not part of this decision, and not chased here: an intermittent `renderer_test` hang (about one
  gate run in three, with and without a cache) and a leaked `renderer_test` process seen from
  another worktree on 2026-10-25.
