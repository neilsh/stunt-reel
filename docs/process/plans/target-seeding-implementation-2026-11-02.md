# Target Seeding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `mise run init` gives a new worktree on the Dev Drive a `target/` cloned from a donor
checkout that Cargo already considers built, at little physical disk.

**Architecture:** Every cargo task names the shared cache by one absolute `CARGO_HOME`, derived in
`mise.toml` from git's common directory, so a donor's fingerprints stay valid in any checkout. A
new pure-Python module, `stunt_reel.target_seed`, picks a donor and copies its `target/debug`,
`target/check` and `target/matrix` with `robocopy`, which block-clones on ReFS. `worktree_init.py`
calls it from `init` and from a new `seed` command.

**Tech Stack:** Python 3.12 standard library (`ctypes`, `msvcrt` on Windows), `robocopy`, mise
`[vars]` with `exec` and `dirname` (checked on mise 2026.10.12), pytest.

**Spec:** [`target-seeding-2026-11-02.md`](target-seeding-2026-11-02.md);
decision in [ADR 0030](../../adr/0030-new-worktrees-seed-target-by-block-clone.md).

## Global Constraints

- Seed only into a `target/` that holds none of `debug/`, `check/`, `matrix/`; never overwrite.
- Seed only where the checkout's volume is ReFS; skip elsewhere (Linux and macOS are later work).
- Seeded directories, in order: `debug`, `check`, `matrix`; seeded files: `.rustc_info.json`,
  `CACHEDIR.TAG`. Never `release`, `build-at`, `doc`.
- `robocopy <src> <dst> /E /COPY:DAT /DCOPY:DAT /R:0 /W:0 /NFL /NDL /NJH /NJS`; exit codes 0–7
  are success, 8 and above are failure. Timestamps must survive.
- Seeding is best effort: any failure prints `! seed: <reason>`, removes what it copied, and `init`
  continues with exit code unchanged.
- `CARGO_HOME` stays per task (ADR 0013: mise installs its rustup shim into `$CARGO_HOME`); every
  task that sets it uses `{{vars.cargo_home}}`, and `build-at` sets it too.
- The Python package stays dependency-free; `mise run check` stays corpus-free and offline.
- Measurement gate (spec section 5): seeded worktree's cold `mise run check` under 30 s with 0
  crates compiled; its physical disk under 0.5 GB; seeding adds under 15 s to init.

## Review Focus

1. A `target/` that exists but holds only `tmp/`, `check.log` or `doc/` (what a Python-only gate or
   a failed run leaves) must still be seeded. Test in Task 2.
2. A donor whose build is running (its `.cargo-lock`, `.cargo-build-lock` or
   `.cargo-artifact-lock` held) must be skipped, never half-copied. Test in Task 3.
3. A donor `target/` with no `.rustc_info.json` or no registry `.d` file (only `cargo doc` ran, or
   a build failed early) must be disqualified without an exception. Test in Task 2.
4. `git worktree list` names this checkout and prunable entries whose path is gone; both must be
   ignored as donors. Test in Task 2.
5. `CARGO_HOME` spelled with `/` in mise and `\` in Cargo's `.d` files, in either case, must
   compare equal. Test in Task 2.

---

### Task 1: One absolute `CARGO_HOME` for every cargo task

**Files:**
- Modify: `mise.toml` (add `[vars]` after `[env]`; every `CARGO_HOME = "{{config_root}}/.cache/cargo"`
  at lines 109, 114, 127, 159, 172, 185, 215, 220, 225, 238, 243, 252, 264, 311; `[tasks.build-at]`
  at line 78 gains `env`; the `[env]` comment at lines 39–45 names ADR 0030)
- Test: `tests/test_worktree_layout.py`

**Interfaces:**
- Produces: mise variable `vars.cargo_home`, resolving to `<primary>/.cache/cargo` with `/`
  separators (observed: `E:/git/stunt-reel/.cache/cargo`).

- [ ] **Step 1: Write the failing tests** in `tests/test_worktree_layout.py`:

```python
def test_cargo_home_is_one_absolute_path() -> None:
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert "--git-common-dir" in config["vars"]["cargo_home"]
    homes = {
        name: task["env"]["CARGO_HOME"]
        for name, task in config["tasks"].items()
        if "CARGO_HOME" in task.get("env", {})
    }
    assert homes, "no task sets CARGO_HOME"
    assert {home for home in homes.values()} == {"{{vars.cargo_home}}"}, homes


def test_build_at_sets_cargo_home() -> None:
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert config["tasks"]["build-at"]["env"]["CARGO_HOME"] == "{{vars.cargo_home}}"
```

- [ ] **Step 2: Run them to see them fail**

Run: `mise exec -- uv run pytest tests/test_worktree_layout.py -k cargo_home -q`
Expected: 2 failed (`KeyError: 'vars'`, `KeyError: 'env'`).

- [ ] **Step 3: Add the variable and point every task at it**

```toml
[vars]
# One absolute path in every checkout: Cargo fingerprints a dependency by its CARGO_HOME path,
# so a target/ cloned from another checkout is fresh only if both name the cache alike (ADR 0030).
cargo_home = "{{ exec(command='git rev-parse --path-format=absolute --git-common-dir') | dirname }}/.cache/cargo"
```

`exec` runs where mise was invoked, which is always inside a checkout of this repository, so
git finds the same common directory from any of them (checked on mise 2026.10.12 with this
exact template). Replace each `CARGO_HOME = "{{config_root}}/.cache/cargo"` with
`CARGO_HOME = "{{vars.cargo_home}}"`; add `env = { CARGO_HOME = "{{vars.cargo_home}}" }` to
`build-at`.

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_worktree_layout.py -q`
Expected: all pass.

- [ ] **Step 5: Run the Rust lane once and confirm the new path reached Cargo**

Run: `mise run check-rust`
Expected: PASS; every dependency recompiles once.
Run: `head -c 300 target/debug/deps/serde_core-*.d`
Expected: source paths start with `E:\git\stunt-reel\.cache\cargo\registry` (the primary's cache,
not this worktree's `.cache` junction).

- [ ] **Step 6: Commit**

```bash
git add mise.toml tests/test_worktree_layout.py
git commit -m "build(mise): name the shared cargo cache by one absolute path"
```

---

### Task 2: Donor qualification and ranking

**Files:**
- Create: `python/stunt_reel/target_seed.py`
- Test: `tests/test_target_seed.py`

**Interfaces:**
- Produces, in `stunt_reel.target_seed`:
  - `SEEDED_DIRS: tuple[str, ...] = ("debug", "check", "matrix")`
  - `SEEDED_FILES: tuple[str, ...] = (".rustc_info.json", "CACHEDIR.TAG")`
  - `needs_seed(target: Path) -> bool`: true when none of `SEEDED_DIRS` exists under `target`.
  - `built_by(target: Path, rustc_vv: str) -> bool`: true when `rustc_vv.strip()` equals the
    stripped `stdout` of some entry in `target/.rustc_info.json`'s `outputs`; false when the file
    is missing or unreadable.
  - `uses_cargo_home(target: Path, cargo_home: Path) -> bool`: reads `*.d` files in
    `target/debug/deps` until one names a path containing `\registry\src\` or `/registry/src/`,
    and compares the part before it with `cargo_home`, both normalized by `_norm`; false when no
    such file exists.
  - `_norm(path: str | Path) -> str`: `str(path).replace("/", "\\").rstrip("\\").casefold()`.
  - `rank_donors(checkouts: Sequence[Path], *, here: Path, rustc_vv: str, cargo_home: Path) ->
    list[Path]`: drops `here`, missing paths, and any whose `target/` fails `built_by` or
    `uses_cargo_home` or holds no `debug/.fingerprint`; orders the rest with an identical
    `Cargo.lock` (bytes equal to `here`'s) first, then by `target/debug/.fingerprint` mtime,
    newest first. Returns the checkout paths.

- [ ] **Step 1: Write the failing tests**, building synthetic trees in `tmp_path` with a helper
  `_donor(root: Path, *, rustc: str = RUSTC, home: str = HOME, lock: str = "a", age: float = 0)`
  that writes `Cargo.lock`, `target/.rustc_info.json`
  (`{"outputs": {"1": {"stdout": rustc}}}`), `target/debug/.fingerprint/`, and
  `target/debug/deps/serde_core-0123456789abcdef.d` whose first line names
  `{home}\registry\src\index\serde_core\src\lib.rs`, then sets the fingerprint mtime to
  `time.time() - age`. Tests:

```python
RUSTC = "rustc 1.99.1 (58cf8f9c3 2026-10-13)\nhost: x86_64-pc-windows-msvc\n"
HOME = r"E:\git\stunt-reel\.cache\cargo"

def test_needs_seed_ignores_tmp_log_and_doc(tmp_path):            # Review Focus 1
    for name in ("tmp", "doc"): (tmp_path / "target" / name).mkdir(parents=True)
    (tmp_path / "target" / "check.log").write_text("x")
    assert needs_seed(tmp_path / "target")
    (tmp_path / "target" / "matrix").mkdir()
    assert not needs_seed(tmp_path / "target")

def test_needs_seed_when_target_absent(tmp_path):
    assert needs_seed(tmp_path / "target")

def test_built_by_matches_rustc_and_tolerates_missing_info(tmp_path):   # Review Focus 3
    a = _donor(tmp_path / "a")
    assert built_by(a / "target", RUSTC)
    assert not built_by(a / "target", RUSTC.replace("1.99.1", "1.99.0"))
    (a / "target" / ".rustc_info.json").unlink()
    assert not built_by(a / "target", RUSTC)

def test_uses_cargo_home_normalizes_separators_and_case(tmp_path):     # Review Focus 5
    a = _donor(tmp_path / "a")
    assert uses_cargo_home(a / "target", Path("e:/GIT/stunt-reel/.cache/cargo/"))
    assert not uses_cargo_home(a / "target", Path(r"E:\packages\cargo"))

def test_uses_cargo_home_false_without_registry_dep_info(tmp_path):    # Review Focus 3
    a = _donor(tmp_path / "a")
    for d in (a / "target/debug/deps").glob("*.d"): d.unlink()
    assert not uses_cargo_home(a / "target", Path(HOME))

def test_rank_prefers_matching_lock_then_newest(tmp_path):
    here = tmp_path / "here"; here.mkdir(); (here / "Cargo.lock").write_text("a")
    old_same = _donor(tmp_path / "old", lock="a", age=600)
    new_same = _donor(tmp_path / "new", lock="a", age=10)
    newest_other = _donor(tmp_path / "other", lock="b", age=1)
    assert rank_donors([old_same, newest_other, new_same], here=here, rustc_vv=RUSTC,
                       cargo_home=Path(HOME)) == [new_same, old_same, newest_other]

def test_rank_drops_self_missing_and_disqualified(tmp_path):           # Review Focus 4
    here = _donor(tmp_path / "here")
    wrong_rustc = _donor(tmp_path / "r", rustc="rustc 1.98.0\n")
    wrong_home = _donor(tmp_path / "h", home=r"E:\packages\cargo")
    good = _donor(tmp_path / "g")
    assert rank_donors([here, tmp_path / "gone", wrong_rustc, wrong_home, good], here=here,
                       rustc_vv=RUSTC, cargo_home=Path(HOME)) == [good]
```

- [ ] **Step 2: Run them to see them fail**

Run: `mise exec -- uv run pytest tests/test_target_seed.py -q`
Expected: collection error, `ModuleNotFoundError: stunt_reel.target_seed`.

- [ ] **Step 3: Implement the five functions** in `python/stunt_reel/target_seed.py`, with a
  module docstring that cites ADR 0030 and the plan. `uses_cargo_home` reads at most the first
  4 KiB of each `.d` file and splits on whitespace.

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_target_seed.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add python/stunt_reel/target_seed.py tests/test_target_seed.py
git commit -m "feat(seed): pick a donor target/ built by this rustc and cache"
```

---

### Task 3: Copying from a donor, safely

**Files:**
- Modify: `python/stunt_reel/target_seed.py`
- Test: `tests/test_target_seed.py`

**Interfaces:**
- Consumes: Task 2's `needs_seed`, `rank_donors`, `SEEDED_DIRS`, `SEEDED_FILES`.
- Produces:
  - `@dataclass(frozen=True) class SeedOutcome: status: Literal["seeded", "skipped", "failed"];
    detail: str`
  - `clones_on(path: Path) -> bool`: Windows only, `GetVolumeInformationW` on the path's drive
    root, true when the filesystem name is `"ReFS"`; false on any other platform or error.
  - `build_locks_free(target: Path) -> contextlib.AbstractContextManager[bool]`: opens each of
    `.cargo-lock`, `.cargo-build-lock`, `.cargo-artifact-lock` that exists under each seeded
    profile, takes a non-blocking exclusive `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)` on byte 0,
    yields true if every lock was taken (false at the first refusal), and releases all on exit.
    Elsewhere than Windows it yields true.
  - `robocopy(source: Path, destination: Path) -> None`: runs the Global Constraints command;
    raises `OSError` with the exit code when it is 8 or more.
  - `seed(checkout: Path, *, checkouts: Sequence[Path], rustc_vv: str, cargo_home: Path,
    copy: Callable[[Path, Path], None] = robocopy, volume_clones: Callable[[Path], bool] =
    clones_on) -> SeedOutcome`

`seed` order: `needs_seed(checkout / "target")` else skipped `"target/ already built"`;
`volume_clones(checkout)` else skipped `"volume does not clone blocks"`; drop checkouts on
another drive (`os.path.splitdrive`, compared with `casefold`), since a clone cannot cross
volumes; first of `rank_donors(...)` else skipped `"no donor with this rustc and cargo home"`; inside
`build_locks_free(donor / "target")` (false: skipped `"donor <path> is building"`) copy each
existing `SEEDED_DIRS` entry, then each existing `SEEDED_FILES` entry with `shutil.copy2`;
return seeded `"from <donor>"`. On any exception after the first copy began: remove every
destination it created, return failed `"<exception>"`.

- [ ] **Step 1: Write the failing tests** (reuse Task 2's `_donor`; a fake copier records calls
  and creates the destination directory):

```python
def test_seed_copies_dirs_then_files_from_best_donor(tmp_path):
    here = tmp_path / "here"; here.mkdir(); (here / "Cargo.lock").write_text("a")
    donor = _donor(tmp_path / "d")
    for name in ("check", "matrix"): (donor / "target" / name).mkdir()
    (donor / "target" / "CACHEDIR.TAG").write_text("tag")
    calls = []
    def fake_copy(src, dst): calls.append((src.name, dst)); dst.mkdir(parents=True)
    out = seed(here, checkouts=[donor], rustc_vv=RUSTC, cargo_home=Path(HOME),
               copy=fake_copy, volume_clones=lambda _: True)
    assert out == SeedOutcome("seeded", f"from {donor}")
    assert [name for name, _ in calls] == ["debug", "check", "matrix"]
    assert (here / "target" / ".rustc_info.json").is_file()
    assert (here / "target" / "CACHEDIR.TAG").read_text() == "tag"

def test_seed_skips_built_target_and_non_cloning_volume(tmp_path):
    here = _donor(tmp_path / "here")
    assert seed(here, checkouts=[], rustc_vv=RUSTC, cargo_home=Path(HOME),
                copy=_never, volume_clones=lambda _: True).status == "skipped"
    fresh = tmp_path / "fresh"; fresh.mkdir()
    out = seed(fresh, checkouts=[here], rustc_vv=RUSTC, cargo_home=Path(HOME),
               copy=_never, volume_clones=lambda _: False)
    assert out == SeedOutcome("skipped", "volume does not clone blocks")

def test_seed_failure_removes_partial_copy(tmp_path):                   # spec: best effort
    here = tmp_path / "here"; here.mkdir(); (here / "Cargo.lock").write_text("a")
    donor = _donor(tmp_path / "d"); (donor / "target" / "check").mkdir()
    def flaky(src, dst):
        dst.mkdir(parents=True)
        if src.name == "check": raise OSError("robocopy exit 8")
    out = seed(here, checkouts=[donor], rustc_vv=RUSTC, cargo_home=Path(HOME),
               copy=flaky, volume_clones=lambda _: True)
    assert out.status == "failed" and "exit 8" in out.detail
    assert not (here / "target" / "debug").exists()
    assert not (here / "target" / "check").exists()

@pytest.mark.skipif(sys.platform != "win32", reason="Cargo's locks are Windows byte locks here")
def test_seed_skips_a_donor_that_is_building(tmp_path):                 # Review Focus 2
    here = tmp_path / "here"; here.mkdir(); (here / "Cargo.lock").write_text("a")
    donor = _donor(tmp_path / "d")
    lock = donor / "target" / "debug" / ".cargo-lock"; lock.write_bytes(b"")
    with lock.open("r+b") as held:
        msvcrt.locking(held.fileno(), msvcrt.LK_NBLCK, 1)
        out = seed(here, checkouts=[donor], rustc_vv=RUSTC, cargo_home=Path(HOME),
                   copy=_never, volume_clones=lambda _: True)
        msvcrt.locking(held.fileno(), msvcrt.LK_UNLCK, 1)
    assert out == SeedOutcome("skipped", f"donor {donor} is building")
```

`_never` raises `AssertionError("copied")`.

- [ ] **Step 2: Run them to see them fail**

Run: `mise exec -- uv run pytest tests/test_target_seed.py -q`
Expected: 4 new failures (`ImportError: seed`).

- [ ] **Step 3: Implement `SeedOutcome`, `clones_on`, `build_locks_free`, `robocopy`, `seed`**
  as specified in this task's Interfaces block. Cleanup removes only paths `seed` created (track
  them in a list), with `shutil.rmtree` for directories.

- [ ] **Step 4: Run the tests**

Run: `mise exec -- uv run pytest tests/test_target_seed.py -q`
Expected: 11 passed on Windows.

- [ ] **Step 5: Check `clones_on` and `robocopy` for real, once, by hand**

Run: `mise exec -- uv run python -c "from pathlib import Path; from stunt_reel.target_seed import clones_on; print(clones_on(Path('E:/')), clones_on(Path('C:/')))"`
Expected: `True False`.

- [ ] **Step 6: Commit**

```bash
git add python/stunt_reel/target_seed.py tests/test_target_seed.py
git commit -m "feat(seed): clone a donor's target/ under its build locks"
```

---

### Task 4: Seed from `init` and `mise run seed`

**Files:**
- Modify: `python/scripts/worktree_init.py` (`_init` at lines 180–245, `main` at lines 874–931;
  module docstring)
- Modify: `mise.toml` (new `[tasks.seed]` after `[tasks.init]`)
- Test: `tests/test_worktree_reap.py` is the existing script test; add
  `tests/test_worktree_seed.py` beside it, importing the script the same way.

**Interfaces:**
- Consumes: Task 3's `seed`, `SeedOutcome`, imported into `worktree_init.py` by name
  (`from stunt_reel.target_seed import SeedOutcome, seed`) so tests can monkeypatch
  `worktree_init.seed`; `_worktrees(repo: Path) -> list[_Worktree]` in
  `worktree_init.py`; `cache_root()` from `stunt_reel.dataroot`.
- Produces: `_seed_target() -> str` in `worktree_init.py`, the one line init prints:
  `"  + target/ seeded from <donor>"`, `"  - target/ not seeded: <detail>"` or
  `"  ! seed: <detail>"`. Never raises.

`_seed_target` gathers `rustc -vV` (via `shutil.which("rustc")`; missing rustc is skipped
`"rustc not on PATH"`), `checkouts=[w.path for w in _worktrees(REPO_ROOT)]`,
`cargo_home=cache_root() / "cargo"`, and calls `seed(REPO_ROOT, ...)`. `_init` prints it right
after the `.cache` link lines and before `_uv_venv`. `main` gains a `seed` command that prints
`_seed_target()` and returns 0.

```toml
[tasks.seed]
description = "Clone a built target/ from another checkout into this one's empty target/ (ADR 0030)"
run = "python python/scripts/worktree_init.py seed"
env = { PYTHONPATH = "{{config_root}}/python" }
```

- [ ] **Step 1: Write the failing tests** in `tests/test_worktree_seed.py`:

```python
def test_seed_line_formats_each_outcome(monkeypatch):
    for outcome, line in [
        (SeedOutcome("seeded", r"from E:\a"), r"  + target/ seeded from E:\a"),
        (SeedOutcome("skipped", "volume does not clone blocks"),
         "  - target/ not seeded: volume does not clone blocks"),
        (SeedOutcome("failed", "robocopy exit 8"), "  ! seed: robocopy exit 8"),
    ]:
        monkeypatch.setattr(worktree_init, "seed", lambda *a, **k: outcome)
        monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
        monkeypatch.setattr(worktree_init, "_worktrees", lambda repo: [])
        assert worktree_init._seed_target() == line

def test_seed_line_never_raises(monkeypatch):
    def boom(*a, **k): raise RuntimeError("git missing")
    monkeypatch.setattr(worktree_init, "_worktrees", boom)
    monkeypatch.setattr(worktree_init, "_rustc_vv", lambda: "rustc 1.99.1\n")
    assert worktree_init._seed_target() == "  ! seed: git missing"

def test_seed_command_is_wired(monkeypatch, capsys):
    monkeypatch.setattr(worktree_init, "_seed_target", lambda: "  - target/ not seeded: x")
    assert worktree_init.main(["seed"]) == 0
    assert "not seeded: x" in capsys.readouterr().out
```

`_rustc_vv() -> str | None` is the small helper that runs `rustc -vV`; `None` makes
`_seed_target` return `"  - target/ not seeded: rustc not on PATH"`.

- [ ] **Step 2: Run them to see them fail**

Run: `mise exec -- uv run pytest tests/test_worktree_seed.py -q`
Expected: 3 failed (`AttributeError: _seed_target`).

- [ ] **Step 3: Implement `_rustc_vv`, `_seed_target`, the `_init` call, the `seed` command and
  the mise task**; add one sentence to the module docstring saying init seeds `target/` (ADR 0030).

- [ ] **Step 4: Run the Python lane**

Run: `mise run check-py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/scripts/worktree_init.py mise.toml tests/test_worktree_seed.py
git commit -m "feat(init): seed an empty target/ from a donor checkout"
```

---

### Task 5: Measurement gate, then accept

**Files:**
- Modify: `docs/process/plans/target-seeding-2026-11-02.md` (status line; section 5 results)
- Modify: `docs/adr/0030-new-worktrees-seed-target-by-block-clone.md` (status)
- Modify: `docs/adr/0013-worktrees-share-one-writable-tool-cache.md`,
  `docs/adr/0017-the-gate-keeps-no-compiler-cache.md` (status lines point at ADR 0030)
- Modify: `docs/harness-setup.md`, `docs/development.md` (one sentence each: init seeds `target/`
  on the Dev Drive; `mise run seed` for a checkout made by another tool)

- [ ] **Step 1: Make a donor.** In this worktree (now carrying Tasks 1–4) run `mise run check`.
  Expected: PASS.
- [ ] **Step 2: Make the seeded worktree.**
  `git worktree add --detach E:/git/stunt-reel.wt/seed-b HEAD`, then in it `mise run init`.
  Expected: init prints `+ target/ seeded from <this worktree>`; record init's wall time against
  an unseeded init (time both).
- [ ] **Step 3: Gate the seeded worktree.** In `seed-b`: `mise run check`, then
  `grep -cE '^\s+(Compiling|Checking)' target/check.log`.
  Expected: PASS under 30 s; 0 crates compiled (workspace crates only, if any, named in the note).
- [ ] **Step 4: Measure disk.** Run the shared-cluster count from ADR 0030 (logical size less
  clusters with a reference count above 1, via `fsutil file queryExtentsAndRefCounts`) on
  `seed-b/target`. Expected: under 0.5 GB of its own.
- [ ] **Step 5: Lockfile drift.** In `seed-b`, check out a commit whose `Cargo.lock` differs from
  the donor's, `mise run clean -- --yes`, `mise run seed`, `mise run check-rust`.
  Expected: only the changed packages and their dependents compile.
- [ ] **Step 6: Donor still warm.** Back in this worktree: `mise run check-rust`.
  Expected: 0 crates compiled.
- [ ] **Step 7: Remove `seed-b`** with the junction procedure (`mise run reap` skips detached
  worktrees outside the pool): unlink each reparse point outside `target/` with `rmdir`, confirm
  none remain, `git worktree remove --force`, delete its `.cache/venvs/seed-b-*`.
- [ ] **Step 8: Record and accept.** Write the five measurements into spec section 5 with the
  date; if every row passes, set ADR 0030 to `accepted`, point ADR 0013's and 0017's status lines
  at it, and add the two doc sentences. If a row fails, stop and record why instead.
- [ ] **Step 9: Gate and commit**

Run: `mise run check`
Expected: PASS.

```bash
git add docs/process/plans/target-seeding-2026-11-02.md docs/adr/0030-new-worktrees-seed-target-by-block-clone.md docs/adr/0013-worktrees-share-one-writable-tool-cache.md docs/adr/0017-the-gate-keeps-no-compiler-cache.md docs/harness-setup.md docs/development.md
git commit -m "docs(adr): accept seeding new worktrees' target/ by block clone"
```
