# New worktrees seed `target/` by block clone

## Status

accepted 2026-11-02, at the measured 40 s and 0.7–0.9 GB of own disk per new worktree rather than
the 30 s and 0.5 GB [the seeding plan](../process/plans/target-seeding-2026-11-02.md) first set:
the workspace crates rebuild by design, and less than half the unseeded 91 s is worth having now.
Takes up the "seed a new worktree's `target/` from a built template" option that
[ADR 0017](0017-the-gate-keeps-no-compiler-cache.md) kept for reopening, and makes one exception to
[ADR 0013](0013-worktrees-share-one-writable-tool-cache.md): every checkout points `CARGO_HOME` at
the one shared cache by its absolute path.

## Context

On 2026-11-02 the 50 GB `E:` Dev Drive (ReFS) that holds the checkouts fell to 1.2 GB free, and
`target/` directories held about 18 GB of it (about 31 GB counting the Orca worktrees on `C:`). A
worktree that has run the gate once holds 2.4 GB (1.7 GB `target/debug`, 0.44 GB `target/check`,
0.2 GB `target/matrix`); a worktree in daily use grows to 3.5–5.1 GB, because Cargo never deletes
stale units and because these add more:

- `cargo doc` writes 107 dependency metadata files (192 MB) into `target/debug` that are the same
  units, by hash, as the clippy lane's in `target/check`.
- A bare `cargo` outside `mise run` uses the user's `CARGO_HOME`, so its units sit beside the
  gate's instead of reusing them (0.6 GB `release`, 0.6 GB `build-at` in the primary). `build-at`
  sets no `CARGO_HOME` at all.

Builds cannot be shared after the fact. The same dependency built in three worktrees gives three
different files, because each worktree's `CARGO_HOME` path is written into the output (36 times in
`serde_core`'s rlib). And Cargo treats a different `CARGO_HOME` path as a different build: one
`target/` built through two junctions to the same registry compiled 14 crates, then 0, then 14
with the other path, then 14 again with the first. Each build overwrote the other's files under
the same names.

ReFS clones blocks on an ordinary copy: two `Copy-Item`/`robocopy` copies of a 70 MB rlib cost
about 9 MB, and `fsutil file queryExtentsAndRefCounts` shows every extent with reference count 3.

### kache 2.0.0, measured the same day

kache 2.0.0 (stable that day) normalizes `CARGO_HOME` and workspace paths in its keys and restores
by clone, so it was the first candidate. Two scratch worktrees on `E:`, each with its own
`CARGO_HOME`, `RUSTC_WRAPPER` set per command, no `kache init`:

| measure | without kache | kache | kache, `cache_executables = true` |
| --- | --- | --- | --- |
| cold Rust gate, second worktree | 89 s | 68 s | 85 s |
| warm gate | 18 s, 21 s | 20 s (first runs 32 s, 34 s) | not run |
| one-crate edit | 29 s, 36 s | 37 s, 37 s | not run |
| second worktree's own `target/` disk | ~2.4 GB | ~1.3 GB | ~0.1 GB |
| store, once | none | 1.1 GiB | 1.7 GiB |

Disk is the logical size less clusters with a reference count above 1. Other sessions were
building on the same machine, so the times are rough.

The test build alone (`cargo test --no-run`) took 38 s without kache, 47 s while filling the store
and 22–35 s restoring from it. Every restored crate still passes through the wrapper, and
`kache stats` puts that at 380–790 ms of startup plus about 90 ms of keying per crate. Process
creation alone costs about 100 ms here (`rustc --version`).

kache's new-target seeding would remove that per-crate cost by copying units and fingerprints so
that Cargo skips them, but it never ran: not with `RUSTC_WRAPPER`, not with `kache cargo --`,
not from a second checkout, and not in a two-crate repro with one shared `CARGO_HOME`. Neither
the wrapper's nor the daemon's debug log records a seed request, and the code's early returns
are silent. No upstream issue covers it; the nearest is
[kunobi-ninja/kache#1792](https://github.com/kunobi-ninja/kache/issues/1792) (Windows daemon
reachability and slow cache keys), whose errors these logs do not show.

## Decision

`mise run init` seeds an empty `target/` by cloning a donor checkout's build output, and every
checkout uses one absolute `CARGO_HOME` so that the donor's dependency fingerprints stay valid in
the new checkout. A dependency's fingerprint names its registry source, so Cargo rebuilds one the
donor built differently. The workspace's own crates are the exception: Cargo calls one fresh when
its sources are older than its outputs, whatever the sources hold, so a checkout created before
its donor's last build would run the donor's code, and its tests would read the donor's
`CARGO_MANIFEST_DIR`. The seed therefore drops those crates' fingerprints, and they always
rebuild. Measured on 2026-11-02 (the plan, section 5): every dependency arrived fresh, and the
Rust lanes took 40 s against 91 s unseeded. ADR 0017's 17.6 s with 0 crates compiled did not
reproduce, and by this design it cannot. The plan holds the design, the checks that pick a donor,
and the measurement.

## Considered Options

- **Adopt kache 2.0.0 now.** It meets the disk goal (with executable caching on) and keeps
  per-checkout `CARGO_HOME`, but a cold gate in a new worktree is 68–85 s against 40 s for a
  seeded one, edits are no faster, and it adds a pinned two-binary tool, a daemon, a store and a
  config. Deferred, not rejected: reopen when its new-target seeding works on Windows,
  kunobi-ninja/kache#1792 is resolved, and a few releases have passed since 2.0.0. Its seeding
  would need the same care for workspace units as ours. It keeps one
  advantage seeding lacks: after a `Cargo.lock` or toolchain change each crate compiles once for
  every worktree, where a seeded worktree rebuilds the changed units itself until its donor does.
- **One `target/` for every worktree.** Rejected again for ADR 0013's reason: Cargo locks it for a
  whole build, so concurrent gates serialise.
- **Deduplicating existing `target/` directories after the fact.** Not possible while each
  worktree's `CARGO_HOME` path is written into its output.
- **Only trimming what a build keeps** (no dependency debug info: 0.16 GB per worktree; incremental
  off in the clippy and matrix lanes: about 0.33 GB). Small next to seeding; left as follow-ups.

## Consequences

- `CARGO_HOME` resolves to the primary checkout's `.cache/cargo` by absolute path in every
  checkout. ADR 0013 chose the per-checkout path for DSH's sandbox and integrity labels; work here
  now runs mainly under Claude Code, where neither applies. Every existing worktree rebuilds its
  dependencies once after the switch, because their fingerprints name the old path.
- A seeded worktree on another volume (the Orca worktrees on NTFS `C:`) gets a full copy rather
  than a clone, so init seeds only where the filesystem clones.
- Cleaning idle worktrees' `target/` stays worth doing; seeding makes a cleaned worktree cheap to
  rebuild.
