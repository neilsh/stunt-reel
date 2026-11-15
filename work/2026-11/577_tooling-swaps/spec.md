# Spec: retire the CRLF hook, CI's commit-range check and the GPU watchdog script

Issue [#577](https://github.com/neilsh/stunt-reel/issues/577). Agreed in a brainstorming session on 2026-11-15, revised after a fresh review and a CRLF spike the same day.

## Why

Two driving factors, in the owner's words: **fewer lines to maintain** and **more trustworthy checks**. A survey of `python/scripts/`, `python/stunt_reel/` and the hooks found four candidates for replacement by prek built-ins or established tools. Review and spikes left three, and in each the custom code goes rather than being swapped for a new tool: the problem it solved is gone (CRLF), is moved to a cheaper place (commit subjects), or is caught closer to its cause (GPU hangs). The fourth, lychee for local Markdown links, was dropped (Non-goals).

## Goals

1. **CRLF hook.** Delete `check_crlf.py` (250 lines), `tests/test_check_crlf.py` (465 lines), the `crlf-check` task and its prek hook, with nothing in their place.
2. **Commit subjects.** Make the PR title the subject a merged PR puts on `main`, check the title in CI, and delete the range mode of [`check_commit_msg.py`](../../../python/scripts/check_commit_msg.py) (`--range`, `--pr`, `git cherry`, the `gh` merged-PR query) with its tests.
3. **GPU hang watchdog.** Delete `watch_render_test.py` (391 lines), `tests/test_watch_render_test.py` (91 lines) and the `test-render` task; a hang deadline inside the GPU tests' `gpu_test` wrapper takes over.

## Non-goals

- `gate.py`, `process_tree.py` (stays: `gate.py`, `parity_pipeline.py` and `tests/test_prek_hooks.py` use it), `move_docs.py`, `pr_threads.py`, the worktree tools, `doc_health`, `knowledge_map`, `cli.py`, `frontmatter.py`: project-specific, or chosen deliberately in an ADR.
- Running `gate.py` under `uv` so psutil could replace `process_tree.py` (ADR 0014's plain-`python` bootstrap stays).
- cargo-nextest, for the GPU tests or the gate (see Approaches).
- Upstream prek hook repositories; ADR 0026's rule that every local hook is `mise run <task>` stands.
- Stricter commit rules (subject length, imperative mood) from `committed` or commitizen.
- **lychee for local Markdown links** (dropped 2026-11-15). A spike found it accurate: 0 errors over the repo's 2,420 links in ~0.1 s, a missing file and a missing heading flagged on scratch files, and slugs matching `markdown_links.slug()` on tricky headings. But it cannot express today's rules: `_check_link` in `tests/test_doc_invariants.py` skips the heading check only for a link from a dated record to an evergreen file, while dated-to-dated links and the evergreen `work/README.md` keep it; `.ignore` hides all of `/work/` from lychee; and `LINK_SOURCES_SKIPPED` pauses the check mid-move. Most of the custom code would stay, lychee would join CI's `install_args` and the gate's steps, and the saving was close to nothing. ADR 0041 had already rejected lychee for internal links, because code cites documents by anchor token.
- A prek built-in (`mixed-line-ending --fix=lf`) for CRLF. A fixer that rewrites a file fails the commit, which would fail commits whose staged content was already correct: the cost ADR 0026's 2026-11-05 amendment fixed ([#219](https://github.com/neilsh/stunt-reel/issues/219)). Because prek sets unstaged edits aside before its hooks run (`prek.toml`'s header), a file with unstaged edits would be checked in its staged form, not its CRLF working copy. It picks files by `identify` types, not `.gitattributes`. These follow from prek's documented behaviour and ADR 0026; none was run.

## Anti-goals

- **An unrecorded loss.** Where a check goes, what it caught and where that is now caught (or that it no longer is) is stated per change below, backed by a test or a recorded spike.
- **Two copies of one rule.** For example, a Conventional Commit types list kept in a GitHub Action's config and in `check_commit_msg.py`.
- **A check that stops running somewhere today's runs** (local hook, gate, CI), or that only runs when someone remembers to run it, except the accepted losses listed per change.
- **Bringing back a cost an ADR recorded and fixed.** For example, rejecting commits whose staged content is already correct (ADR 0026's 2026-11-05 amendment, [#219](https://github.com/neilsh/stunt-reel/issues/219)); deleting `crlf-check` rejects no commit.

## Constraints

- AGENTS.md: `mise run check` passes; Conventional Commit subjects; a fresh reviewer reads any diff to `docs/*.md`, `docs/howto/` or `research/` before push.
- ADR 0026: local prek hooks are exactly `mise run <task>` for a leaf task; [`tests/test_prek_config.py`](../../../tests/test_prek_config.py) and `test_ci_skips_exactly_the_local_hooks` in [`tests/test_prek_hooks.py`](../../../tests/test_prek_hooks.py) enforce the hook sets and CI's `SKIP` list.
- ADRs are immutable except by a dated amendment note (as ADR 0026 already carries), or a new ADR that supersedes part of one.
- CI's `quality` job installs only the tools in its `install_args` (`.github/workflows/ci.yml`), with `MISE_AUTO_INSTALL=false`.
- GitHub repository settings and the `main` ruleset are changed by the owner, not by an agent.

## Approaches considered

| Area | Considered | Chosen | Why |
| --- | --- | --- | --- |
| Overall scope | (1) whole-file swaps only; (2) plus the commit-message swap; (3) plus running the gate under `uv` for psutil | **(2)** | Owner's pick. (3) breaks the gate's stale-`uv` guard, which cannot run if `uv` launched the gate. |
| CRLF | prek's `mixed-line-ending`; keep `crlf-check`; **delete it** | **Delete** | Owner's pick after the spike in section 1. The built-in is ruled out under Non-goals. |
| Commit subjects | `committed`/commitizen/cocogitto per commit; gitlint plus a custom trailer rule; **check the PR title** | **PR title** | The subject regex is ~20 lines; the cost is the range mode, which exists only because every PR commit is checked. gitlint's last release (2023) fails ADR 0010's two-year bar, and none of the per-commit tools skip a squash-merged parent's commits (#228). |
| GPU watchdog | cargo-nextest; retire the script with nothing in its place; keep it; **in-test deadline** | **In-test deadline** | The recorded hang ([`docs/quality-gate.md`](../../../docs/quality-gate.md) § GPU tests) is two tests deadlocking inside one process. nextest runs each test in its own process, so it cannot reproduce that hang; ADR 0016 also rejected it for paying ~2.2 s of adapter setup per test, against a per-process cost it measured when the binary held 16 tests (it holds about twice that now). Retiring with nothing in place leaves a regression to the gate's 1,800 s step timeout, which names no test. |
| Local links | markdown-it-py; lychee offline; **keep the test** | **Keep** | Owner's pick; see Non-goals. |

## The design

Independent pull requests, any order; each amends the docs and ADRs it touches.

### 1. CRLF: delete `crlf-check`

**Spike, 2026-11-15: does a CRLF working copy still break anything?** The check was added (#119, 2026-11-02) because `fmt-check-py` failed on a CRLF working copy after a 108 s gate run. Six tracked files (`AGENTS.md`, `research/MAP.md`, `docs/quality-gate.md`, `python/stunt_reel/hashing.py`, `crates/stunt-core/src/lib.rs`, `prek.toml`) were rewritten byte-exactly to all-CRLF, the checks below run, and the files restored with `git checkout-index -f`:

| Check | All-CRLF file | Mixed-ending file (scratch copy, every other line CRLF) |
| --- | --- | --- |
| `fmt-check-py` (`ruff format --check`, `line-ending = "auto"`) | pass | **fail** |
| `lint-py` (`ruff check`) | pass | pass |
| `fmt-check-rust` (`cargo fmt --check`, `newline_style = "Auto"`) | pass | not measured |
| `test-docs` (doc invariants) | pass | not measured |
| `knowledge-map -- --check` (gate test `test_research_map_is_current`) | **fail**: compares `MAP.md`'s bytes | not measured |

So an all-CRLF file passes the formatters and lint. "No longer" cannot be claimed: `line-ending = "auto"` and `newline_style = "Auto"` both date from 2026-10-17 (27e844f4), before #119, so #119's failure was probably a file with mixed endings, which still fails `ruff format --check`. That case moves from commit time to the gate (Accepted loss).

Other readers of tracked text files' bytes, checked by reading the code (not run):

- `test_research_map_is_current` decodes `MAP.md` and compares it with `render_map`, so CRLF fails it, as the spike showed. `mise run fix` runs `knowledge-map -- --write`, which rewrites it (not run in the spike).
- `test_agents_md_fits_its_budget` counts AGENTS.md's bytes: 7,262 bytes in 76 lines, about 7,338 as all-CRLF, under its 8,192 limit with about 850 bytes to spare.
- `doc_health.py` counts bytes but only reports.
- The Rust readers (for example `report_doc.rs`) read with `read_to_string` and parse lines, which tolerates CRLF.

**Change:**

- Delete `python/scripts/check_crlf.py`, `tests/test_check_crlf.py`, the `crlf-check` task in `mise.toml` and its hook in `prek.toml`.
- Update `tests/test_prek_config.py`, CI's `SKIP` list in `.github/workflows/ci.yml` and `test_ci_skips_exactly_the_local_hooks` in `tests/test_prek_hooks.py`.
- Docs: ADR 0026 gets an amendment note (its hook table and its 2026-11-05 `crlf-check` exception, citing this spike); `docs/quality-gate.md`'s pre-commit paragraph; `docs/development.md` and `docs/harness.md` wherever they name `crlf-check` or warn about CRLF from text-mode writes (the builder greps for both).
- **Accepted loss:** a Python file with mixed line endings, or a CRLF `MAP.md`, fails `mise run check` instead of the commit hook, and `mise run fix` should repair both (`ruff format` and `knowledge-map -- --write`; not run in the spike). A Markdown, TOML or YAML file with CRLF or mixed endings is checked by nothing, which is harmless: CRLF never reaches a commit, because `.gitattributes` (`* text=auto eol=lf`) normalises what `git add` stores; on 2026-11-15 `git ls-files --eol` showed 0 of 955 tracked files stored with CRLF or mixed endings.

### 2. Commit subjects: check the PR title

- **Owner actions** (an agent cannot make these):
  - in the repository settings, turn off "Allow rebase merging" and set squash merges' default commit message title to "Pull request title";
  - add the new PR-title job to the `main` ruleset's required checks, or the check is advisory.

  State on 2026-11-15, read with `gh api repos/neilsh/stunt-reel`: `allow_squash_merge` true, `allow_merge_commit` false, `allow_rebase_merge` true, `squash_merge_commit_title` `COMMIT_OR_PR_TITLE`, `squash_merge_commit_message` `COMMIT_MESSAGES`. The message body stays "Commit messages", so each commit's trailers still reach `main`. The PR is built without waiting for these, but its body says they must be made before it merges, since deleting `--range` while rebase merging is allowed would let unchecked subjects land.
- **CI:** a new workflow file (for example `.github/workflows/pr-title.yml`), not a job in `ci.yml`: `ci.yml`'s `pull_request` trigger and `cancel-in-progress` are workflow-wide, so adding `edited` there would re-run `quality`, `windows-smoke` and `msrv` on every title or body edit and cancel a gate in flight. The new workflow runs on `pull_request` with `types: [opened, edited, synchronize, reopened]` (naming `types` replaces the defaults, so all four are listed), installs only `python uv`, and sets no `SKIP:` (which `test_ci_skips_exactly_the_local_hooks` looks for). It checks `github.event.pull_request.title` with `check_commit_msg.py`'s own subject rule (for example a `--subject <text>` mode), so the types list exists once. A third-party PR-title Action was set aside because it would hold a second types list (anti-goal 2). Remove the `--range` step from the `quality` job.
- **Keep locally:** the commit-msg hook's subject check (`gh pr create --fill` takes a one-commit PR's title from its subject) and the `Fresh-review:` trailer check on staged work `spec.md`/`plan.md`. CI has never checked the trailer (the script's docstring: "a range is not checked for it"), so nothing is lost there.
- **Delete:** `--range`, `--pr`, `_messages`, `_in_base`, `_merged_pulls`, `_landed_elsewhere`, `GitHubUnavailableError` and their tests.
- **Dependents to update:**
  - `tests/test_git_isolation.py` names `test_the_script_checks_a_commit_range` as its scratch-repository test (`_SCRATCH_REPO_TEST`); point it at a test that remains, uses the `repo` fixture and reports "1 passed", such as `test_the_hook_reads_the_staged_paths`.
  - `tests/test_gh_rest_only.py` keeps `scripts/check_commit_msg.py` in `LOCAL_ONLY` because of `--range`; remove the entry.
  - The script's module docstring, the `commit-msg-check` task description in `mise.toml`, and the comment in `.githooks/commit-msg`.
- **Docs:**
  - AGENTS.md § Committing rule 3 and `docs/development.md` § Commit messages say the PR title is the subject that lands; replace that section's "No check gates the title."
  - Amendment notes on ADR 0026's commit-msg section and on ADR 0044, whose decision says "CI's range check stays".
  - The `running-unattended` skill already arms `--squash`.
- **Accepted losses:** commits inside a PR are checked only by the local hook, not in CI. An admin's direct push to `main` skips the title check, as it skips the range check today.

### 3. GPU hang: a deadline inside `gpu_test`

In [`crates/stunt-render/tests/gpu/common/mod.rs`](../../../crates/stunt-render/tests/gpu/common/mod.rs):

- Start **one** watchdog thread per process, before the first GPU call (for example when `GPU_TEST_LOCK` is first initialised). Creating a thread on Windows takes the loader lock that the recorded deadlock holds, so it must not be created during a hang.
- Each `gpu_test` arms it with the test's name and a deadline **after acquiring `GPU_TEST_LOCK`** (a test queued behind a slow one is waiting, not stuck), and disarms it after the body thread has been joined.
- On expiry: write `HANG: <test> still running after <n>s` straight to the stderr handle (not `eprintln!`, which libtest may capture), then `std::process::abort()`. Abort ends the process without running DLL detach; a normal exit would need the loader lock and could hang itself. On a desktop, Windows Error Reporting may show a dialog or write a crash dump on abort; disable that for the process (for example with `SetErrorMode`) if a spike shows it blocks.
- A per-test deadline, overridable by an environment variable (for example `STUNT_GPU_TEST_DEADLINE_S`). It is not the script's bound: the script's 60 s (`DEFAULT_TIMEOUT_S`) covers a whole run of the binary, which ADR 0016 measured at 3.2-3.6 s. Set the default from the slowest single GPU test, **measured on CI's lavapipe job**, with a generous margin. A per-test deadline cannot see a slowdown spread thinly across many tests; the gate's step timeout still bounds the whole run.
- Delete `watch_render_test.py`, its test and the `test-render` task.
- **Docs and comments that name the watchdog:**
  - Rewrite [`docs/howto/run-the-gpu-tests.md`](../../../docs/howto/run-the-gpu-tests.md) around the deadline, with a documented loop that runs `cargo test -p stunt-render --test gpu` N times to measure a hang rate. If it becomes a mise task, it must run under both PowerShell and bash.
  - `docs/development.md`'s index line ("under the hang watchdog").
  - `docs/quality-gate.md` § GPU tests, which says the `gpu` binary is kept apart from `it` "so the watchdog can run it alone". Keep the separate binary (a hang-rate loop still runs it alone), and restate the reason.
  - The module comment in `crates/stunt-render/tests/gpu/main.rs`, which names `mise run test-render`.
  - An amendment note on ADR 0016, which cites `test-render`.
- Remove what only the watcher used from `process_tree.py`: the `on_timeout` callback (used only by `watch_render_test.py` and its test in `tests/test_process_tree.py`).
- **Accepted losses:** the script's last-20-lines and child-process-count report; the test name replaces it. A hang after the last test, at process exit, is outside any `gpu_test`; the gate's step timeout still bounds it. Tests that open a renderer outside `gpu_test` (for example under `crates/stunt-cli`) are unbounded today and stay so.
- **Test:** a GPU-free test of the watchdog itself (a deliberately stuck body under a short deadline, run in a child process, asserting the `HANG` line and an abnormal exit). Where it lives is the builder's call; it must not take `GPU_TEST_LOCK` from the real GPU tests' process.

## Left to the builder

- Flag and environment-variable names, and the file layout of the watchdog code.
- Whether section 2's ADR changes are amendment notes or one new ADR.
- The order of the PRs, and whether they stack (they need not).
