# The gate runs pytest across every core

## Status

accepted 2026-11-03, amended 2026-11-06. Takes up the `pytest-xdist` option
[ADR 0016](0016-the-gate-runs-independent-lanes.md) left for
[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) to clear, and is the
admitting record that ADR asks for.

## Context

When ADR 0016 gave the gate lanes, the Python suite was the warm critical path at about 15 s. It has
since grown to 993 tests and 91 s, single-process on a 16-core workstation, while every other lane
of a warm gate finishes inside 22 s. A warm `mise run check` took 91 s, all of it waiting on
`test-py`.

About 60 s of the suite is a few slow tests, but no one of them dominates: the parity-bench
fixture computes ten metrics over seventeen faults (13.5 s), the worktree-reap tests build real
git repositories (about 20 s across sixteen tests), the formats catalog runs three times (8 s), and
two tests wait out real timeouts (11 s). Trimming them one by one leaves a serial suite near 50 s.

## Decision

The gate's `test-py` step runs pytest with `-n auto` from `pytest-xdist`, set through
`PYTEST_ADDOPTS` in the step's environment (`STEP_ENV` in
[gate.py](../../python/scripts/gate.py), which also holds the variables that stop the step from
silently skipping). `-n auto` is not in pytest's `addopts`: a scoped
`mise run test-py -- <file>`, the inner loop of AGENTS.md, Working economically, stays in one process, where
starting workers costs about 2 s against a file that runs in milliseconds. xdist's default `load`
scheduling hands out single tests, so a module-scoped fixture is rebuilt on each worker that needs
it; that spends CPU but not wall time, where `loadfile` would keep all of `test_worktree_reap.py`
on one worker.

Measured warm on the 16-logical-core Windows workstation, each figure a whole `mise run check`:

| gate | `test-py` | `test-rust` | whole gate |
| --- | --- | --- | --- |
| serial pytest (ADR 0016) | 91 s | 22 s | 91 s |
| `-n auto` (this decision) | 32-33 s | 28 s | 32-33 s |

`test-rust` slows by 6 s from sharing the cores, and the two lanes now finish within seconds of
each other. One test-side trim came with it: the guest-timeout test in
[`test_tac_automation.py`](../../tests/test_tac_automation.py) gives up after one refused connect
instead of three (6 s to 2 s), since each refused loopback connect on Windows really waits.

### The dependency, against ADR 0010

- **Job.** Run one pytest session across worker processes and gather one verdict, with
  per-worker temporary roots. The standard library offers processes, not a pytest scheduler; the
  alternative is a hand-written sharder (below).
- **pytest-xdist 3.8.0**: a `py3-none-any` wheel, so every CI platform installs it without a
  build; MIT; released 2025-07. It ships no `py.typed` and has no mypy plugin, which ADR 0010's
  check asks for. Nothing imports it, though: the gate passes `-n` through the environment, and the
  one test that knows about workers reads `PYTEST_XDIST_WORKER`. mypy never resolves it, so the
  check has nothing to apply to. A conftest that imports `xdist` reopens this.
- **execnet 2.1.2**: xdist's transport to its worker processes. A `py3-none-any` wheel, MIT,
  `py.typed`, released 2025-11.
- **pytest**: already in the dev group.

## Considered Options

- **Shard test files across several lanes in gate.py.** Rejected: a static split balances
  badly (one reap file is 20 s), it collects the suite once per shard, it gives the gate several
  `test-py` verdicts and log sections, and it reimplements xdist's scheduler.
- **`-n auto` in `addopts`.** Rejected: every scoped run would pay worker startup. A run that
  wants workers outside the gate passes `-n auto` itself.
- **Trim the slow tests and stay serial.** Not enough on its own (about 50 s). Under xdist only the
  longest single test or fixture bounds the suite, so trims elsewhere no longer move the gate.
- **Cache capture and render luma in `stunt_reel.bench`** to cut the bench fixture, the suite's
  floor, by about 5 s. Deferred: `test-rust` bounds the gate at 28 s either way.

## Consequences

- A warm gate is bounded by two lanes together: `test-rust`, where two `stunt-render` GPU test
  binaries run one after the other for about 21 s, and `test-py`, whose floor is the 14.6 s bench
  fixture plus worker startup. Speeding up either alone gains a few seconds.
- CI's `quality` job runs `mise run check`, so it runs xdist on the runner's cores. `check-windows`
  is a mise `depends` chain that never goes through gate.py and stays serial.
- Tests run in a nondeterministic order across processes. A test may not share a fixed path,
  port or working directory with another, and one that reads pytest's session layout must allow
  for a worker's `<run root>/popen-gw<N>` temporary root, as
  [`test_pytest_basetemp.py`](../../tests/test_pytest_basetemp.py) does.

## Amendment: physical cores (2026-11-06)

`-n auto` started 16 workers on the workstation, one per logical core, because xdist counts
physical cores only when `psutil` is installed and falls back to `os.cpu_count()` otherwise. The
dev group now carries `psutil`, so `-n auto` starts 8. The decision stands with "core" meaning a
physical one; the gate still passes `-n auto` through `PYTEST_ADDOPTS`.

pytest alone, warm, on the 8-physical, 16-logical-core workstation
([scoped-gate plan](../process/plans/scoped-gate-2026-11-06.md), section 2):

| workers | wall |
| --- | --- |
| `-n auto` (16) | 39-45 s |
| `-n 12` | 34 s |
| `-n 8` | 30-33 s (three runs) |

On the day the dependency landed, with other sessions holding 15-20 % of the CPU, pytest alone
took 49-50 s at 8 workers and 51-53 s at 16, alternating runs. Three warm whole gates took
53, 53 and 48 s before and 49, 55 and 67 s after; that background load swamps a gain of a few
seconds, so the whole-gate figures show the noise rather than the change. Eight workers also
leave cores free for `test-rust` and for a cold cargo build in another worktree.

### The dependency, against ADR 0010

- **Job.** Count physical cores for xdist's `-n auto`. The standard library reports logical
  cores only; the alternative, a hand-written count per platform, is what psutil already is.
- **psutil 7.2.2**: `abi3` wheels for Windows (x86-64, ARM64), macOS and manylinux/musllinux
  (x86-64, aarch64), so every CI platform installs it without a build; BSD-3-Clause; released
  2026-01. It ships no `py.typed`. Nothing imports it: xdist looks for it at startup, so mypy
  never resolves it and the check has nothing to apply to.
