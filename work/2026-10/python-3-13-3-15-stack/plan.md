# Python 3.13 to 3.15 Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five stacked branches, each one commit that passes `mise run check`, that move the toolchain from Python 3.12.16 to 3.15.2 and ruff's target from py312 to py315.

**Architecture:** Each task is one branch and one PR. The upgrade tasks edit only version declarations (`mise.toml`, `pyproject.toml`, `.github/renovate.jsonc`, `docs/development.md`, `uv.lock`). The apply-ruff tasks move ruff's `target-version` and fix what it arms. Task 2 also relaxes the pin test so ruff's target can trail the pin by one minor.

**Tech Stack:** mise 2026.10, uv 0.13.1, ruff 0.17.1, mypy 2.4.0, pytest 9.1.1, `gh stack`.

**Spec:** [`python-3.13-3.15-stack-2026-10-31.md`](python-3.13-3.15-stack-2026-10-31.md). Read its Rules and Decisions sections before Task 1.

## Global Constraints

- Pins: Python `3.13.18`, `3.14.10`, `3.15.2` (the newest patch on 2026-10-31; re-check with `mise ls-remote python` and use a newer patch if one exists, in the pin, the commit body and nowhere else).
- Floors follow the pin minor: `requires-python = ">=3.13"`, `">=3.14"`, `">=3.15"`.
- Renovate cap in `.github/renovate.jsonc`, the `python` rule's `allowedVersions`: `"<3.14"`, `"<3.15"`, `"<3.16"`.
- mypy `python_version` always equals the pin's minor. Ruff `target-version` equals the pin's minor, or trails it by one between an upgrade task and its apply-ruff task.
- Upgrade commits change version declarations only, unless `mise run check` fails without a fix (spec rule 2); such a fix is named in the commit body.
- Every commit: Conventional Commit subject (given per task), a body that says why with the evidence, `mise run check passes.`, then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Stage files by name; never `git add -A`; never anything under `corpus/`.
- `uv lock` has no mise task: run `mise exec -- uv lock` (expect an approval prompt). Never a bare `uv`.
- After each pin change, run `mise install` then `mise run init` before any gate run. If `test_the_environment_runs_the_python_pin` still fails, delete this worktree's cached environment (`<repo>/.cache/venvs/python-upgrade-strategy-42329c-*`) and rerun `mise run init`.
- `test_timeout_kills_the_grandchild_too` may fail once under the parallel gate; rerun `mise run check-py` once, and name the rerun in the commit body. A second failure is a real failure.
- Do not push and do not run `gh stack submit`. The user pushes, or says to.

## Review Focus

1. A cached environment from the previous pin makes the gate fail in `test_the_environment_runs_the_python_pin`: expected, fixed by the init step, never by editing the test.
2. `uv lock` against a new floor drops resolution markers for older interpreters; the diff should contain only `requires-python`, `resolution-markers` and wheel entries, and no version of `kaitaistruct`, `mypy`, `pytest`, `pytest-cov` or `ruff` may change. If one does, revert the lock and rerun `uv lock` without `--upgrade`.
3. The relaxed pin test accepts a ruff target one minor below the pin, and rejects two minors below or any amount above (pinned by Task 2's parametrized test).
4. The `TC003` fix leaves `Iterator` used only in annotations; with no `from __future__ import annotations` in that file, it is safe only because 3.14 defers annotation evaluation, so Task 3 must run on the 3.14 pin.
5. A doc still says `3.12` after Task 4: `grep -n "3\.12" docs/development.md pyproject.toml mise.toml .github/renovate.jsonc` should show only history (the `[tool.uv]` comment in `pyproject.toml`).

---

### Task 1: Python 3.13 (PR 1, this branch)

**Files:**
- Modify: `mise.toml:11` (`python = "3.12.16"`)
- Modify: `pyproject.toml:10` (`requires-python`), `:40` (`target-version`), `:138` (`python_version`)
- Modify: `.github/renovate.jsonc:46` (`allowedVersions`)
- Modify: `docs/development.md:9` (`Python ≥ 3.12`), `:209` (`requires-python = ">=3.12"` in the "Three conventions" paragraph)
- Modify: `uv.lock` (regenerated)

**Interfaces:**
- Consumes: the plan commit already on `claude/python-upgrade-strategy-42329c`.
- Produces: branch `claude/python-upgrade-strategy-42329c` at the 3.13 commit; pin 3.13.18, ruff `py313`, mypy `3.13`.

- [ ] **Step 1: Set the 3.13 values** in the five files above: pin `3.13.18`, floor `>=3.13`, ruff `py313`, mypy `3.13`, cap `<3.14`, and both `docs/development.md` mentions to 3.13.
- [ ] **Step 2: Rebuild the environment.** Run `mise install`, `mise run init`, `mise exec -- uv lock`. Expected: `uv.lock` line 3 reads `requires-python = ">=3.13"`; Review Focus 2 holds.
- [ ] **Step 3: Gate.** Run `mise run check`. Expected: `[gate] PASS`.
- [ ] **Step 4: Commit** the five files and `uv.lock` with subject `build(python): move the toolchain to Python 3.13`. The body says ruff finds nothing new at py313 (so the target moves here too), and cites the probe in the spec.
- [ ] **Step 5: Start the stack.** Run `gh stack init claude/python-upgrade-strategy-42329c`. Expected: `gh stack view` lists one branch targeting `main`.

### Task 2: Python 3.14 upgrade and the relaxed pin test (PR 2)

**Files:**
- Modify: `mise.toml`, `pyproject.toml` (`requires-python`, mypy `python_version` only), `.github/renovate.jsonc`, `docs/development.md:9,209`, `uv.lock`
- Modify: `tests/test_toolchain_pins.py:1-10` (module docstring), `:116-124` (`test_the_python_targets_follow_the_pin`)
- Modify: `docs/development.md:209` (the target sentence)

**Interfaces:**
- Consumes: Task 1's branch.
- Produces: branch `python/3.14`; pin 3.14.10, mypy `3.14`, ruff still `py313`; a helper `_ruff_target_allowed(target: tuple[int, int], pin: tuple[int, int]) -> bool` in `tests/test_toolchain_pins.py`.

- [ ] **Step 1: Create the branch.** Run `gh stack add python/3.14`.
- [ ] **Step 2: Write the failing test** in `tests/test_toolchain_pins.py`:

```python
@pytest.mark.parametrize(
    ("target", "pin", "allowed"),
    [
        ((3, 14), (3, 14), True),
        ((3, 13), (3, 14), True),
        ((3, 12), (3, 14), False),
        ((3, 15), (3, 14), False),
    ],
)
def test_ruff_may_trail_the_pin_by_one_minor(
    target: tuple[int, int], pin: tuple[int, int], *, allowed: bool
) -> None:
    assert _ruff_target_allowed(target, pin) is allowed
```

(Add `import pytest`; it is not yet imported there.)

- [ ] **Step 3: Run it to see it fail.** Run `mise exec -- uv run pytest tests/test_toolchain_pins.py -q`. Expected: FAIL, `NameError: name '_ruff_target_allowed' is not defined`.
- [ ] **Step 4: Implement `_ruff_target_allowed`** next to `_ruff_target`. Its docstring says why: an upgrade PR moves the interpreter, and the PR above it moves ruff's target and fixes what that arms. Change `test_the_python_targets_follow_the_pin` to assert `_ruff_target_allowed(ruff_target, pin)`, with a message naming both versions; mypy's assertion stays an equality. Change "targets that follow the floor" in the module docstring to say mypy's target equals the pin and ruff's may trail it by one minor until the apply-ruff PR.
- [ ] **Step 5: Run the pin tests.** Same command. Expected: PASS, still on 3.13.
- [ ] **Step 6: Set the 3.14 values:** pin `3.14.10`, floor `>=3.14`, mypy `3.14`, cap `<3.15`, both `docs/development.md` mentions to 3.14. Leave ruff at `py313`. In the target sentence of `docs/development.md:209`, add that ruff's target may trail the pin by one minor between an upgrade PR and its apply-ruff PR.
- [ ] **Step 7: Rebuild the environment** as in Task 1 Step 2. Expected: `uv.lock` `requires-python = ">=3.14"`.
- [ ] **Step 8: Gate.** Run `mise run check`. Expected: `[gate] PASS`. Ruff stays clean because its target is still py313.
- [ ] **Step 9: Commit** all of the above with subject `build(python): move the toolchain to Python 3.14`. The body explains the pin-test relaxation (why the split needs it, and that two minors behind still fails).

### Task 3: Apply ruff for py314 (PR 3)

**Files:**
- Modify: `pyproject.toml:40` (`target-version`)
- Modify: `tests/test_doc_invariants.py:11` (`from collections.abc import Iterator`)

**Interfaces:**
- Consumes: Task 2's branch.
- Produces: branch `python/3.14-ruff`; ruff `py314`.

- [ ] **Step 1: Create the branch.** Run `gh stack add python/3.14-ruff`.
- [ ] **Step 2: See the failure.** Set ruff `target-version = "py314"`, then run `mise run check-py`. Expected: lint FAIL, one `TC003` at `tests/test_doc_invariants.py:11`.
- [ ] **Step 3: Fix by hand.** Move `from collections.abc import Iterator` under `if TYPE_CHECKING:` (import `TYPE_CHECKING` from `typing`), after the other imports. Do not use `--unsafe-fixes`, and do not add `lazy import`.
- [ ] **Step 4: Gate.** Run `mise run check`. Expected: `[gate] PASS`, including `tests/test_doc_invariants.py` at runtime on 3.14.
- [ ] **Step 5: Commit** both files with subject `refactor(python): apply ruff for the Python 3.14 target`. The body says the bump armed only `TC003`, and that `UP` found nothing.

### Task 4: Python 3.15 upgrade (PR 4)

**Files:**
- Modify: `mise.toml`, `pyproject.toml` (`requires-python`, mypy `python_version`), `.github/renovate.jsonc`, `docs/development.md:9,209`, `uv.lock`

**Interfaces:**
- Consumes: Task 3's branch; Task 2's `_ruff_target_allowed` (unchanged).
- Produces: branch `python/3.15`; pin 3.15.2, mypy `3.15`, ruff still `py314`.

- [ ] **Step 1: Create the branch.** Run `gh stack add python/3.15`.
- [ ] **Step 2: Set the 3.15 values:** pin `3.15.2`, floor `>=3.15`, mypy `3.15`, cap `<3.16`, both `docs/development.md` mentions to 3.15. Leave ruff at `py314`.
- [ ] **Step 3: Rebuild the environment** as in Task 1 Step 2. Expected: `uv.lock` `requires-python = ">=3.15"`.
- [ ] **Step 4: Gate.** Run `mise run check`. Expected: `[gate] PASS`.
- [ ] **Step 5: Commit** with subject `build(python): move the toolchain to Python 3.15`.

### Task 5: Apply ruff for py315, and the handoff (PR 5)

**Files:**
- Modify: `pyproject.toml:40`
- Modify: `tests/test_tac_adversarial.py:149-150` (`sentinel`)
- Maybe modify: `tests/test_doc_invariants.py` (only if `TC003` still fires)
- Modify: `docs/process/plans/python-3.13-3.15-stack-2026-10-31.md` (handoff)

**Interfaces:**
- Consumes: Task 4's branch.
- Produces: branch `python/3.15-ruff`; ruff `py315`. The stack is complete.

- [ ] **Step 1: Create the branch.** Run `gh stack add python/3.15-ruff`.
- [ ] **Step 2: See the failures.** Set ruff `target-version = "py315"`, then run `mise run check-py`. Expected: lint FAIL with `A001` at `tests/test_tac_adversarial.py:149`. Note whether `TC003` also fires on `tests/test_doc_invariants.py`.
- [ ] **Step 3: Fix `A001`:** rename `sentinel` to `canary` at both of its uses in `test_bda_atomic_overflow_preserves_memory`.
- [ ] **Step 4: Fix `TC003` only if Step 2 showed it:** replace the `TYPE_CHECKING` block with `lazy from collections.abc import Iterator` and drop the unused `TYPE_CHECKING` import. Otherwise leave the file alone.
- [ ] **Step 5: Gate.** Run `mise run check`. Expected: `[gate] PASS`.
- [ ] **Step 6: Write the handoff** at the end of the spec, as a `## Handoff` section: the five branch names and the SHAs of the four commits below this one, the pins used, any gate-required fix (spec rule 2), and which `TC003` form landed. Remind other checkouts to run `mise install` and `mise run init`.
- [ ] **Step 7: Commit** the code changes and the spec with subject `refactor(python): apply ruff for the Python 3.15 target`.
- [ ] **Step 8: Verify the stack.** Run `gh stack view`. Expected: five branches, the bottom targeting `main`. Then, for each branch from `claude/python-upgrade-strategy-42329c` up, check it out and run `mise install`, `mise run init` and `mise run check-py`. Expected: PASS on each. Finish on `python/3.15-ruff`.
