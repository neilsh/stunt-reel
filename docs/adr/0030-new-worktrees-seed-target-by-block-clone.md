# New worktrees seed `target/` by block clone

## Status

re-measured 2026-11-19 with kache 2.2.0, decision unchanged: kache alone took a median 35.9 s for a new worktree's first Rust lanes against the seed's 29.6 s, and beside the seed 28.1 s, within the seed's spread (Context).

amended 2026-11-14 for [#486](https://github.com/neilsh/stunt-reel/issues/486): Rust tests
read `CARGO_MANIFEST_DIR` at run time, and the seed keeps a workspace crate's unit only where
every file it was built from is byte-identical to the donor's and Cargo records none of them by
the donor's absolute path, giving those files the donor's modification times. A new worktree's
first Rust lanes took a median 18.5 s against 23 s over four pairs
([journal](../../work/2026-11/486_manifest-dir-runtime/journal.md)).

amended 2026-11-04 by [ADR 0036](0036-worktrees-reach-shared-state-by-configuration.md): seeding runs from `ensure`, a dependency of every
building task.

accepted 2026-11-02, at the measured 40 s and 0.7–0.9 GB of own disk per new worktree rather than
the 30 s and 0.5 GB [the seeding plan](../../work/2026-11/target-seeding/spec.md) first set:
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

### kache 2.2.0, re-measured 2026-11-19

kunobi-ninja/kache#1792 was closed as fixed in 2.1.1 on 2026-11-15, and 2.1.1 and 2.2.0 had shipped since 2.0.0, so the deferred option was measured again.
Each run made a new worktree at `900ae751` on `E:` and timed its first `mise run check-rust`.
The seed came from the repo's own `seed()` with one named donor: a checkout built twice without kache for the first arm, and one built twice through kache for the third.
kache 2.2.0 ran as `RUSTC_WRAPPER` with its store on `E:` (`cache.local_store`), default settings otherwise, and no `kache init`.
Three runs per arm (n = 3, and the two seeded arms had different donors), interleaved, with no other cargo or rustc process running at the start of any run:

| measure | seed, no kache | kache, no seed | seed and kache |
| --- | --- | --- | --- |
| first Rust lanes | 33.2, 25.8, 29.6 s | 35.8, 47.5, 35.9 s | 27.5, 28.1, 28.4 s |
| `Compiling`, `Checking`, `Documenting` lines in `check.log` | 15 | 130–305 | 15 |
| kache's hit rate | none | 89–93% | 0% (3 compiled, none cacheable) |
| `target/` size (`du -sm`, MiB) | 2103 | 1780–2607 | 1913 |

Own disk (clusters with a reference count of 1) was not measured.
Four alternating warm gates were alike: 20 s and 16 s without kache, 18 s and 16 s through it.
Two warm runs through kache earlier the same day took 131 s (nothing compiled) and 46 s.
In the first the fmt step, which never calls rustc, took 36 s; in the second the GPU tests, identical binaries by hash, took 20 s against 11 s without kache.
That points to load elsewhere on the machine rather than kache, but it was not isolated.

kache's worktree seeding ran on Windows in these runs: in each of the three seed-and-kache runs, `kache stats --last-build` reported 3 of 3 units seeded from another checkout's `target/debug`.
kache seeded those three units and still compiled them (they are executables, which `cache_executables = false` keeps out of the store), and Cargo ran the same 15 units as with our seed alone.
Seeding appeared only in the seed-and-kache arm's stats; without our seed, Cargo logged 130–305 units, most restored from the store.

The verdict stands.
kache alone was slower than the seed (median 35.9 s against 29.6 s, with no overlap in range), and beside the seed its 28.1 s median fell within the seed's own 25.8–33.2 s spread.
kache 2.2.0's notes also say its file-hash memo, which cuts Windows key time, cannot work off NTFS, ReFS included, and the checkouts are on ReFS; key time was not measured here.

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
  would need the same care for workspace units as ours.
  Re-measured with 2.2.0 on 2026-11-19 (Context): #1792 is fixed and its worktree seeding runs, but alone it is slower than our seed and beside it no faster beyond noise, at three runs per arm.
  Reopen if kache seeds whole units so that Cargo skips them, or a measurement beside the seed shows a gain larger than the seed's run-to-run spread.
  It keeps one
  advantage seeding lacks: after a `Cargo.lock` or toolchain change each crate compiles once for
  every worktree, where a seeded worktree rebuilds the changed units itself until its donor does.
- **One `target/` for every worktree.** Rejected again for ADR 0013's reason: Cargo locks it for a
  whole build, so concurrent gates serialise.
- **Deduplicating existing `target/` directories after the fact.** Not possible while each
  worktree's `CARGO_HOME` path is written into its output.
- **Only trimming what a build keeps** (no dependency debug info: 0.16 GB per worktree; incremental
  off in the clippy and matrix lanes: about 0.33 GB). Small next to seeding, so not instead of
  it. The first, and building `doc` in `target/check` beside clippy's metadata (0.19 GB), were
  done on 2026-11-02: a cold gate's `target/` measured 1.9 GB, against the 2.4 GB above.
  Later the same day incremental went off in the clippy, doc and matrix lanes (278 MB after a
  dozen edits; a re-check after a real edit went from 1.6–4.2 s to 2.2–4.8 s) and test builds
  lost their debug info (about 70 MB of `.pdb`; frames keep their names, not their lines). The
  test lane keeps incremental for the edit-and-test loop. One integration-test binary per crate
  is [#125](https://github.com/neilsh/stunt-reel/issues/125).

## Consequences

- `CARGO_HOME` resolves to the primary checkout's `.cache/cargo` by absolute path in every
  checkout. ADR 0013 chose the per-checkout path for DSH's sandbox and integrity labels; work here
  now runs mainly under Claude Code, where neither applies. Every existing worktree rebuilds its
  dependencies once after the switch, because their fingerprints name the old path.
- A seeded worktree on another volume (the Orca worktrees on NTFS `C:`) gets a full copy rather
  than a clone, so init seeds only where the filesystem clones.
- Cleaning idle worktrees' `target/` stays worth doing; seeding makes a cleaned worktree cheap to
  rebuild.
