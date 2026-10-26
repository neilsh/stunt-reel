# The gate runs independent lanes concurrently

## Status

accepted; implemented

## Context

`mise run check` ran its nine leaf steps one after another although only three of them contend for
one resource: `lint-rust`, `test-rust` and `doc` build into `target/`, and cargo holds an exclusive
lock on a target directory for the whole of a build, so those cannot usefully overlap. The other
six steps — `fmt-check-rust`, `check-rust-matrix` and the four Python steps — only share the
machine. On a warm checkout the sequential gate took 34 s, and about 19 s of that was the Python
half queueing behind the last cargo step. On a cold checkout (a fresh worktree after
`mise run init`, so `target/` is empty) it took 79 s.

Cargo also serialises two builds that do not reuse each other's output: `cargo clippy` compiles in
the check profile while `cargo test` and `cargo doc` compile in the build profile. They share one
lock on `target/` even though neither waits for the other's artifacts, so much of a cold gate was
blocked by a lock held for work that could not help it.

[ADR 0008](0008-worktrees-share-one-read-only-data-root.md) and
[ADR 0013](0013-worktrees-share-one-writable-tool-cache.md) rejected one `CARGO_TARGET_DIR` shared
across *worktrees*. This decision does not reopen that: these directories are per worktree, live
under its own `target/`, and die with it.

## Decision

[gate.py](../../python/scripts/gate.py) groups the steps of the one `STEPS` plan into lanes
(`STEP_LANES`). The steps in a lane run in order; lanes run at the same time, with at most one
worker per CPU. A lane is the unit of an exclusively held resource:

- `rust-lint` owns `target/check` ([mise.toml](../../mise.toml)), so the check-profile compile runs
  beside the build-profile one instead of after it.
- `check-rust-matrix` owns `target/matrix`, so the no-default-features variant neither waits for
  nor invalidates the all-features artifacts under `target/`.
- `test-rust` then `doc` share the `rust-build` lane: both need the build-profile artifacts in
  `target/`.
- `fmt-check-rust` and each Python step own a lane; none of them touches a cargo target directory.
- `STEPS` remains the only step list, so `check`, `check-rust` and `check-py` still cannot run
  different gates ([ADR 0014](0014-the-gate-is-one-ordered-script.md)).
- The matrix task drops its `cargo check ... &&` prefix: `cargo test` already builds the plain
  library for the integration tests, so the check compiled the same no-default-features library a
  second time for no extra coverage.
- Step lines and log sections are written under one lock as each step completes, with stdout
  flushed. Completion order is not plan order, and a piped gate would otherwise print nothing
  until it exited.

Measured on a 16-logical-core Windows workstation with the shared cargo registry warm; a cold run
starts with `target/`, `target/check` and `target/matrix` removed (a fresh worktree's state), and
each figure is the whole `mise run check`:

| gate | warm | cold |
| --- | --- | --- |
| sequential (ADR 0014) | 34 s | 79 s |
| lanes (this decision) | 15 s | 65-70 s |

The new directories cost 0.6 GB (0.42 GB check profile, 0.20 GB matrix) against a cold `target/`
of about 2 GB. Measurements were taken outside the agent file sandbox: under DSH's
`workspace-write` sandbox the same build is several times slower because every file operation goes
through the restricted token, which is a property of the harness, not of the gate.

## What enforces this

- **A lane for every step.** `_lane_plan` refuses to run a step that has no lane, and
  [`tests/test_gate_plan.py`](../../tests/test_gate_plan.py) checks the map is total over `STEPS`
  and that each lane keeps plan order.
- **Cargo's own lock.** A shared target directory serialises even if a lane is mis-assigned, so the
  blast radius of a wrong mapping is a slow gate, not a corrupt build; the mapping comment names
  the resource each lane owns.
- **One step list.** `check`, `check-rust` and `check-py` all dispatch the same `STEPS` through
  `_plan`; a half only chooses which steps run.
- **The log.** `target/check.log` records the lane plan, then one section per completed step; the
  verdict still counts failures over the plan.

## Considered Options

- **Parallelise only the Python half.** Rejected: it leaves the check-profile and build-profile
  compiles serialised, which is most of a cold gate and several seconds of a warm one.
- **Run every step as its own lane.** Rejected: three cargo steps would queue on one
  target-directory lock in a nondeterministic order, and the matrix would keep invalidating the
  all-features artifacts.
- **Let mise dispatch the graph** (`run = [{ tasks = [...] }]`). Rejected: it puts a second copy of
  the step list in `mise.toml`, losing ADR 0014's one-list guarantee and the verdict and log.
- **`sccache`.** Still the lever for cold builds, and still deferred for the reasons in ADR 0013;
  lanes are orthogonal to it.
- **`pytest-xdist`.** Not taken: the Python suite is now the warm critical path (about 15 s), but a
  new dependency for it would have to clear [ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md).

## Consequences

- A warm gate is now bounded by the Python suite (about 15 s); the Rust lanes finish in 5-13 s.
- A cold gate is still compile-bound (about 63 s of cargo work); lanes recover the Python wait and
  the check-profile overlap, not the compile itself.
- One gate per checkout: two concurrent runs share the cargo locks and both write
  `target/check.log`.
- CI caches `target/`, so its cargo cache key is bumped once (`cargo-v2-`): a cache hit never saves,
  and the old key would leave the new directories cold on every run. The worker cap keeps a
  four-core runner from over-subscribing three concurrent cargo builds.
- `check-windows` is still a mise `depends` chain; it now builds clippy into `target/check`, so a
  cold Windows CI run pays that build once.
