# The gate is one ordered script, not a task graph

## Status

superseded in part by [ADR 0016](0016-the-gate-runs-independent-lanes.md): the one step list,
the verdict and the log stay; the steps now run as concurrent lanes, ordered only where they
share a resource.

`mise run check` used to be mise's `depends` chain: six aggregate tasks, each printing its own
output, no verdict at the end, and no log to read afterwards. The quiet halves had already
drifted — `check-rust` and `check-py` ran a shorter step list than `check`, so "the gate
passed" could mean two different things. It now runs [gate.py](../../python/scripts/gate.py),
which executes the leaf tasks, prints one line per step, quotes the tail of every failing step,
writes the complete output to `target/check.log`, and ends with a PASS or
FAIL over the step count. There is one step list, so a half-gate cannot diverge from the whole
one.

## What enforces this

- **One dispatcher.** `check`, `check-rust` and `check-py` in [mise.toml](../../mise.toml) all
  run `gate.py`; the steps live in `STEPS` there, and each names a leaf task.
- **No second copy.** The deleted `quiet_check.py` was that copy, and it is the one that had
  drifted.
- **A compiler that cannot silently skip.** The `test-py` step sets `STUNT_REQUIRE_KSC=1`, so a
  missing Kaitai compiler fails the gate instead of skipping the schema-contract test.
- **The log.** `target/check.log` is gitignored and is what a failure is quoted from, so a
  failing run is not repeated just to read its output.

## Considered Options

- **Keep the `depends` chain and add a verdict task.** Rejected: the output still comes from the
  child tasks, so there is nowhere to write the log and no way to truncate a failing step.
- **Two independent short gates.** Rejected: that is the drift being fixed.
- **A Makefile or a shell one-liner.** Rejected: a third runner to keep in step, and no
  Windows/Linux parity.
- **Quiet flags on each tool.** Rejected: cargo and ruff share no quiet contract, and the verdict
  would still not exist.
