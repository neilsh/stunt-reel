# CI scopes a docs-only pull request

## Status

accepted 2026-11-17 for [#659](https://github.com/neilsh/stunt-reel/issues/659), designed in its
[spec](../../work/2026-11/659_ci-scope-by-changed-paths/spec.md). Supersedes in part
[ADR 0038](0038-the-local-gate-runs-what-a-change-touches.md): its Context's "CI's `quality` job
runs the gate on every pull request" no longer holds for a docs-only pull request, which runs the
docs half. ADR 0038's rules for `mise run check` are unchanged, a set `CI` included.

## Context

A pull request that changed only Markdown waited on the same CI as a code change: `quality`
installed lavapipe and the Rust toolchain, restored the cargo cache and ran the full gate, beside
`msrv`, `deny` and `windows-smoke`. The owner's complaint was the wait.

On 2026-11-17 no `include_str!` or `include_bytes!` in `crates/` named a `.md` or `.ksy` file
(the fixture includes are under `tests/fixtures/`, an `other` path), and no `docs`-marked test
called cargo. So a change whose paths are all in ADR 0038's docs category reaches neither the Rust
build, nor `msrv`, nor `deny`.

The `main` ruleset (read through the API on 2026-11-17) requires five checks, matched by display
name: `Quality gate (ubuntu)`, `Windows smoke`, `MSRV check`, `Dependency policy` and `PR title`.
GitHub documents that a job skipped by its own `if:` reports as passing; a workflow that a `paths:`
filter never starts leaves its check pending, which blocks the merge.

## Decision

- **CI asks the gate's classifier.** `gate.py scope [--base REF]`
  ([`gate.py`](../../python/scripts/gate.py)) prints `docs_only=true` when ADR 0038's
  `scope_for`, with `CI` ignored, is not full and its halves are exactly the docs half; it prints
  `docs_only=false` otherwise, also when git cannot give the paths. `ci.yml` holds no path globs
  of its own.
- **A `scope` job runs it on pull requests only**
  ([`ci.yml`](../../.github/workflows/ci.yml)), against `origin/<base>`, with mise's pinned Python:
  the runner's system `python3` cannot parse `gate.py`. Any output line but those two fails the
  job. `scope` is not a required check.
- **One skip condition**: `scope` succeeded and said `docs_only=true`. A failed `scope`, a skipped
  one (a push to `main`, a manual run) or `docs_only=false` runs every job as before.
- **`quality` always runs** (`!cancelled()`), under its own name. Under the skip condition its
  steps leave out the lavapipe install, `rust` from the mise install, the cargo cache and
  `mise run check`, and run `mise run check-docs` instead; the empty-diff check, `uv sync`, the
  Java and Kaitai install and the prek built-ins still run.
- **`msrv`, `deny` and `windows-smoke` skip** under the skip condition, by their own `if:`, and
  run otherwise unless the run was cancelled. `windows-smoke` still runs on pull requests only.
- **No workflow-level `paths:` or `paths-ignore:`**, and no job `name:` changes: the ruleset
  matches by those names.

## Considered Options

- **A path filter in the workflow** (`dorny/paths-filter` or hand-written globs). Rejected: a
  second path table that drifts from ADR 0038's, and possibly a new action for the
  allowed-actions policy.
- **Split `quality` into Rust, Python and docs jobs behind one aggregate check.** Rejected for
  now: it needs the ruleset's required checks re-pointed, an admin change, and it shortens
  full-gate pull requests rather than the docs-only wait.

## Consequences

- A docs-only pull request that breaks a test only the full gate catches can merge, and the
  failure shows as a red check on `main`'s push run. ADR 0038's example is a Python test that
  reads `AGENTS.md` without the `docs` marker. The owner accepted this on 2026-11-17.
- `deny` does not run on a docs-only pull request, so a new advisory first shows on the next code
  pull request or push to `main`. Pushes to `main` and `workflow_dispatch` runs run every job they
  ran before.
- A change to `ci.yml` or `mise.toml` is an `other` path, so its pull request runs every
  pull-request job, as before.
- A future `include_str!` or `include_bytes!` in `crates/` of a `.md` or `.ksy` file outside it
  would escape the scope, since `classify` would call that path docs. `tests/test_gate_plan.py`
  finds only the reads written as `"../../` and `workspace_root().join("`; such an include would
  need its path in `_RUST_READS`.
- Dropping `rust` from the docs-only install rests on one local run (2026-11-17): with cargo and
  rustup off `PATH`, `rust` listed as missing by mise and `MISE_AUTO_INSTALL=false`,
  `mise run check-docs` passed. That run used the system Java, where CI installs Java through mise,
  and had `CI` unset, which `gate.py docs` does not read.
- Not yet exercised on GitHub: that a job skipped by its `if:` satisfies its required check, that
  a failed `scope` runs every job it gates, and that the prek built-ins step runs without Rust installed.
  The pull requests that follow this change verify them; this ADR does not.
- `tests/test_ci_scope.py` pins the skip condition, the job names and the absence of path filters
  in `ci.yml`; `tests/test_gate_plan.py` covers `gate.py scope`.
