# prek Runs the Commit Hooks: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `.githooks/pre-commit` → `mise run pre-commit` → `prek run --config prek.toml`, with `gate.py staged` removed and the built-ins also checked in CI.

**Architecture:** #32's installation stays (committed `.githooks/`, `core.hooksPath` set by `mise run init`). Only the `pre-commit` task changes: it runs prek over `prek.toml`, whose local hooks are each `mise run <leaf task>` and whose other hooks are prek built-ins. `gate.py` goes back to `all|rust|py`.

**Tech Stack:** prek 0.5.5 (mise-pinned), Python 3.12 `tomllib`, pytest, GitHub Actions.

**Spec:** [ADR 0026](../../adr/0026-commit-hooks-run-the-gates-own-tasks.md). This file replaces the plan for the earlier opt-in design.

## Handoff (2026-10-31)

Executed. Tasks 1–4 landed as planned, plus CodeRabbit's two plan comments: `diff-check` is
`always_run`, and CI's built-ins step also runs on pushes to `main` (from the previous tip) and
on manual runs (`--all-files`). The whole-branch review found that in CI, with nothing staged
and no merge in progress, `check-added-large-files` and `check-merge-conflict` read nothing;
they now take `--enforce-all` and `--assume-in-merge`, pinned by
`test_ci_built_ins_catch_a_committed_change`. Task 5 passed on Windows: a staged clean `.py`
with an unstaged ruff error commits and keeps the edit; a misformatted `.rs` in a crate is
blocked; a delete-only `GLOSSARY.md` commit runs `test-docs` and is blocked; a detached `main`
worktree runs its own `gate.py staged` hook. A worktree-scoped absolute `core.hooksPath` (set
outside `mise run init`) overrides the shared relative one and makes every branch run the
primary checkout's hook; unset it with `git config --worktree --unset core.hooksPath`.

## Global Constraints

- Local hooks are exactly: `diff-check` (no file filter), `fmt-check-rust` (`types = ["rust"]`), `fmt-check-py` and `lint-py` (`types = ["python"]`), `test-docs` (`always_run = true`). Each has `entry = "mise run <id>"`, `language = "system"`, `pass_filenames = false`.
- Built-ins are exactly `check-added-large-files`, `check-illegal-windows-names`, `check-case-conflict`, `check-merge-conflict`, `check-toml`, `check-yaml`, `detect-private-key`. No fixers.
- Only `local` and `builtin` repositories; no `rev`; no `default_install_hook_types` (nothing is installed by prek).
- `[tasks.pre-commit] run = "prek run --config prek.toml"`; `[tasks.diff-check] run = "git diff --cached --check"`; `[tasks.hooks]` is deleted; `prek = "0.5.5"` stays in `[tools]`.
- CI `SKIP` value is the comma-joined local hook ids, in `prek.toml` order.
- Stage by name, never `git add -A` (AGENTS.md SOP 3). Commit trailers: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and the session line.

## Review Focus

1. A commit that only deletes a Markdown page: prek passes no deleted files to hooks, so `test-docs` must not depend on file types. Pinned by `test-docs` having `always_run = true` in `test_local_hooks_fire_as_the_adr_says` (Task 1); the ADR table says so (Task 4).
2. A commit with unstaged edits: hooks must judge the staged content. Pinned by `test_prek_checks_the_staged_content` both ways (Task 3).
3. The CI `SKIP` list drifting from the local hooks, which would re-run a gate step or silently skip a built-in. Pinned by `test_ci_skips_exactly_the_local_hooks` (Task 3).
4. A machine without prek: `mise run pre-commit` should fail loudly, not pass. mise reports the missing tool; `STUNT_REQUIRE_PREK=1` in the gate makes the integration test fail rather than skip (Task 3).
5. A checkout of a branch from before this change: `core.hooksPath` is the relative `.githooks`, so it runs that branch's own hook. Not testable offline; Task 5 checks it by hand.

---

### Task 1: `prek.toml`, the mise tasks, and the config test

**Files:**
- Modify: `prek.toml`, `mise.toml` (`[tools]` comment at the prek pin, delete `[tasks.hooks]`, add `[tasks.diff-check]` beside `[tasks.test-docs]`, change `[tasks.pre-commit]`), `.githooks/pre-commit` (comment only)
- Rewrite: `tests/test_prek_config.py`

**Interfaces:**
- Produces: `prek.toml` local hook ids in order `diff-check, fmt-check-rust, fmt-check-py, lint-py, test-docs` (Task 3's `SKIP` test reads them); `tests/test_prek_config.py` helpers `_config() -> dict[str, Any]`, `_hooks(repo: str) -> list[dict[str, Any]]`, `_mise() -> dict[str, Any]` (Task 3 reuses `_hooks`).

- [x] **Step 1: Rewrite the test.** Keep `_config` and `_hooks`; add `_mise()` (parsed `mise.toml`). Replace `GATE_HOOKS` and `LOCAL_HOOK_KEYS` with:

```python
LOCAL_HOOKS = {
    "diff-check": {},
    "fmt-check-rust": {"types": ["rust"]},
    "fmt-check-py": {"types": ["python"]},
    "lint-py": {"types": ["python"]},
    "test-docs": {"always_run": True},
}
REQUIRED_KEYS = {"id", "name", "entry", "language", "pass_filenames"}
TRIGGER_KEYS = {"types", "always_run"}


def test_local_hooks_run_a_leaf_mise_task():
    tasks = _mise()["tasks"]
    for hook in _hooks("local"):
        assert hook["entry"] == f"mise run {hook['id']}"
        assert hook["language"] == "system"
        task = tasks[hook["id"]]
        assert "run" in task and "depends" not in task


def test_local_hooks_take_no_arguments():
    for hook in _hooks("local"):
        assert hook["pass_filenames"] is False
        assert REQUIRED_KEYS <= set(hook) <= REQUIRED_KEYS | TRIGGER_KEYS


def test_local_hooks_fire_as_the_adr_says():
    assert [h["id"] for h in _hooks("local")] == list(LOCAL_HOOKS)
    for hook in _hooks("local"):
        assert {k: hook[k] for k in TRIGGER_KEYS & set(hook)} == LOCAL_HOOKS[hook["id"]]


def test_pre_commit_task_runs_prek():
    tasks = _mise()["tasks"]
    assert tasks["pre-commit"]["run"] == "prek run --config prek.toml"
    assert tasks["diff-check"]["run"] == "git diff --cached --check"
    assert "hooks" not in tasks
    assert re.fullmatch(r"\d+\.\d+\.\d+", _mise()["tools"]["prek"])


def test_prek_installs_nothing():
    assert "default_install_hook_types" not in _config()
```

Keep `test_builtin_hooks_are_the_adr_set` and `test_only_local_and_builtin_repositories` unchanged; drop the `gate` import.

- [x] **Step 2: Run it.** `uv run pytest tests/test_prek_config.py -q` → fails: `KeyError: 'diff-check'` and the `pre-commit` task still runs `gate.py staged`.
- [x] **Step 3: Implement.** Rewrite `prek.toml`'s header comment for the new flow (committed hook → `mise run pre-commit` → prek; no install), drop `default_install_hook_types`, set the five local hooks in the order above. In `mise.toml`: the `[tools]` comment says the hooks run through `mise run pre-commit`; delete `[tasks.hooks]`; add `[tasks.diff-check]` (description: "Staged conflict markers and whitespace errors (git diff --cached --check); a pre-commit hook"); `[tasks.pre-commit]` description "What the pre-commit hook runs: prek over prek.toml (ADR 0026)" and the run above; update the comment above it and `test-docs`'s description ("…the pre-commit hook runs it on every commit"). `.githooks/pre-commit` comment: `mise run pre-commit` runs prek over `prek.toml`.
- [x] **Step 4: Run it.** Same command → all pass. Also `uv run pytest tests/test_git_hooks.py -q` still passes (the hook's command line is unchanged).
- [x] **Step 5: Commit** `feat(hooks): run the pre-commit hook through prek` with the four files.

### Task 2: Remove `gate.py staged`

**Files:**
- Modify: `python/scripts/gate.py` (docstring lines 22–29, `STAGED_LOG_PATH`, `"test-docs"` in `STEP_LANES`, `STAGED_STEPS`, `STAGED_MARKDOWN_STEPS`, `DIFF_CHECK`, `_staged_plan`, `_git`, `_staged_paths`, `_diff_check`, the `staged` branches in `main`), `tests/test_gate_plan.py:23-25`, `tests/test_git_hooks.py` (docstring, the message at line 73, delete the tests at lines 86–133)

- [x] **Step 1: Tighten the tests.** In `test_gate_plan.py` the lane assertion goes back to `sorted(gate.STEP_LANES) == sorted(steps)` with message "STEP_LANES must name every step, and only steps". Add:

```python
def test_the_gate_has_no_staged_half():
    with pytest.raises(SystemExit):
        gate.main(["staged"])
```

- [x] **Step 2: Run them.** `uv run pytest tests/test_gate_plan.py -q` → both fail (`test-docs` lane present; `staged` accepted).
- [x] **Step 3: Implement.** Delete the listed code; `argparse` choices back to `("all", "rust", "py")`; the log path is always `LOG_PATH`; the docstring's usage line back to `{all|rust|py}`. In `test_git_hooks.py` delete `test_every_staged_step_is_a_leaf_task_with_a_lane`, `test_markdown_brings_in_the_doc_invariants`, `test_staged_conflict_markers_fail_the_diff_check`, `test_deleting_markdown_brings_in_the_doc_invariants`; the docstring and the line-73 message point at `prek.toml` (ADR 0026) instead of `gate.py staged`.
- [x] **Step 4: Run them.** `uv run pytest tests/test_gate_plan.py tests/test_git_hooks.py tests/test_prek_config.py -q` → pass; `uv run ruff check python tests` and `uv run mypy` clean (no unused imports such as `shutil` left behind).
- [x] **Step 5: Commit** `refactor(gate): drop the staged plan prek now runs`.

### Task 3: Prove the staged-content claim, and run the built-ins in CI

**Files:**
- Create: `tests/test_prek_hooks.py`
- Modify: `python/scripts/gate.py` (`REQUIRED_ENV["test-py"]` gains `"STUNT_REQUIRE_PREK": "1"`), `.github/workflows/ci.yml` (`quality` job)

**Interfaces:**
- Consumes: `_hooks` from `tests/test_prek_config.py` (import it, or re-read `prek.toml` the same way).

- [x] **Step 1: Write the tests.** A `prek` fixture: `shutil.which("prek")`; if absent, `pytest.fail` when `STUNT_REQUIRE_PREK` is set, else `pytest.skip`. A scratch repo built like `tests/test_git_hooks.py::_repo`, with its own `prek.toml` holding only `[[repos]] repo = "builtin"` + `check-toml`, and `a.toml` committed as `x = 1`.

```python
def test_prek_checks_the_staged_content(prek, tmp_path):
    # staged valid, unstaged broken -> passes, and the broken edit is restored
    ...  # stage `x = 2`, then write `x = ` without staging
    assert run(prek, "run", "--config", "prek.toml").returncode == 0
    assert (repo / "a.toml").read_text() == "x = \n"
    # staged broken, unstaged fixed -> fails
    ...
    assert run(prek, "run", "--config", "prek.toml").returncode != 0


def test_ci_skips_exactly_the_local_hooks():
    ci = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    skip = re.search(r"SKIP: (\S+)", ci).group(1)
    assert skip.split(",") == [h["id"] for h in _hooks("local")]
```

Isolate git env vars as `test_git_hooks.py` does.
- [x] **Step 2: Run them.** `uv run pytest tests/test_prek_hooks.py -q` → the CI test fails (no `SKIP` yet); the prek test skips where prek is absent.
- [x] **Step 3: Implement.** `REQUIRED_ENV` as above. In `ci.yml` `quality`: `fetch-depth: 0` on checkout; add `prek` to the mise `install_args`; after "Run quality tasks", a step "Commit-hook built-ins on the PR's changes", `if: github.event_name == 'pull_request'`, `env: SKIP: diff-check,fmt-check-rust,fmt-check-py,lint-py,test-docs`, `run: mise exec -- prek run --config prek.toml --from-ref origin/${{ github.base_ref }} --to-ref HEAD`, with a comment citing ADR 0026.
- [x] **Step 4: Run them.** Same command → the CI test passes. On the PR, CI must show the integration test passed (not skipped) under the gate, and the new step green.
- [x] **Step 5: Commit** `test(hooks): prove prek checks what is staged; run its built-ins in CI`.

### Task 4: Docs

**Files:**
- Modify: `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md` (hook table: `test-docs` fires on every commit, with the reason; key list adds `always_run`), `docs/development.md:158` (the `pre-commit` row) and `:179` (the hook paragraph), `README.md:36` (delete the `mise run hooks` line), `CONTRIBUTING.md:20-21` (delete the `mise run hooks` sentence)

- [x] **Step 1: Edit.** The `pre-commit` row and paragraph say: `mise run init` installs the committed hook; it runs `mise run pre-commit`, which is prek over `prek.toml`; prek checks the staged content; list the hooks; `mise run fmt` to fix; `--no-verify` to skip; CI runs the built-ins; link ADR 0026.
- [x] **Step 2: Verify.** `uv run pytest tests/test_doc_invariants.py -q` passes; `grep -rn "gate.py staged\|mise run hooks\|STAGED_" --include=*.md --include=*.py --include=*.toml .` finds nothing outside `docs/process/`.
- [x] **Step 3: Commit** `docs(hooks): describe the prek-run commit hook`, then `mise run check` (or the parts this session can run, named in the body).

### Task 5: Live check (maintainer, Windows)

- [x] `git switch prek-hooks`, `mise install`, `mise run init` → `core.hooksPath` is `.githooks`.
- [x] Commit a staged clean `.py` with an unstaged ruff error in the same file → succeeds; the unstaged edit is still there.
- [x] Stage a misformatted `.rs` → the commit is blocked by `fmt-check-rust`.
- [x] Commit that only deletes a linked `.md` → `test-docs` runs.
- [x] In a worktree on a branch from before this change → the commit runs that branch's own hook.
