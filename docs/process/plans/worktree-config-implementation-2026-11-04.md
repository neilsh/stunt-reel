# Worktree configuration, not links — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new worktree from any tool works on its first `mise run`, holds no junctions, and seeds
`target/` by itself before the first Cargo build.

**Architecture:** Code finds the corpus and captures through `dataroot.data_root()` instead of
checkout junctions; `mise.toml` names the shared uv and cargo caches by absolute path; each
worktree keeps uv's default `.venv`; a hidden, locked `ensure` task, a `depends` of every
building task, seeds `target/` and sets `core.hooksPath`. Old linked worktrees keep working and
`reap` keeps unlinking them.

**Tech Stack:** Python 3 stdlib (`dataroot.py`, `worktree_init.py`, `target_seed.py`), mise tasks
and Tera templates, pytest, one Rust integration test.

**Spec:** [`worktree-config-2026-11-04.md`](worktree-config-2026-11-04.md). Read it first; this plan
argues from its sections 3 and 4.

## Global Constraints

- `mise run check` passes at the end of every task and every stack layer (AGENTS.md Directive 2).
- Tests stay corpus-free: a test touching a data-root path sets `STUNT_DATA_ROOT` to `tmp_path`
  (Directive 1, `[I7]`).
- Nothing deletes recursively through a junction: legacy links are removed only by `remove_link`
  (ADR 0018). New code never calls `create_link`.
- `ensure` imports only the stdlib and `stunt_reel` modules that do, because it runs before any
  environment exists (`PYTHONPATH={{config_root}}/python`, plain `python`, like `init`).
- `reap`'s unlink-and-prove step, `LINK_TARGETS`, `env_target` and the orphan sweep stay; only
  their callers in `init` and the scripts go (spec section 3, "Existing worktrees").
  `ensure_links` and `shared_target` went in the review fix pass: no caller was left.
- Stage paths by name, Conventional Commit subjects, body that answers why (SOP 3).
- Delivery is one `gh stack` (gh-stack skill): layer 1 = Tasks 1–4, layer 2 = Tasks 5–7,
  layer 3 = Tasks 8–9.

## Review Focus

1. A user passes `--film corpus/stisldem/VAULT/CTRY.FLM`, the form every task description and
   research note uses, in a worktree with no `corpus/` link: it must read the data root's film
   (Task 2 test `test_a_relative_corpus_argument_reads_the_data_root`).
2. The gate starts `lint-rust`, `test-rust`, `doc` and `check-rust-matrix` concurrently in a fresh
   worktree: `target/` is seeded once, never twice into one staging directory (Task 6 test
   `test_concurrent_ensures_seed_once`).
3. A clone whose `<primary>.data` does not exist keeps its corpus in the checkout: reads must land
   there, not in a missing directory (Task 1 test `test_a_missing_data_root_falls_back_to_the_primary`).
4. `STUNT_DATA_ROOT` set to another directory must move captures as well as the corpus
   (Task 1 test `test_the_override_moves_captures_too`).
5. `init` run in an old linked worktree must report its links and leave them in place, and `reap`
   must still unlink them (Task 7 tests `test_init_reports_legacy_links_and_keeps_them`,
   existing `tests/test_worktree_reap.py`).

---

## Layer 1: data-root paths in code

### Task 1: ADR 0032 and the data-root resolvers

**Files:**
- Create: `docs/adr/0032-worktrees-reach-shared-state-by-configuration.md`
- Modify: `python/stunt_reel/dataroot.py:144-153` (`data_root`), add two functions after it
- Modify: `python/stunt_reel/parity_layout.py:56,101-103` (`capture_root`)
- Modify: `.gitignore` (add `/captures/` beside `capture/`)
- Test: `tests/test_dataroot.py`, `tests/test_parity_layout.py`

**Interfaces:**
- Produces:
  - `data_root() -> Path`. Order: `STUNT_DATA_ROOT`; else `<primary>.data` **if it is a
    directory**; else the primary checkout; outside git, `REPO_ROOT`. Still `lru_cache`d.
  - `corpus_root() -> Path`: `data_root() / "corpus"`.
  - `resolve_data_path(path: Path) -> Path`: a relative path whose first part is `corpus` or
    `captures` becomes `data_root() / path`; any other path is returned unchanged.
  - `data_path_arg(text: str) -> Path`: `resolve_data_path(Path(text))`, for argparse `type=`.
    argparse applies `type` to string defaults too, so `default="corpus/..."` resolves alike.
  - `parity_layout.capture_root() -> Path`: `dataroot.data_root() / "captures"`, absolute. Import
    `dataroot` inside the function: `dataroot` imports `parity_layout` at module level.

- [ ] **Step 1: Write ADR 0032.** One page, the repo's ADR shape (Status, Context, Decision,
  Considered Options, Consequences). Status `accepted 2026-11-04`. Content is spec sections 2 and
  3; Considered Options are `.worktreeinclude`, a `WorktreeCreate` hook, a `SessionStart` hook,
  automating `init` while keeping the links, and per-worktree `UV_PROJECT_ENVIRONMENT`.
  Consequences name ADRs 0008, 0013, 0018, 0019 and 0030 and say Task 8 marks them.
- [ ] **Step 2: Write the failing tests** in `tests/test_dataroot.py`, each clearing
  `dataroot.data_root.cache_clear()` first:

```python
def test_a_missing_data_root_falls_back_to_the_primary(tmp_path, monkeypatch):
    # primary at tmp_path/"repo" with a .git dir, no tmp_path/"repo.data"
    assert dataroot.data_root() == tmp_path / "repo"


def test_corpus_root_is_under_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STUNT_DATA_ROOT", str(tmp_path))
    assert dataroot.corpus_root() == tmp_path.resolve() / "corpus"


def test_a_relative_corpus_path_resolves_against_the_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("STUNT_DATA_ROOT", str(tmp_path))
    film = Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert dataroot.resolve_data_path(film) == tmp_path.resolve() / film
    assert dataroot.resolve_data_path(Path("captures/x")) == tmp_path.resolve() / "captures/x"


def test_other_paths_resolve_to_themselves(tmp_path, monkeypatch):
    monkeypatch.setenv("STUNT_DATA_ROOT", str(tmp_path))
    for path in (Path("build/re/playone.img"), tmp_path / "corpus" / "x", Path("corpusx/a")):
        assert dataroot.resolve_data_path(path) == path


def test_the_override_moves_captures_too(tmp_path, monkeypatch):
    monkeypatch.setenv("STUNT_DATA_ROOT", str(tmp_path))
    assert parity_layout.capture_root() == tmp_path.resolve() / "captures"
```

  Build the primary in the first test the way `test_primary_checkout_owns_the_git_directory`
  (`tests/test_dataroot.py:49`) does, with `STUNT_DATA_ROOT` deleted.
- [ ] **Step 3: Run them.** `mise run test-py -- tests/test_dataroot.py` → the five new tests FAIL
  (`AttributeError` for the two new functions, wrong paths for the others).
- [ ] **Step 4: Implement** the four functions above. `capture_root()` callers that join it to
  `REPO_ROOT` (`capture_playone_reference.py:163`, `capture_video.py:132`,
  `worktree_init.py:439`) drop the join; `migrate_captures.py:66` uses `.name` and is unchanged;
  `LINK_TARGETS`' captures row keeps the literal `"build/parity/captures"` (the old checkout path,
  needed only to recognise old links). Fix any `tests/test_parity_layout.py` assertion that expects
  the relative path.
- [ ] **Step 5: Run** `mise run test-py -- tests/test_dataroot.py tests/test_parity_layout.py` → PASS.
- [ ] **Step 6: Commit** `feat(dataroot): resolve the corpus and captures from the data root` with
  the ADR, `.gitignore`, both modules and both test files.

### Task 2: Scripts read through the resolvers

**Files:**
- Modify (literal → resolver, drop `ensure_links_or_report`): `python/scripts/`
  `adversarial_formats_challenge.py`, `batch_parity.py`, `capture_digest.py`,
  `capture_playone_reference.py`, `capture_video.py`, `flm_events.py`, `game_builds.py`,
  `make_all.py`, `parity_bench.py`, `parity_frame.py`, `parity_run.py`, `parity_sweep.py`,
  `play.py`, `probe_playone_light.py`, `unlzexe.py`, `verify_schemas_corpus.py`
- Modify: `python/stunt_reel/parity_pipeline.py:82,120`, `python/stunt_reel/tac/staging.py:124`
- Modify: `python/stunt_reel/dataroot.py` (delete `ensure_links_or_report` and its `__all__` entry)
- Test: `tests/test_worktree_layout.py`, `tests/test_dataroot.py`, `tests/test_capture_digest.py`,
  one new test file `tests/test_data_arguments.py`

**Interfaces:**
- Consumes: `corpus_root()`, `resolve_data_path()`, `capture_root()` (Task 1).
- Produces: every `--film`, `--game-root`, `--corpus` and positional corpus argument is declared
  `type=data_path_arg` with a string default (`default="corpus/stisldem/VAULT/CTRY.FLM"`), so
  `--help` still shows the familiar form and the parsed value is resolved. Module-level
  `DEFAULT_FILM: Path` constants become strings or go.

- [ ] **Step 1: Write the failing tests.** In `tests/test_worktree_layout.py` replace
  `test_every_script_that_reads_the_corpus_links_it` (line 125) with:

```python
def test_no_module_reads_a_data_path_relative_to_the_working_directory():
    # every python/ file except dataroot.py: no Path("corpus..."), "corpus/...", REPO_ROOT / "corpus",
    # root / "corpus" outside a resolve_data_path(...) or corpus_root() call
    assert offenders == []


def test_nothing_calls_the_retired_link_repair():
    assert not any("ensure_links_or_report" in p.read_text(encoding="utf-8") for p in PYTHON_FILES)
```

  In `tests/test_data_arguments.py`, for `capture_playone_reference`, `play` and `flm_events`
  (the three whose parsers take `--film` or a positional film):

```python
@pytest.mark.parametrize("script", ["capture_playone_reference", "play", "flm_events"])
def test_a_relative_corpus_argument_reads_the_data_root(script, tmp_path, monkeypatch):
    monkeypatch.setenv("STUNT_DATA_ROOT", str(tmp_path))
    dataroot.data_root.cache_clear()
    args = load(script)._parser().parse_args([*FILM_FLAG[script], "corpus/stisldem/VAULT/CTRY.FLM"])
    assert args.film == tmp_path.resolve() / "corpus/stisldem/VAULT/CTRY.FLM"


def test_the_default_film_reads_the_data_root(
    tmp_path, monkeypatch
):  # capture_playone_reference, no --film
    assert args.film == tmp_path.resolve() / "corpus/stisldem/VAULT/CTRY.FLM"
```

  `FILM_FLAG` maps each script to `["--film"]` or `[]` (positional); `load` imports a script the
  way existing script tests do. Where a script builds its parser inline in `main`, extract
  `_parser() -> argparse.ArgumentParser` first (no behaviour change).
- [ ] **Step 2: Run** `mise run test-py -- tests/test_worktree_layout.py tests/test_data_arguments.py`
  → FAIL, listing the files above as offenders.
- [ ] **Step 3: Implement.** Each literal goes through `resolve_data_path` or `corpus_root()`;
  `batch_parity.py:409` and `parity_pipeline.py:120` (`root / "corpus"`, where `root` is
  `--data-root`) keep using their `root` argument when given and `corpus_root()` otherwise;
  `unlzexe.py:161` and `verify_schemas_corpus.py:505` test "reads the corpus" by
  `path.is_relative_to(corpus_root())` after resolving. `adversarial_formats_challenge.py`'s
  `glob.glob("corpus/...")` and `sys.path.insert` use `str(corpus_root() / ...)`. Delete every
  `ensure_links_or_report` import and call, and the function. Remove its two tests in
  `tests/test_dataroot.py` (lines 181-208) and the monkeypatch in `tests/test_capture_digest.py:97`.
- [ ] **Step 4: Run** `mise run lint-py`, `mise run typecheck`, then
  `mise run test-py -- tests/test_worktree_layout.py tests/test_data_arguments.py tests/test_dataroot.py tests/test_capture_digest.py`
  → PASS.
- [ ] **Step 5: Commit** `refactor(scripts): read the corpus through the data root, not a link`.

### Task 3: Rust readers find the data root

**Files:**
- Modify: `mise.toml` `[vars]` (add `data_root`), `[tasks.sod-census]` (line 343)
- Modify: `crates/stunt-core/tests/flm_camera_test.rs:27-35` (`corpus_film`)
- Test: `tests/test_worktree_layout.py`

**Interfaces:**
- Produces: `vars.primary` (the primary checkout, from `cargo_home`'s current `git rev-parse
  --path-format=absolute --git-common-dir` expression; `config_root` outside git) and
  `vars.data_root = "{{vars.primary}}.data"`. `vars.data_root` reads neither `STUNT_DATA_ROOT` nor
  the filesystem: Task 1's fallbacks belong to Python, and a Rust reader given a missing directory
  reports it.

- [ ] **Step 1: Write the failing test** in `tests/test_worktree_layout.py`:

```python
def test_sod_census_reads_the_data_roots_corpus():
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert "--corpus {{vars.data_root}}/corpus" in config["tasks"]["sod-census"]["run"]
```

- [ ] **Step 2: Run it** → FAIL.
- [ ] **Step 3: Implement.** Factor the primary-checkout expression out of `cargo_home` into
  `vars.primary` (same `|| echo -` fallback to `config_root`, same `&`-safe form the
  `test_cargo_home_renders_in_a_checkout_whose_path_has_an_ampersand` test holds), then
  `cargo_home = "{{vars.primary}}/.cache/cargo"` and `data_root = "{{vars.primary}}.data"`. Append
  `--corpus {{vars.data_root}}/corpus` to `sod-census`'s `run`. `corpus_film()` reads
  `STUNT_DATA_ROOT` with `std::env::var_os` and falls back to the current `../../corpus` path.
  `test_cargo_home_renders_in_a_checkout_whose_path_has_an_ampersand` (line 233) writes only
  `cargo_home` into its scratch `mise.toml`; make it write `primary` too, and assert both render.
  If mise does not resolve one var from another, inline the expression in each var instead.
- [ ] **Step 4: Run** `mise run test-py -- tests/test_worktree_layout.py` and `mise run check-rust` → PASS
  (the camera test stays `#[ignore]`d).
- [ ] **Step 5: Commit** `fix(cli,core): find the corpus through the data root in Rust readers`.

### Task 4: Layer 1 gate and stack

- [ ] **Step 1: Run** `mise run check` → `PASS 9/9`.
- [ ] **Step 2: Manual read** in a scratch worktree with no links (`git worktree add
  .claude/worktrees/wt-probe-1 HEAD`, no `init`): `mise run flm-events -- corpus/stisldem/VAULT/CTRY.FLM`
  prints events. Remove it with `git worktree remove .claude/worktrees/wt-probe-1` (it holds no links).
- [ ] **Step 3: Create layer 1** with the gh-stack skill from Tasks 1–3's commits.

## Layer 2: tools by configuration, and `ensure`

### Task 5: Absolute shared caches, no temp override

**Files:**
- Modify: `mise.toml:37-63` (`[env]` and `[vars]` and their comments)
- Test: `tests/test_worktree_layout.py`

**Interfaces:**
- Consumes: `vars.primary` (Task 3).
- Produces: `UV_CACHE_DIR = "{{vars.primary}}/.cache/uv"`; no `TMP` or `TEMP` in `[env]`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_the_uv_cache_is_the_primarys_by_absolute_path():
    assert config["env"]["UV_CACHE_DIR"] == "{{vars.primary}}/.cache/uv"


def test_tasks_use_the_os_temp_directory():
    assert "TMP" not in config["env"] and "TEMP" not in config["env"]
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, rewriting the `[env]` comment to cite ADR 0032.
  `[vars]` is defined after `[env]` in the file; check `mise env` renders `UV_CACHE_DIR` absolute
  from this worktree (mise resolves vars before env; if not, move `[vars]` above `[env]`).
- [ ] **Step 4: Run** `mise env | Select-String UV_CACHE_DIR` → `E:/git/stunt-reel/.cache/uv`;
  `mise run test-py -- tests/test_worktree_layout.py` → PASS.
- [ ] **Step 5: Commit** `build(mise): name the shared uv cache by absolute path; drop the temp override`.

### Task 6: The `ensure` task

**Files:**
- Modify: `python/stunt_reel/target_seed.py` (add the lock)
- Modify: `python/scripts/worktree_init.py` (add `ensure` subcommand and `_ensure`)
- Modify: `mise.toml` (add `[tasks.ensure]`; `depends = ["ensure"]` on building tasks)
- Test: `tests/test_target_seed.py`, `tests/test_worktree_seed.py`, `tests/test_worktree_layout.py`

**Interfaces:**
- Produces:
  - `target_seed.exclusive(path: Path)`, a `contextlib.contextmanager` yielding nothing: blocks until
    it holds an OS lock on the file `path` (created if missing): `msvcrt.locking(LK_LOCK)` on
    Windows, `fcntl.flock(LOCK_EX)` elsewhere, retrying `LK_LOCK`'s 10-second timeout until held.
  - `worktree_init._ensure() -> int`: under `exclusive(REPO_ROOT / "target" / ".ensure.lock")`,
    runs `ensure_hooks_path(REPO_ROOT)` and `_seed_target()`; prints their lines only when either
    did something (`+`) or failed (`!`); returns 0 (a seed failure is a slower build, not an error).
  - `[tasks.ensure]`: `hide = true`, `run = "python python/scripts/worktree_init.py ensure"`, `env`
    identical to `[tasks.init]`'s.
  - `depends = ["ensure"]` on every task whose `env` sets `CARGO_HOME` except `fmt-rust`,
    `fmt-check-rust`, `deny` and `check-rust`; plus `init` and `seed` are not given it (they call
    the same code).

- [ ] **Step 1: Write the failing tests.**

```python
# tests/test_worktree_seed.py
def test_concurrent_ensures_seed_once(tmp_path, monkeypatch):
    # point REPO_ROOT at tmp_path checkout; monkeypatch target_seed.seed with a fake that records
    # calls, sleeps 0.2 s, then creates target/debug; run _ensure() in 4 threads
    assert calls == 1


def test_ensure_is_quiet_when_nothing_changes(tmp_path, capsys, monkeypatch):
    # target/debug exists, core.hooksPath already set
    assert worktree_init._ensure() == 0 and capsys.readouterr().out == ""


# tests/test_worktree_layout.py
def test_every_task_that_builds_depends_on_ensure():
    exempt = {"fmt-rust", "fmt-check-rust", "deny", "check-rust", "init", "seed"}
    missing = [
        name
        for name, task in config["tasks"].items()
        if "CARGO_HOME" in task.get("env", {})
        and name not in exempt
        and "ensure" not in task.get("depends", [])
    ]
    assert missing == []
```

  The thread test needs the lock to work between threads of one process: open the lock file
  separately in each `exclusive` call (one handle per holder), which `msvcrt.locking` and `flock`
  both treat as distinct.
- [ ] **Step 2: Run** `mise run test-py -- tests/test_worktree_seed.py tests/test_worktree_layout.py` → FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** the same command → PASS; then `mise run lint-rust` in this worktree prints
  nothing from `ensure` when `target/` is already built.
- [ ] **Step 5: Commit** `feat(worktree): seed target/ before the first cargo build, under a lock`.

### Task 7: `init` stops linking

**Files:**
- Modify: `python/scripts/worktree_init.py:98-141,190-256,439-449` (`_uv_venv`, `_uv_sync`, `_init`,
  the capture-link restore in `clean`)
- Modify: `python/stunt_reel/dataroot.py` (delete `ensure_cache_link`, `_adopt_partial_cache`,
  `ensure_venv_link`, `discard_env` if only `ensure_venv_link` used it)
- Modify: `mise.toml` `[tasks.init]` description
- Test: `tests/test_dataroot.py`, `tests/test_worktree_seed.py`

**Interfaces:**
- Consumes: `_ensure()` (Task 6), `_reparse_points(root: Path)`, the list of link paths under *root* (`worktree_init.py:630`).
- Produces: `_init(migrate: bool) -> int`: `--migrate` unchanged (moves an in-checkout corpus into
  the data root, then **does not** link it); then `_ensure()`; then `uv sync --locked --all-groups`
  into the default `.venv`; then one line per entry of `_reparse_points(REPO_ROOT)`:
  `  ~ <relative path> is a link from the old layout; reap unlinks it`. Never removes one.

- [ ] **Step 1: Write the failing tests** in `tests/test_worktree_seed.py`:

```python
def test_init_reports_legacy_links_and_keeps_them(tmp_path, monkeypatch, capsys):
    # checkout with a junction .cache -> tmp_path/"shared" (dataroot.create_link); uv sync stubbed
    assert worktree_init._init(migrate=False) == 0
    assert dataroot.is_link(checkout / ".cache")
    assert "is a link from the old layout" in capsys.readouterr().out


def test_init_creates_no_links(tmp_path, monkeypatch):
    # fresh checkout, uv sync stubbed
    worktree_init._init(migrate=False)
    assert worktree_init._reparse_points(checkout) == []
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; delete the link-creation tests in
  `tests/test_dataroot.py` (`test_cache_link_*`, `test_env_link_*`, lines 210-279 and 352-421),
  keeping `test_env_target_*`, `test_orphan_envs_*` and the marker tests, which `reap -- --prune`
  still needs.
- [ ] **Step 4: Run** `mise run test-py -- tests/test_dataroot.py tests/test_worktree_seed.py tests/test_worktree_reap.py`
  → PASS (reap's tests unchanged).
- [ ] **Step 5: Commit** `refactor(worktree): init seeds and syncs, and no longer links`.

**Layer 2 close:** `mise run check` → PASS, then create layer 2 with gh-stack.

## Layer 3: documentation and verification

### Task 8: Docs, SOP 6 and ADR status lines

**Files:**
- Modify: `docs/harness-setup.md` (restructure), `docs/harness.md:43-83` (DSH sections),
  `AGENTS.md` SOP 6 items 2 and 5, `docs/development.md` if it says "run `mise run init` once"
- Modify: status lines of `docs/adr/0008-…`, `0013-…`, `0018-…`, `0019-…` (superseded), `0030-…`
- Modify: `docs/process/plans/worktree-config-2026-11-04.md` Status line
- Test: `tests/test_doc_invariants.py` (existing; it checks links and anchors)

- [ ] **Step 1: Rewrite `docs/harness-setup.md`** in this order: what lives where (drop the
  `.cache`/`.venv` junction rows, add the data root and caches by absolute path); one-time setup
  (install, trust, data root); a new worktree (nothing to do; the first building task seeds;
  `mise run init` to do it eagerly); removing a worktree (any tool for a worktree without links,
  `mise run reap` for one with them); then `## Claude Code`, `## DSH` (sessions need
  `danger-full-access` for `mise run` tasks; temp-directory symptom moved here from harness.md),
  `## Orca` (worktrees on `C:` copy the venv). Keep "Verify the machine", replacing the junction
  check with `mise env | Select-String UV_CACHE_DIR`.
- [ ] **Step 2: Edit** `docs/harness.md` "Temporary directories" to say tasks now use the OS temp
  directory and DSH needs `danger-full-access` (link to harness-setup's DSH section); SOP 6:
  item 2 becomes "nothing to provision: the first building task seeds `target/`
  (ADR 0032); `mise run init` does it eagerly", item 5 keeps `reap` for linked worktrees and
  allows any tool's removal otherwise.
- [ ] **Step 3: Add the ADR status lines**, dated 2026-11-04, in the form ADR 0008 line 5 uses:
  0019 "superseded by ADR 0032"; 0008 "amended by ADR 0032: code reads the data root directly; no
  link"; 0013 "amended by ADR 0032: no `.cache` link; the cache is named by absolute path"; 0018
  "amended by ADR 0032: new worktrees hold no links; this applies to old ones until reaped"; 0030
  "amended by ADR 0032: seeding runs from `ensure`, a dependency of every building task".
- [ ] **Step 4: Run** `mise run test-py -- tests/test_doc_invariants.py` → PASS.
- [ ] **Step 5: Commit** `docs: worktrees need no provisioning step (ADR 0032)`.

### Task 9: End-to-end verification (spec section 6)

- [ ] **Step 1:** From a session in the primary checkout, create a worktree with Claude Code's
  `EnterWorktree` tool. In it, with no `init`: `mise run lint-py` passes; `.venv` is a real
  directory; `_reparse_points` lists nothing; `mise run lint-rust` leaves `target/debug` seeded
  (its `ensure` line says `seeded from …`).
- [ ] **Step 2:** `mise run frame` on an existing CTRY capture reads the corpus and the capture.
- [ ] **Step 3:** Record the data root's and `<primary>/.cache`'s file count and size
  (`Get-ChildItem -Recurse -File | Measure-Object Length -Sum`), leave with `ExitWorktree` choosing
  remove, record again: identical.
- [ ] **Step 4:** In an old linked worktree with no work in it, `mise run reap -- --yes` from the
  primary still reports the unlink and removes it.
- [ ] **Step 5:** Add a dated row with the four results to the spec's section 6 and set its Status
  to implemented; `mise run check` → PASS; commit `docs(plans): record the worktree verification`;
  create layer 3 with gh-stack.
