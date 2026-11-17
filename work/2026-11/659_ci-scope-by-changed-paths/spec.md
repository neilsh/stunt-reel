# CI scopes its jobs by the files a pull request changes: design

Issue [#659](https://github.com/neilsh/stunt-reel/issues/659). Size: a small change (one workflow, one subcommand in `gate.py`, one ADR, one doc edit), so this is the short design.

## Intent

A docs-only pull request waits on the same CI as a code change: `quality` installs lavapipe and the Rust toolchain, restores the cargo cache and runs the full `mise run check`; `msrv`, `deny` and `windows-smoke` run beside it. The owner's complaint is wait time on docs-only PRs. Skip what a docs-only change cannot affect today, and only that: no `include_str!` or `include_bytes!` in `crates/` names a `.md` or `.ksy` file (read 2026-11-17; the fixture includes are `tests/fixtures/`, which is `other`), and no docs-marked test calls cargo, so `msrv`, `deny` and the Rust half have nothing a Markdown or `.ksy` change can reach. A future `include_str!` of a docs path would break this; `tests/test_gate_plan.py` finds only the reads written as `"../../` and `workspace_root().join("`.

## Goals

- A PR whose changed paths are all `docs` in [`gate.py`'s `classify`](../../../python/scripts/gate.py) (`*.md`, `*.ksy`, none under `crates/` or `tests/fixtures/`, none in `_RUST_READS`) runs the docs half only: `quality` runs `mise run check-docs` with no lavapipe, Rust install or cargo cache, and `msrv`, `deny` and `windows-smoke` skip.
- One path table. CI asks `gate.py`'s `scope_for` which halves apply; `ci.yml` holds no globs of its own.
- Every other PR, every push to `main` and every `workflow_dispatch` runs exactly what it runs today.

## Non-goals

- Scoping Python-only or Rust-only PRs. The classifier already says which half they need; this change reads one bit, `docs_only`, and a later one can read more.
- Changing the local gate or its ADR 0038 rules. `mise run check` under `CI` still runs the full gate.
- Path filters on `pages.yml`, `codeql.yml` or `pr-title.yml`.

## Anti-goals

- A required check left pending, which blocks merging. The `main` ruleset requires the checks named under Constraints, so no workflow-level `paths:` or `paths-ignore:`: a job skipped by its own `if:` reports as passing, a workflow that never starts does not.
- A broken scope step that lets a PR through unchecked. A job whose `needs` failed is skipped, and a skipped required check passes, so each dependent runs unless the scope job succeeded and said `docs_only=true`.

## Constraints

- Required checks: the `main` ruleset (read 2026-11-17 through the API) matches status contexts by display name: `Quality gate (ubuntu)`, `Windows smoke`, `MSRV check`, `Dependency policy` and `PR title` (`pr-title.yml`, untouched here). The job `name:` fields stay exactly as they are; renaming one would leave its required check pending. [`quality-gate.md`](../../../docs/quality-gate.md) lists four of the five, by job id, and gets corrected with the edit in Design 6. The new `scope` job is not required.
- ADR 0038: a path in the `other` category (`mise.toml`, a workflow, a fixture), no paths, or paths git cannot give, is the full gate. `ci.yml` itself is `other`, so a change to the scoping runs the full gate.
- Actions are pinned to SHAs and the repository has an allowed-actions policy; no new third-party action.

## Approaches

- **A. Reuse the gate's classifier (chosen).** A `scope` job runs a new `gate.py scope` subcommand on the PR diff and outputs `docs_only`. Downstream jobs and steps read it.
- **B. A path filter in the workflow** (`dorny/paths-filter` or hand-written globs). Rejected: a second path table that drifts from ADR 0038's, and possibly a new action on the allowlist.
- **C. Split `quality` into parallel Rust, Python and docs jobs behind one aggregate check.** Rejected for now: it needs the ruleset's required checks re-pointed (an admin change), and its gain is on full-gate PRs, not the docs-only wait.

The owner accepted A and its cost: a docs-only PR that breaks a test only the full gate catches (ADR 0038's example is a Python test reading `AGENTS.md` that lacks the `docs` marker) can merge, and the failure shows as a red check on `main` after the merge. Pushes to `main` stay full, so it shows within one run; ADR 0038 already weighed this ("a later red check, not a broken `main`").

## Design

1. **`python python/scripts/gate.py scope [--base REF]`** prints `docs_only=true` or `docs_only=false` on stdout, from `scope_for(paths, full_flag=False, ci=False, …)`: `true` only when the scope is not full and its halves are exactly `("docs",)`. Any error reading paths prints `false`. `ci=False` is deliberate: this asks what the paths need, not whether CI forces the full gate. `ci.yml` appends it to `$GITHUB_OUTPUT`.
2. **`scope` job** in `ci.yml`: `pull_request` only, `fetch-depth: 0`, runs the subcommand with `--base origin/$BASE_REF`. It installs `python` through `jdx/mise-action` (3.15.2, as `mise.toml` pins it): `gate.py` line 63 is `lazy from types import ModuleType` (PEP 810), which the runner's system `python3` cannot parse (3.13 gives `SyntaxError`), so the job costs a small mise install, not nothing. A failure of this job, a parse error included, is not the `false` path of item 1; item 3's condition is what makes it safe.
3. **The one skip condition**, used by every dependent: `SKIP = needs.scope.result == 'success' && needs.scope.outputs.docs_only == 'true'`. A dependent skips only when `SKIP` holds, and runs in every other case: `scope` failed, `scope` was skipped (push, dispatch) or said `false`. So every dependent carries `needs: scope` and `if: !cancelled() && !(SKIP)`: without `always()`, a failed or skipped `scope` skips its dependents, and a skipped required check passes, which is the second anti-goal.
4. **`quality`**: always runs and keeps its name (its `if: !cancelled()` alone, since its steps decide). Under `SKIP`, the lavapipe install, the Rust install arg, the cargo cache and `mise run check` are skipped by step-level `if:` and `mise run check-docs` runs instead; otherwise the steps run as today. The empty-diff step, `uv sync`, the Java and Kaitai install and the prek built-ins step are unchanged. The `check-docs` selection needs the Kaitai compiler and `STUNT_REQUIRE_KSC=1`, which `gate.py` already sets.
5. **`msrv`, `deny`, `windows-smoke`**: `if: !cancelled() && !(SKIP)`. `windows-smoke` keeps its `github.event_name == 'pull_request'` too: `!cancelled() && github.event_name == 'pull_request' && !(SKIP)`.
6. **Docs**: a new ADR (the newest is 0046, so 0047 or later) superseding ADR 0038 in part, as ADR 0044 did: ADR 0038's "CI's `quality` job runs the gate on every pull request" gives way to "for a docs-only PR it runs the docs half". `docs/quality-gate.md` (its CI paragraph) loses "run on every pull request and push rather than being path-filtered" for `msrv` and `deny`, lists all five required checks by display name, and says what skips, why a skipped job still satisfies the ruleset and why `main` stays full. Comments in `ci.yml` cite the ADR.
7. **Tests**: `tests/test_gate_plan.py` cases for the subcommand: docs-only → `true`; docs plus a Rust path, a Python path, an `other` path, no paths, an unreadable base → `false`.

## Calls the owner has not made (mine)

- `docs_only` is one boolean, not a list of halves.
- `windows-smoke` skips on docs-only: its tests are Python junction, reparse-point and build-lock tests that no Markdown change can touch.
- A new ADR rather than an amendment to ADR 0038, following ADR 0044's precedent.

## Left to the builder

- Whether `actions/setup-python` offers 3.15 and is quicker than the mise install for the `scope` job; the system `python3` is ruled out.
- Confirm `mise run check-docs` passes with `rust` in `mise.toml`'s `[tools]` but not installed and `MISE_AUTO_INSTALL=false`, as `quality` would run it. The review found no docs-marked test that calls cargo (only `test_formats_catalog.py` and `test_work_frozen.py` spawn subprocesses, and neither builds Rust), but not that the task starts without the toolchain.
- The step-level `if:` expressions, and `actionlint` over the result if it can be installed.
- The ADR number and wording.

## Verification

`gate.py scope` is unit-tested. The workflow is verified on GitHub: a docs-only PR must show `quality`, `msrv`, `deny` and `windows-smoke` passing with the last three skipped, and a PR touching a `.py` file must run everything. Both need a PR, which needs the owner's go-ahead. A deliberately failing `scope` job (a bad `--base`, or a syntax error in `gate.py`) must leave every check running. That a skipped job satisfies a required check is GitHub's documented behaviour but was not exercised here; the docs-only PR is its test.
