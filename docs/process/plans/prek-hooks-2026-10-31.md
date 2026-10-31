# prek Hooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run hooks` installs opt-in prek pre-commit hooks that run only the gate's own fast tasks plus a fixed set of prek built-ins, and a test keeps them that way.

**Architecture:** One config file (`prek.toml`), one test that reads it against `gate.STEPS`, one pin and one task in `mise.toml`, and three doc touches. No Python or Rust code beyond the test.

**Tech Stack:** prek 0.5.5 (pinned through mise), Python 3.12 `tomllib`, pytest.

**Spec:** [ADR 0026](../../adr/0026-commit-hooks-run-the-gates-own-tasks.md)

## Global Constraints

- Every `repo = "local"` hook: `id` is a task in `gate.STEPS`, `entry` is exactly `mise run <id>`, `language = "system"`, `pass_filenames = false`, no `args`.
- The local hooks are exactly `fmt-check-rust` (`types = ["rust"]`), `fmt-check-py` (`types = ["python"]`) and `lint-py` (`types = ["python"]`).
- The builtin hooks are exactly `check-added-large-files`, `check-illegal-windows-names`, `check-case-conflict`, `check-merge-conflict`, `check-toml`, `check-yaml`, `detect-private-key`. No fixers.
- Only `local` and `builtin` repositories; no `rev` anywhere.
- `default_install_hook_types = ["pre-commit"]`.
- prek pin `"0.5.5"` lives only in `mise.toml` `[tools]`; `[tasks.hooks]` runs `prek install`.
- Stage by name, never `git add -A` (AGENTS.md SOP 3). Commit trailers: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and the session line.

## Review Focus

1. A hook that runs a non-step task such as `mise run check` (recursion, a minute per commit): refused because `check` is not in `gate.STEPS` — `test_local_hooks_run_a_gate_step`.
2. A hook entry with extra flags (`mise run lint-py -- --fix`) or an `args` key, which would rewrite files or diverge from the gate: refused by exact entry equality and `test_local_hooks_take_no_arguments`.
3. A fixer built-in (`trailing-whitespace`, `end-of-file-fixer`) slipped in: refused by the exact built-in set.
4. A remote hook repository with its own `rev` (the original drift): refused by `test_only_local_and_builtin_repositories`.
5. A `pre-push` hook type that would overwrite the untracked noreply `pre-push` hook: refused by `test_installs_only_the_pre_commit_shim`.

---

### Task 1: `prek.toml` and the test that holds it to the gate

**Files:**
- Create: `tests/test_prek_config.py`
- Create: `prek.toml`

**Interfaces:**
- Consumes: `gate.STEPS: dict[str, list[str]]` from `python/scripts/gate.py`, imported the way `tests/test_gate_plan.py` does.
- Produces: `prek.toml`, read by Task 2's docs and by prek.

- [ ] **Step 1: Write the failing test.** Module docstring cites ADR 0026. Load `prek.toml` with `tomllib` from `REPO_ROOT` (pattern of `tests/test_toolchain_pins.py`). Helpers `_config() -> dict[str, Any]` (the parsed file) and `_hooks(repo: str) -> list[dict[str, Any]]`, which returns the hooks of every `[[repos]]` with that `repo`. Tests:

```python
GATE_HOOKS = {"fmt-check-rust": ["rust"], "fmt-check-py": ["python"], "lint-py": ["python"]}
BUILTINS = {"check-added-large-files", "check-illegal-windows-names", "check-case-conflict",
            "check-merge-conflict", "check-toml", "check-yaml", "detect-private-key"}

def test_local_hooks_run_a_gate_step():
    steps = {*gate.STEPS["rust"], *gate.STEPS["py"]}
    for hook in _hooks("local"):
        assert hook["id"] in steps
        assert hook["entry"] == f"mise run {hook['id']}"
        assert hook["language"] == "system"

def test_local_hooks_take_no_arguments():
    for hook in _hooks("local"):
        assert hook["pass_filenames"] is False
        assert "args" not in hook

def test_local_hooks_are_the_adr_set():
    assert {h["id"]: h["types"] for h in _hooks("local")} == GATE_HOOKS

def test_builtin_hooks_are_the_adr_set():
    assert {h["id"] for h in _hooks("builtin")} == BUILTINS

def test_only_local_and_builtin_repositories():
    assert {r["repo"] for r in _config()["repos"]} == {"local", "builtin"}
    assert all("rev" not in r for r in _config()["repos"])

def test_installs_only_the_pre_commit_shim():
    assert _config()["default_install_hook_types"] == ["pre-commit"]

def test_prek_is_pinned_and_installed_through_mise():
    mise = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+\.\d+\.\d+", mise["tools"]["prek"])
    assert mise["tasks"]["hooks"]["run"] == "prek install"
```

- [ ] **Step 2: Run it and see it fail.** `uv run pytest tests/test_prek_config.py -q` → errors with `FileNotFoundError` for `prek.toml`.
- [ ] **Step 3: Write `prek.toml`.** Header comment pointing at ADR 0026 and saying "add a gate step first, or a built-in". Top-level `default_install_hook_types`; one `[[repos]] repo = "local"` with the three `[[repos.hooks]]` (`name` = the step's mise description in short); one `[[repos]] repo = "builtin"` listing the seven ids. Nothing else.
- [ ] **Step 4: Run it.** Same command → the six `prek.toml` tests pass, `test_prek_is_pinned_and_installed_through_mise` still fails (`KeyError: 'prek'`); Task 2 fixes it.
- [ ] **Step 5: Commit** `test(hooks): hold prek.toml to the gate's own steps` with `prek.toml` and the test.

### Task 2: Pin, task and docs

**Files:**
- Modify: `mise.toml` (`[tools]` after `cargo:cargo-llvm-cov`; `[tasks.hooks]` after `[tasks.reap]`)
- Modify: `docs/development.md` (new short subsection right after the gate paragraph at line 153)
- Modify: `README.md:35` block, `CONTRIBUTING.md:19`

- [ ] **Step 1: Pin and task.** `prek = "0.5.5"` with a one-line comment (opt-in commit hooks, ADR 0026). `[tasks.hooks]` description: `"Install the opt-in prek pre-commit hooks (ADR 0026): the gate's fmt and lint checks plus prek built-ins"`, `run = "prek install"`.
- [ ] **Step 2: Docs.** `docs/development.md` subsection "Commit hooks (optional)": what runs, that it checks the whole tree, `mise run fmt` to fix, `--no-verify` to skip, one install serves every worktree, `pre-push` untouched, link ADR 0026. README: add `mise run hooks   # optional: fmt and lint checks at commit` under the `mise run check` line. CONTRIBUTING: one clause after the gate bullet.
- [ ] **Step 3: Verify.** `uv run pytest tests/test_prek_config.py tests/test_toolchain_pins.py tests/test_doc_invariants.py -q` → all pass. Then `mise run check` where mise is available; otherwise `uv run ruff format --check . && uv run ruff check . && uv run mypy` and record which parts of the gate did not run.
- [ ] **Step 4: Commit** `build(hooks): pin prek and add mise run hooks`, body naming the parts of the gate that ran.

### Task 3: Live check on the maintainer's Windows checkout (manual)

Not runnable from a session without network access to GitHub releases.

- [ ] `git fetch && git switch prek-hooks` (or a worktree), `mise install prek`, `mise run hooks` → `.git/hooks/pre-commit` exists, `.git/hooks/pre-push` unchanged.
- [ ] `prek validate-config` → no errors (confirms the `builtin` and `default_install_hook_types` TOML spelling the docs did not show).
- [ ] `prek run --all-files` → all pass; if a built-in flags existing files, fix the files or record the exclusion in ADR 0026.
- [ ] Stage a misformatted `.py`, `git commit` → blocked by `fmt-check-py`; `mise run fmt` → commit succeeds.
