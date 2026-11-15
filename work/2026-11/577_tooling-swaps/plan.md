# Retire the CRLF hook, CI's commit-range check and the GPU watchdog script: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `check_crlf.py`, `check_commit_msg.py`'s range mode and `watch_render_test.py`, putting a PR-title check and an in-test GPU hang deadline where the spec says.

**Architecture:** Three pull requests from `main`, one per spec section; none stacks on another. PR B and PR C both amend ADR 0026 and edit `docs/development.md`, so merge PR B first and rebase PR C onto `main` before it merges. PR A puts a watchdog thread inside the `gpu` test binary's `gpu_test` wrapper. PR B deletes a prek hook. PR C moves the Conventional Commit check from every commit to the PR title, in a workflow of its own.

**Tech Stack:** Rust 2024 integration tests (std only), Python 3.15 scripts with pytest, prek, mise tasks, GitHub Actions.

**Spec:** [spec.md](spec.md) (approved, committed 63e3cd2a). Read it before any task; this plan does not restate its reasons.

## Global Constraints

- Every change passes `mise run check` with no warnings before its commit (AGENTS.md § Committing); `-- --full` before opening each PR.
- Stage paths by name; never `git add -A`, never `corpus/`.
- Conventional Commit subjects; a body says why when a reviewer would ask.
- ADRs change only by a dated `## Amendment YYYY-MM-DD: …` section, in the style of ADR 0026's 2026-11-05 amendment.
- A diff to `docs/*.md`, `docs/howto/` or AGENTS.md gets a fresh reviewer before push (AGENTS.md § Committing rule 5). Editing AGENTS.md: read the `writing-for-agents` skill first.
- Local prek hooks stay exactly `mise run <task>` (ADR 0026); `tests/test_prek_config.py` and `tests/test_prek_hooks.py` must agree with `prek.toml` and `ci.yml`.
- GitHub settings and the `main` ruleset are the owner's to change. PR C's body lists them; no agent changes them.
- Actions are pinned to commit SHAs, copied from `ci.yml` (`actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1`, `jdx/mise-action@6be3c7ed4c21d4f76b208d351d95aac273ebb76d # v5.2.4`).

## Review Focus

1. **A PR title holding shell metacharacters** (backticks, `$(…)`, quotes) is checked as text and never executed: the workflow passes it through `env:`, never `${{ … }}` inside `run:`. Task 5 tests this.
2. **GitHub's own revert title**, `Revert "feat: x"`, passes, as `GIT_SUBJECT` already allows in commit messages. Task 4 tests this.
3. **A title edited after the PR opens** is re-checked: the workflow's `types` include `edited` and keep `opened`, `synchronize`, `reopened`. Task 5 tests this.
4. **A GPU test that panics** disarms the watchdog as it unwinds, so no `HANG` or abort fires later in the run. Task 1 tests this.
5. **A slow but healthy GPU test on lavapipe** never trips the deadline: it is armed only after `GPU_TEST_LOCK` is held, and its default comes from a CI measurement (Task 2).

---

## PR A: GPU hang deadline (spec section 3)

Branch from `main`: `feat/gpu-test-deadline`.

### Task 1: The watchdog module

**Files:**
- Create: `crates/stunt-render/tests/gpu/common/watchdog.rs`
- Modify: `crates/stunt-render/tests/gpu/common/mod.rs` (add `pub(crate) mod watchdog;`)

**Interfaces:**
- Produces, in `common::watchdog`:
  - `pub(crate) const DEADLINE_ENV: &str = "STUNT_GPU_TEST_DEADLINE_S";`
  - `pub(crate) const DEFAULT_DEADLINE: Duration` (set to `Duration::from_secs(120)` here; Task 2 replaces the number with the measured one)
  - `pub(crate) fn parse_deadline(value: Option<&str>) -> Duration`: `None` gives `DEFAULT_DEADLINE`. A positive whole number of seconds is used as is. Anything else (empty, `0`, `abc`, `1.5`) panics with a message naming `DEADLINE_ENV` and the value.
  - `pub(crate) fn hang_message(test: &str, after: Duration) -> String`: returns `"HANG: {test} still running after {secs}s\n"`.
  - `pub(crate) struct Watchdog`, with `pub(crate) fn global() -> &'static Watchdog`. The first call spawns the one watchdog thread and creates no other. `pub(crate) fn arm(&'static self, test: &str, after: Duration) -> Armed` sets the deadline.
  - `pub(crate) struct Armed` disarms on `Drop`, so it also disarms on unwind.
  - On expiry the thread writes `hang_message` with `std::io::stderr().write_all` (not `eprintln!`, which libtest captures), then calls `std::process::abort()`.

The approach: a `Mutex<Option<(String, Instant, Duration)>>` plus a `Condvar`. The thread waits with `wait_timeout` until the armed deadline, or indefinitely while disarmed. `arm` and `Drop` notify it.

- [ ] **Step 1: Write the failing unit tests** in `mod tests` inside `watchdog.rs`:

```rust
#[test]
fn an_unset_deadline_is_the_default() { assert_eq!(parse_deadline(None), DEFAULT_DEADLINE); }
#[test]
fn a_whole_number_of_seconds_is_the_deadline() { assert_eq!(parse_deadline(Some("7")), Duration::from_secs(7)); }
#[test]
#[should_panic(expected = "STUNT_GPU_TEST_DEADLINE_S")]
fn a_zero_deadline_is_refused() { parse_deadline(Some("0")); }
#[test]
#[should_panic(expected = "STUNT_GPU_TEST_DEADLINE_S")]
fn a_non_number_is_refused() { parse_deadline(Some("abc")); }
#[test]
fn the_hang_line_names_the_test_and_the_bound() {
    assert_eq!(hang_message("renderer::draws", Duration::from_secs(120)),
               "HANG: renderer::draws still running after 120s\n");
}
#[test]
fn disarming_before_the_deadline_never_aborts() {
    // Review Focus 4: a guard dropped (here by an unwinding panic) leaves nothing armed.
    // The watchdog has one slot; hold the GPU lock, as gpu_test does, so no GPU test arms meanwhile.
    // (Spec section 3's "must not take GPU_TEST_LOCK" is about the stuck self-test, which runs in a
    // child process; this test is quick and must serialise with the GPU tests in this one.)
    let _lock = crate::common::GPU_TEST_LOCK.get_or_init(|| std::sync::Mutex::new(())).lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let result = std::panic::catch_unwind(|| {
        let _armed = Watchdog::global().arm("unwinds", Duration::from_millis(300));
        panic!("test body failed");
    });
    assert!(result.is_err());
    std::thread::sleep(Duration::from_millis(600)); // the process is still alive past the deadline
}
```

- [ ] **Step 2: Write the failing self-test.** In `mod tests`, `#[ignore] fn stuck_body()` returns at once unless `STUNT_GPU_WATCHDOG_SELFTEST=1` is set. When it is set, it arms `"stuck_body"` for 1 s and sleeps 30 s. `fn a_stuck_test_is_named_and_aborted()` runs `std::env::current_exe()` with `["common::watchdog::tests::stuck_body", "--exact", "--ignored", "--nocapture"]` and that environment variable set, then asserts:

```rust
assert!(!output.status.success());
assert!(String::from_utf8_lossy(&output.stderr).contains("HANG: stuck_body still running after 1s"));
```

It never takes `GPU_TEST_LOCK`, and the stuck body runs in the child process only.

- [ ] **Step 3: Run them to verify they fail**

Run: `mise exec -- cargo test --locked -p stunt-render --test gpu common::watchdog`
Expected: compile errors (`parse_deadline`, `Watchdog` not defined).

- [ ] **Step 4: Implement `watchdog.rs`** to the interfaces above.

- [ ] **Step 5: Run them to verify they pass**

Run: `mise exec -- cargo test --locked -p stunt-render --test gpu common::watchdog`
Expected: 7 passed, 1 ignored. The self-test finishes in about 1 s, not 30.

- [ ] **Step 6: Check for a Windows Error Reporting dialog.** Run Step 5 again on this Windows machine and watch for a WER dialog or a run that blocks after the `HANG` line. If either appears, call `SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX)` under `#[cfg(windows)]` before `abort()`. It comes from a `windows-sys` dev-dependency (`Win32_System_Diagnostic_Debug`; 0.61.2 is already in `Cargo.lock`, so `cargo deny` sees no new crate). The workspace denies `unsafe_code` and requires `undocumented_unsafe_blocks`, so the call needs `#[expect(unsafe_code, reason = …)]` and a `// SAFETY:` comment. Re-run. Record which outcome happened in the commit body.

- [ ] **Step 7: Commit**

```bash
git add crates/stunt-render/tests/gpu/common/watchdog.rs crates/stunt-render/tests/gpu/common/mod.rs
git commit -m "test(render): add a per-test hang watchdog for the gpu binary"
```

### Task 2: Arm it in `gpu_test` and measure the default

**Files:**
- Modify: `crates/stunt-render/tests/gpu/common/mod.rs` (`gpu_test`)
- Temporarily modify: `.github/workflows/ci.yml` (one measurement step, removed before merge)

**Interfaces:**
- Consumes: `Watchdog::global`, `Watchdog::arm`, `parse_deadline`, `DEADLINE_ENV`.

- [ ] **Step 1: Wire it in.** In `gpu_test`:
  - Call `Watchdog::global()` before taking `GPU_TEST_LOCK`, so the thread exists before any GPU call.
  - After the lock guard is held, `let _armed = Watchdog::global().arm(&name, parse_deadline(std::env::var(DEADLINE_ENV).ok().as_deref()));`. It must come before `Builder::new().name(name)`, which moves `name`.
  - `_armed` must drop after the scoped `join()`, which it does if it is bound before `std::thread::scope` (Review Focus 5).

- [ ] **Step 2: Run the GPU tests**

Run: `mise exec -- cargo test --locked -p stunt-render --test gpu`
Expected: all pass, no `HANG` line.

- [ ] **Step 3: Measure on lavapipe.** Push the branch and open PR A as a draft (CI runs on pull requests). Then push a temporary commit adding a step to `ci.yml`'s `quality` job, after the gate. The step:
  - sets `env: STUNT_REQUIRE_GPU: "1"` on itself (the gate step sets it at step level, so it is not inherited);
  - runs `cargo test --locked -p stunt-render --test gpu` once to build it (its features differ from the gate's `--workspace --all-features` build);
  - then runs `time cargo test --locked -p stunt-render --test gpu`.

  Read `real` from the second run. The whole-binary time is an upper bound on its slowest test.

- [ ] **Step 4: Set `DEFAULT_DEADLINE`** to `max(60, 10 × the measured seconds)`, rounded up to a multiple of 30. Put the measured figure and the CI run URL in a `///` comment on the constant. Delete the temporary CI step.

- [ ] **Step 5: Run the module tests and the GPU tests**

Run: `mise exec -- cargo test --locked -p stunt-render --test gpu`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add crates/stunt-render/tests/gpu/common/mod.rs crates/stunt-render/tests/gpu/common/watchdog.rs .github/workflows/ci.yml
git commit -m "test(render): bound every gpu_test by the hang watchdog"
```

The body gives the lavapipe measurement and the chosen default.

### Task 3: Retire the watchdog script

**Files:**
- Delete: `python/scripts/watch_render_test.py`, `tests/test_watch_render_test.py`
- Modify: `mise.toml` (replace `[tasks.test-render]`), `python/stunt_reel/process_tree.py`, `tests/test_process_tree.py`, `crates/stunt-render/tests/gpu/main.rs` (module comment), `docs/howto/run-the-gpu-tests.md`, `docs/development.md` (line 62, "stay a second binary for the hang watchdog", and line 84, the index line "under the hang watchdog"), `docs/quality-gate.md` § GPU tests (including the link text "run it under the watchdog"), `docs/adr/0016-the-gate-runs-independent-lanes.md` (amendment)

**Interfaces:**
- Produces: the mise task `test-gpu`, which has `depends = ["ensure"]`, `env = { CARGO_HOME = "{{vars.cargo_home}}" }` and runs `cargo test --locked -p stunt-render --test gpu`. Its description names the deadline and `STUNT_GPU_TEST_DEADLINE_S`.
- Produces: `process_tree.wait(proc, timeout, *, reap=REAP_SECONDS) -> tuple[int, str]`, which is today's signature without `on_timeout`.

- [ ] **Step 1: Remove `on_timeout`** from `process_tree.wait` and its docstring, and the `Callable` import it alone used (`process_tree.py:22`). In `tests/test_process_tree.py`, drop the `on_timeout=` argument from `test_timeout_kills_the_grandchild_too` and its `"hook"` assertion; the test keeps its other assertions.

- [ ] **Step 2: Run them**

Run: `mise run test-py -- tests/test_process_tree.py`
Expected: pass.

- [ ] **Step 3: Delete the script, its test and `test-render`; add `test-gpu`.**

- [ ] **Step 4: Rewrite the docs.**
  - **Howto:** `run-the-gpu-tests.md` says every GPU test aborts with a `HANG: <test>` line past its deadline. It names `STUNT_GPU_TEST_DEADLINE_S` and the default, and gives the hang-rate loop for both shells:
    - PowerShell: `$env:STUNT_REQUIRE_GPU = "1"; 1..20 | % { mise run test-gpu; if ($LASTEXITCODE) { break } }`
    - bash: `for i in $(seq 20); do STUNT_REQUIRE_GPU=1 mise run test-gpu || break; done`

    `STUNT_REQUIRE_GPU=1` replaces the old `--require-gpu`: without it a machine with no adapter skips every test and the loop passes.
  - **`quality-gate.md` § GPU tests:** the `gpu` binary stays apart from `it` so the hang-rate loop can run it alone.
  - **`main.rs` comment:** the same reason in one line.
  - **ADR 0016 amendment:** `test-render` and its watchdog script were replaced by the in-test deadline (#577).

- [ ] **Step 5: Confirm nothing still names the old pieces**

Run: `git grep -n -e test-render -e watch_render_test -e on_timeout -e "hang watchdog" -e "under the watchdog" -- . ":!work"`
Expected: matches only in `docs/adr/0016-the-gate-runs-independent-lanes.md` (its history and the new amendment).

- [ ] **Step 6: Run the gate**

Run: `mise run check -- --full`
Expected: PASS.

- [ ] **Step 7: Commit, fresh-review the docs, push, open PR A**

```bash
git add mise.toml python/stunt_reel/process_tree.py tests/test_process_tree.py crates/stunt-render/tests/gpu/main.rs docs/howto/run-the-gpu-tests.md docs/development.md docs/quality-gate.md docs/adr/0016-the-gate-runs-independent-lanes.md
git rm python/scripts/watch_render_test.py tests/test_watch_render_test.py
git commit -m "refactor(tooling): retire watch_render_test.py for the in-test GPU deadline (#577)"
```

---

## PR B: Delete `crlf-check` (spec section 1)

Branch from `main`: `chore/drop-crlf-check`.

### Task 4: Remove the hook, its task, script and tests

**Files:**
- Delete: `python/scripts/check_crlf.py`, `tests/test_check_crlf.py`
- Modify: `prek.toml` (the `crlf-check` hook), `mise.toml` (`[tasks.crlf-check]`), `tests/test_prek_config.py` (`LOCAL_HOOKS` entry and the comment naming `crlf-check`), `.github/workflows/ci.yml` (the `SKIP:` list), `docs/development.md` (the `crlf-check` table row), `docs/quality-gate.md` (pre-commit paragraph: the `crlf-check` clause and "`crlf-check` alone writes a file …"), `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md` (amendment)

- [ ] **Step 1: Delete and edit as listed.** The `SKIP:` list becomes `diff-check,fmt-check-rust,fmt-check-py,lint-py,test-docs,check-work-frozen`. The ADR 0026 amendment (`## Amendment 2026-11-DD: crlf-check is removed`) cites the spec's 2026-11-15 spike. All-CRLF files pass the formatters, mixed endings and a CRLF `MAP.md` fail the gate, and the index stores no CRLF. It supersedes the hook table's `crlf-check` row and the 2026-11-05 exception. Keep `docs/harness.md`'s advice to write LF.

- [ ] **Step 2: Run the hook tests**

Run: `mise run test-py -- tests/test_prek_config.py tests/test_prek_hooks.py`
Expected: pass (`test_ci_skips_exactly_the_local_hooks` included).

- [ ] **Step 3: Confirm nothing still names it**

Run: `git grep -n -e crlf-check -e check_crlf -- . ":!work"`
Expected: matches only inside ADR 0026's dated amendments and its 2026-11-05 history, none elsewhere.

- [ ] **Step 4: Run the gate, commit, fresh-review the docs, push, open PR B**

Run: `mise run check -- --full`. Expected: PASS.

```bash
git add prek.toml mise.toml tests/test_prek_config.py .github/workflows/ci.yml docs/development.md docs/quality-gate.md docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md
git rm python/scripts/check_crlf.py tests/test_check_crlf.py
git commit -m "chore(hooks): drop crlf-check now the formatters accept CRLF (#577)"
```

---

## PR C: Check the PR title (spec section 2)

Branch from `main`: `ci/pr-title-check`.

### Task 5: `--subject` mode, and the range mode removed

**Files:**
- Modify: `python/scripts/check_commit_msg.py`, `tests/test_check_commit_msg.py`, `tests/test_git_isolation.py:17`, `tests/test_gh_rest_only.py` (`LOCAL_ONLY`), `mise.toml` (`commit-msg-check` description), `.githooks/commit-msg` (comment)

**Interfaces:**
- Produces: `check_commit_msg.py --subject TEXT`, a positional `message` file in a required mutually exclusive group. It prints each `problems(TEXT)` problem as `[commit-msg] pull request title: <problem>` and exits 1, or exits 0. It runs no git and no trailer check.

- [ ] **Step 1: Write the failing tests** in `tests/test_check_commit_msg.py`:

```python
@pytest.mark.parametrize("title", ["feat(core): add a parser", 'Revert "feat: x"'])
def test_a_conventional_or_git_title_passes(hook: Any, title: str) -> None:
    assert hook.main(["--subject", title]) == 0

def test_a_bad_title_is_named(hook: Any, capsys: pytest.CaptureFixture[str]) -> None:
    assert hook.main(["--subject", "Update stuff"]) == 1
    assert "pull request title" in capsys.readouterr().err

def test_a_title_with_shell_text_is_only_read(hook: Any, tmp_path: Path) -> None:
    # Review Focus 1: the title is data, never run.
    marker = tmp_path / "ran"
    assert hook.main(["--subject", f"feat: $(touch {marker}) `touch {marker}`"]) == 0
    assert not marker.exists()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `mise run test-py -- tests/test_check_commit_msg.py -k title`
Expected: FAIL (`--subject` unrecognised).

- [ ] **Step 3: Implement `--subject`, and delete the range mode:** `--range`, `--pr`, `_messages`, `_in_base`, `GH_TIMEOUT`, `GitHubUnavailableError`, `_MERGED_PULLS_QUERY`, `_MERGED_PULLS_JQ`, `_merged_pulls` and `_landed_elsewhere`. Drop `json` and `shutil` if unused. In the tests, delete `_stub_github` and every test from `test_the_script_checks_a_commit_range` through `test_a_gh_call_that_times_out_makes_github_unavailable`. Rewrite the module docstring's usage and exit-status lines.

- [ ] **Step 4: Update the dependents.**
  - Set `_SCRATCH_REPO_TEST` in `tests/test_git_isolation.py` to `"tests/test_check_commit_msg.py::test_the_hook_reads_the_staged_paths"`.
  - Remove `"scripts/check_commit_msg.py"` and its comment from `LOCAL_ONLY`.
  - Reword the `commit-msg-check` description and the `.githooks/commit-msg` comment to drop `--range`.

- [ ] **Step 5: Run them**

Run: `mise run test-py -- tests/test_check_commit_msg.py tests/test_git_isolation.py tests/test_gh_rest_only.py`
Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add python/scripts/check_commit_msg.py tests/test_check_commit_msg.py tests/test_git_isolation.py tests/test_gh_rest_only.py mise.toml .githooks/commit-msg
git commit -m "refactor(hooks): check a PR title with --subject and drop the commit-range mode (#577)"
```

### Task 6: The PR-title workflow and the docs

**Files:**
- Create: `.github/workflows/pr-title.yml`
- Modify: `.github/workflows/ci.yml` (delete the "Commit messages on the pull request" step), `tests/test_check_commit_msg.py`, AGENTS.md § Committing rule 3, `docs/development.md` § Commit messages, `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md` and `docs/adr/0044-commit-messages-carry-no-gate-line.md` (amendments)

**Interfaces:**
- Consumes: `mise run commit-msg-check -- --subject TEXT` (Task 5).
- Produces: a workflow named `PR title` with one job, `title`, whose check name the owner adds to the `main` ruleset.

- [ ] **Step 1: Write the failing test** in `tests/test_check_commit_msg.py`:

```python
def test_the_title_workflow_rechecks_edits_and_never_interpolates_the_title() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr-title.yml").read_text(encoding="utf-8")
    assert re.search(r"types: \[opened, edited, synchronize, reopened\]", workflow)  # Review Focus 3
    assert "TITLE: ${{ github.event.pull_request.title }}" in workflow               # via env only
    # Every `run:` is one line here, so a line scan sees it whole; keep it so.
    run_lines = [line for line in workflow.splitlines() if "run:" in line]
    assert all("${{" not in line and not line.rstrip().endswith(("|", ">")) for line in run_lines)  # Review Focus 1
    assert 'commit-msg-check -- --subject="$TITLE"' in workflow
    assert 'MISE_AUTO_INSTALL: "false"' in workflow
    assert "name: PR title" in workflow
```

(The module defines `REPO_ROOT`; add `import re`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `mise run test-py -- tests/test_check_commit_msg.py -k workflow`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Write `pr-title.yml`.**
  - **Trigger:** `on: pull_request: types: [opened, edited, synchronize, reopened]`.
  - **Concurrency:** group `${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: true`, since `edited` fires often.
  - **Permissions:** `contents: read`.
  - **Job:** id `title`, `name: PR title`, on `ubuntu-latest`. It sets `MISE_AUTO_INSTALL: "false"` as `ci.yml`'s jobs do, so the first `mise run` installs nothing beyond `install_args`. It uses `actions/checkout` and `jdx/mise-action` at `ci.yml`'s SHAs, with `install_args: python uv`.
  - **Check step:** `env: TITLE: ${{ github.event.pull_request.title }}`, then `run: mise run commit-msg-check -- --subject="$TITLE"`. The `=` form keeps a title that starts with `-` from reading as a flag.
  - **Comment:** a header comment says why this is its own workflow, citing the spec.

- [ ] **Step 4: Delete the range step from `ci.yml`**, with its `GH_TOKEN`/`GH_REPO` env. Drop the `quality` job's `pull-requests: read` (ci.yml:35) unless another of its steps calls `gh` (check with `git grep -n "gh " .github/workflows/ci.yml`).

- [ ] **Step 5: Docs.**
  - **AGENTS.md rule 3:** a PR's title is the subject that lands on `main`, and CI checks it. Read the `writing-for-agents` skill first.
  - **`development.md` § Commit messages:** the same, replacing "No check gates the title."
  - **ADR 0026 amendment:** CI checks the PR title, not every commit.
  - **ADR 0044 amendment:** supersedes "CI's range check stays".

- [ ] **Step 6: Run the test and the gate**

Run: `mise run test-py -- tests/test_check_commit_msg.py` then `mise run check -- --full`
Expected: both pass.

- [ ] **Step 7: Commit, fresh-review, push, open PR C.** The PR body opens with the owner actions from spec section 2, and says the PR must not merge until they are done:
  - turn off rebase merging;
  - set the squash title to "Pull request title";
  - add the check `PR title` (the job's `name:`) to the `main` ruleset's required checks.

- [ ] **Step 8: Prove the title is data on Linux.** Once, set PR C's title to ``feat: $(touch /tmp/pwned) `id` "q`` and check the `PR title` job's log: it should pass and print nothing from `id`. Then restore the real title. On Windows this was checked on 2026-11-15: `mise run commit-msg-check -- '<same text>'` reached the script verbatim and created no file. The Python test in Task 5 covers only `main()`.

```bash
git add .github/workflows/pr-title.yml .github/workflows/ci.yml tests/test_check_commit_msg.py AGENTS.md docs/development.md docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md docs/adr/0044-commit-messages-carry-no-gate-line.md
git commit -m "ci: check the pull request title instead of every commit (#577)"
```

---

## Finishing

The last PR to merge writes the work README's `outcome` line. It names the three PRs and the measured GPU deadline, and closes #577.
