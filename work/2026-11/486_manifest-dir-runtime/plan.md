# Read `CARGO_MANIFEST_DIR` at run time; seed keeps unchanged workspace units — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new worktree seeded from a donor keeps the donor's builds of the workspace crates whose sources are unchanged, so its first `mise run check-rust` drops from about 23 s toward the 13 s warm time (one measurement each, 2026-11-14, Cargo 1.100.0; a prototype of Task 5R took 14–18 s over three runs).

**Architecture:** Two changes, one branch, three code commits (Task 5R corrects Task 5 for Cargo 1.100). (1) Every Rust test finds the workspace root at run time through one helper, `test_support::workspace_root()`, copied byte-for-byte into each test crate, so no binary records the donor's `CARGO_MANIFEST_DIR` (rustc writes an `env!` read into dep-info as `# env-dep:`, and Cargo rebuilds a unit whose recorded value differs). (2) `target_seed.py` stops dropping every member fingerprint: it keeps a member unit when every file its rustc dep-info lists is byte-identical in the new checkout, and copies the donor's modification times onto those files, so Cargo judges the unit exactly as it would in the donor. It finds units in Cargo 1.100's `build/<package>/<hash>/` layout and the older flat one, and drops a unit whose Cargo fingerprint names the donor's path.

**Tech Stack:** Rust 2024 (cargo test, clippy pedantic), Python 3.14 (pytest, ruff), mise tasks, PowerShell 5.1 for the benchmark.

**Spec:** [issue #486](https://github.com/neilsh/stunt-reel/issues/486) (triage comment: the agent brief; item 2, `mbx`, moved to #511 and is out of scope) and [`work/2026-11/target-seeding/spec.md`](../target-seeding/spec.md) § 2 and § 7 (the follow-up "Make workspace units reusable safely").

## Global Constraints

- Run every command through `mise run <task>`; `mise tasks` lists them. Do not run `cargo` directly: the cargo tasks set `CARGO_HOME`, and a bare `cargo` rebuilds every dependency.
- `mise run check` must pass with no warnings before each commit (AGENTS.md, Committing rule 2).
- Stage files by name; never `git add -A`, `git commit -a`, or anything under `corpus/`.
- Commit subjects are Conventional Commits; end every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (or the attribution line your harness gives).
- Do not push and do not open a PR: the coordinator pushes the branch and opens the PR after the fresh review. Task 6 ends with a report. The `docs/` changes of Task 6 need a fresh reviewer before any push (AGENTS.md, Committing rule 5); that happens after this plan.
- Commit with a Bash (Git Bash) heredoc, `git commit -F - <<'EOF' … EOF`, as each commit step shows. Never commit from PowerShell: a here-string is an argument, not stdin, and PowerShell 5.1 mangles quotes in `-m`.
- Start from the plans branch `origin/neilsh/open-tasks-dsh` (PR #514), which already holds this `plan.md` and `README.md`; it need not be merged. Never stage `plan.md`. Tasks 1–5 are already committed on `perf/486-manifest-dir-runtime` in `E:\orca\workspaces\stunt-reel\dsh-486` (`7e28b21a`, `f8d2c7c7`; not pushed): continue there at Task 5R.
- `grep` calls `crates/stunt-core/tests/it/vfs_spec.rs` a binary file (it holds one NUL byte inside a literal). It is valid UTF-8; edit it normally and search it with `grep -a`.
- **STOP and ask** (do not guess) wherever a step says STOP, and whenever a command's output differs from the "Expected" line in a way the step does not cover.

## Decisions already made (do not revisit)

- 30 sites, not the issue's 29 (counted by `grep -rn 'CARGO_MANIFEST_DIR' crates/` plus `grep -an` on `vfs_spec.rs`). All are test code.
- One helper, copied as one identical file into each of the five test crates. A shared crate or a `pub` function in `stunt-core` would put run-time environment reads into the pure core (`[I7]`); `#[path]` to a file in `crates/` would sit inside the `crates/*` members glob.
- Every site calls the helper by its full path, `crate::test_support::workspace_root()`, so no `use` line is added anywhere.
- `include_str!` / `include_bytes!` with relative paths stay. rustc's dep-info records them workspace-relative (`crates\stunt-core\tests\it\../../../../tests/fixtures/...`), but Cargo's own (`fingerprint/dep-*`, binary) recorded such files by absolute path (observed 2026-11-14: `include_bytes!` fixtures, e.g. `E:\git\stunt-reel\.claude\worktrees\bench486-after-a\crates\stunt-core\tests\it\../../../../tests/fixtures/synthetic_pfont.bin`, and in clippy units `clippy.toml` and the workspace `Cargo.toml`). A unit kept with such a path watched the donor's fixture: touching B's copy left it `Fresh`. So the seed drops a unit when a file in its fingerprint directory holds the donor's path (`_names_donor`); those units rebuild in every seeded worktree.
- Cargo 1.100 keeps a unit in `target/debug/build/<package>/<hash>/` (and under `target/check/debug/` and `target/matrix/debug/`), its fingerprint in `fingerprint/` and its rustc dep-info in `out/<crate_name>-<hash>.d` (checked on `bench486-after-a` on 2026-11-14: `build/stunt-cli/855d84e6a30c8126/fingerprint/` ↔ `out/stuntreel-855d84e6a30c8126.d`). Registry crates sit in `build/<package>/<hash>/` too; a fresh 1.100 build has no `.fingerprint/` or `deps/` at all. The `.fingerprint/<package>-<hash>/` and `deps/<crate_name>-<hash>.d` entries in today's targets are Cargo 1.99 leftovers. The seed handles both layouts, because a copy can carry those leftovers and an unverified member fingerprint must not survive in either. A unit with zero or several matching `.d` files rebuilds. The seed drops a unit by deleting its fingerprint directory and leaves its outputs.
- Under Cargo 1.100 a seeded unit rebuilt only because the checkout's sources are newer than the donor's build (``Dirty stunt-core v0.1.0 (...): the file `crates\stunt-core\src\world\scenery.rs` has changed (13439171682.900649500s, 33s after last build at 13439171649.019108100s)``); the unit hashes and fingerprint JSON, the inputs to freshness, hold no checkout path. The kept outputs do (`out/*.d`, `.rlib`, `.rmeta`, `.pdb`), so panic locations and backtraces from a kept unit name the donor's files. Copying the donor's times onto byte-identical sources was enough in the 2026-11-14 run.
- A target/ counts as built, and as a donor, when its `debug/` holds `build/` or `.fingerprint/` (`_last_build`, whose newest mtime also ranks donors), and `uses_cargo_home` reads dep-info in both `deps/` and `build/*/*/out/`. Before Task 5R both looked only at the 1.99 layout, so a target/ built only by Cargo 1.100 was never chosen as a donor; today's targets qualify only through 1.99 leftovers.
- rustc dep-info lists each source a second time as a phony rule, a line that ends in `:`; the parser reads only those lines and the `# env-dep:` lines.
- One PR, four commits (Tasks 1–4, Task 5, Task 5R and Task 6), branched from `origin/neilsh/open-tasks-dsh`. Task 5R is a new commit on top of `f8d2c7c7`, not an amend. The PR targets `main` and carries the plans commit with it.
- ADR 0030 is amended in place, in ADR 0035's form (`amended <date> for [#486](…)`, newest amendment first).

## Review Focus

1. A source edited in the donor after its last build: the copied modification time is newer than the donor's fingerprint, so Cargo rebuilds the unit in the new checkout as it would in the donor. Pinned by `test_seed_keeps_a_member_unit_whose_sources_match_the_donor` asserting the copied `st_mtime_ns`.
2. A fixture pulled in by `include_bytes!` and edited (touched) in the new worktree must rebuild the unit. Cargo records such a file by the donor's absolute path, so the seed drops the unit (`watches_donor` case in Task 5R); Task 6 step 3 checks that no kept fingerprint names the donor, and step 5 that the rebuilt unit watches B's fixture.
3. A dep-info file that is not UTF-8, missing, or ambiguous (two `.d` with one hash): the unit rebuilds. Pinned by the `garbled`, `no_dep_info`, `ambiguous` cases in Task 5R, in both layouts.
4. A unit that still reads the donor's path at compile time (a future `env!("CARGO_MANIFEST_DIR")`): the seed drops it (`env_dep` case), and the guard test of Task 1 fails the gate.
5. Units that always rebuild in a seeded worktree, by design: clippy's (they record the donor's `clippy.toml`), rustdoc's (their fingerprint directory holds no `dep-*` file and `out/` no `.d`; Cargo judges them by a `Precalculated` newest-file time, observed 2026-11-14), and test units that embed files under the workspace's `tests/fixtures/`. Keeping them would mean rewriting Cargo's binary dep-info; out of scope.
6. `_names_donor` is a substring match on the normalised donor path, and on `os.path.realpath` of it (which resolves junctions); a `\\?\` prefix is still a match. A donor that Cargo recorded under yet another spelling (an 8.3 short name, a second junction or drive mapping) would not match, so its units would be kept and watch the donor's files. Not tested; the realpath spelling is not tested either.
7. Tests run outside Cargo (`CARGO_MANIFEST_DIR` unset): the helper panics with `CARGO_MANIFEST_DIR is unset: run the tests through cargo`. Not tested; every gate lane runs through Cargo.

---

### Task 1: Branch and the guard test

**Files:**
- Create: `tests/test_rust_sources.py`

**Interfaces:**
- Produces: `test_no_crate_reads_cargo_manifest_dir_at_compile_time[<crate dir>]`, one case per `crates/*` directory holding a `Cargo.toml`.

- [ ] **Step 1: Check the plans branch**

In Bash:

```bash
git fetch origin
git cat-file -e origin/neilsh/open-tasks-dsh:work/2026-11/486_manifest-dir-runtime/plan.md && echo plan-on-branch
```

Expected: `plan-on-branch`. Anything else: STOP.

- [ ] **Step 2: Check the tree is clean**

```bash
git status --porcelain
```

Expected: no output. Any line: STOP.

- [ ] **Step 3: Make the branch**

```bash
git switch -c perf/486-manifest-dir-runtime origin/neilsh/open-tasks-dsh
```

Expected: `Switched to a new branch 'perf/486-manifest-dir-runtime'`. If git refuses, STOP.

- [ ] **Step 4: Write the guard test**

`tests/test_rust_sources.py`, exactly:

```python
"""Rust sources keep their checkout's path out of every binary (issue #486).

A worktree seeded from another checkout's ``target/`` reuses that checkout's test binaries only
if none was compiled with ``env!("CARGO_MANIFEST_DIR")``: rustc records the value, and Cargo
rebuilds the unit wherever the path differs. Tests read it at run time instead.
"""

from __future__ import annotations

import pytest

from stunt_reel.dataroot import REPO_ROOT

CRATES = sorted(
    path.name for path in (REPO_ROOT / "crates").iterdir() if (path / "Cargo.toml").is_file()
)


@pytest.mark.parametrize("crate", CRATES)
def test_no_crate_reads_cargo_manifest_dir_at_compile_time(crate: str) -> None:
    hits = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted((REPO_ROOT / "crates" / crate).rglob("*.rs"))
        if b'env!("CARGO_MANIFEST_DIR")' in path.read_bytes()
    ]
    assert hits == []
```

- [ ] **Step 5: Run it and see it fail**

Run: `mise run test-py -- tests/test_rust_sources.py`
Expected: `4 failed, 1 passed` (failing: `stunt-cli`, `stunt-core`, `stunt-gltf`, `stunt-parity`; passing: `stunt-render`). If the count differs, STOP.

No commit yet: the gate must pass before a commit, and it passes after Task 4.

---

### The helper file (used by Tasks 2–4)

Every task below creates a file named `test_support.rs` with exactly this content (same bytes in all five places):

```rust
//! Paths the tests read, found at run time.
#![allow(
    clippy::expect_used,
    reason = "a test helper outside #[test]: a missing CARGO_MANIFEST_DIR is the failure"
)]

use std::path::PathBuf;

/// The workspace root, two levels above the `CARGO_MANIFEST_DIR` Cargo sets for a test run.
///
/// Read at run time, never with `env!`, so no test binary records its checkout (issue #486).
///
/// # Panics
///
/// When `CARGO_MANIFEST_DIR` is unset or has fewer than two parents.
pub(crate) fn workspace_root() -> PathBuf {
    let manifest_dir = PathBuf::from(
        std::env::var_os("CARGO_MANIFEST_DIR")
            .expect("CARGO_MANIFEST_DIR is unset: run the tests through cargo"),
    );
    manifest_dir
        .ancestors()
        .nth(2)
        .expect("CARGO_MANIFEST_DIR is crates/<name> inside the workspace")
        .to_path_buf()
}
```

The inner `#![allow]` is needed where no crate-level allow covers `expect` outside a `#[test]` (the `stunt-gltf` test binary), and harmless elsewhere; the workspace's `clippy::allow_attributes` lint checks outer `#[allow]` only.

Every site replacement below uses the call `crate::test_support::workspace_root()`. In the tables, **Old** is the text to find, **New** the text that replaces it; `⏎` marks a line break, and each line keeps the indentation it has in the file (`mise run fmt-rust` fixes the rest). After each task's edits, run `mise run fmt-rust` to reflow, then the task's checks.

**Unused imports.** If `mise run lint-rust` reports `unused import: Path` or `unused import: PathBuf` (or the pair `{Path, PathBuf}` partly unused) in a file this task edited, delete only that name from that `use std::path::...` line (delete the whole line when nothing remains). Any other lint error: STOP.

---

### Task 2: `stunt-cli` — helper and 16 sites

**Files:**
- Create: `crates/stunt-cli/src/test_support.rs` (the helper file)
- Modify: `crates/stunt-cli/src/main.rs` (register the module)
- Modify: the 11 files in the table

**Interfaces:**
- Consumes: the helper file above.
- Produces: `crate::test_support::workspace_root() -> PathBuf` in `stunt-cli` test builds.

- [ ] **Step 1: Create the helper and register it**

Create `crates/stunt-cli/src/test_support.rs` with the helper file's content. In `crates/stunt-cli/src/main.rs` replace

```rust
mod sod_trace;
mod window;
```

with

```rust
mod sod_trace;
#[cfg(test)]
mod test_support;
mod window;
```

- [ ] **Step 2: Replace the sites**

| # | File:line | Old | New |
|---|---|---|---|
| 1 | `crates/stunt-cli/src/config.rs:496-497` | `let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));`⏎`let workspace_root = manifest_dir.parent().unwrap().parent().unwrap();` | `let workspace_root = crate::test_support::workspace_root();` |
| 2 | `crates/stunt-cli/src/config.rs:515-516` | same two lines as #1 | same as #1 |
| 3 | `crates/stunt-cli/src/config.rs:549-550` | `let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));`⏎`let fixture_flm = manifest_dir.join("../../tests/fixtures/synthetic_minimal.flm");` | `let fixture_flm =`⏎`crate::test_support::workspace_root().join("tests/fixtures/synthetic_minimal.flm");` |
| 4 | `crates/stunt-cli/src/export.rs:193-194` | `Path::new(env!("CARGO_MANIFEST_DIR"))`⏎`.join("../../tests/fixtures")` | `crate::test_support::workspace_root()`⏎`.join("tests/fixtures")` |
| 5 | `crates/stunt-cli/src/link.rs:333-334` | same as #4 | same as #4 |
| 6 | `crates/stunt-cli/src/scene.rs:741-742` | same as #4 | same as #4 |
| 7 | `crates/stunt-cli/src/shape_views.rs:542-543` | same as #4 | same as #4 |
| 8 | `crates/stunt-cli/src/parity/matched.rs:111-112` | `Path::new(env!("CARGO_MANIFEST_DIR"))`⏎`.join("../../tests/fixtures/parity/matched_frames.json")` | `crate::test_support::workspace_root()`⏎`.join("tests/fixtures/parity/matched_frames.json")` |
| 9 | `crates/stunt-cli/src/parity/report_doc.rs:33` | `Path::new(env!("CARGO_MANIFEST_DIR")).join("../../research/parity/report-fields.md")` | `crate::test_support::workspace_root().join("research/parity/report-fields.md")` |
| 10 | `crates/stunt-cli/src/parity/tests.rs:338` | `std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/bench")` | `crate::test_support::workspace_root().join("tests/fixtures/parity/bench")` |
| 11 | `crates/stunt-cli/src/parity/tests.rs:364` | same as #10 | same as #10 |
| 12 | `crates/stunt-cli/src/parity_artifacts.rs:364` | `Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/v1")` | `crate::test_support::workspace_root().join("tests/fixtures/parity/v1")` |
| 13 | `crates/stunt-cli/src/parity_artifacts.rs:406` | `Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/v3/render")` | `crate::test_support::workspace_root().join("tests/fixtures/parity/v3/render")` |
| 14 | `crates/stunt-cli/src/parity_artifacts.rs:600` | `Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tests/fixtures/parity/video")` | `crate::test_support::workspace_root().join("tests/fixtures/parity/video")` |
| 15 | `crates/stunt-cli/src/playback.rs:305-306` | `std::path::Path::new(env!("CARGO_MANIFEST_DIR"))`⏎`.join("../../tests/fixtures/synthetic_timeline.flm")` | `crate::test_support::workspace_root()`⏎`.join("tests/fixtures/synthetic_timeline.flm")` |
| 16 | `crates/stunt-cli/src/zmbv.rs:257-260` and `:284`, `:297` | see below | see below |

Site 16 (`zmbv.rs`): replace

```rust
    const FIXTURE: &str = concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../tests/fixtures/parity/video/synthetic.avi"
    );
```

with

```rust
    fn fixture() -> std::path::PathBuf {
        crate::test_support::workspace_root().join("tests/fixtures/parity/video/synthetic.avi")
    }
```

and replace both `std::fs::read(FIXTURE)` (lines 284 and 297) with `std::fs::read(fixture())`.

- [ ] **Step 3: Check**

Run, in order:
1. `mise run fmt-rust` — Expected: exits 0.
2. `mise run lint-rust` — Expected: exits 0 (apply the unused-imports rule above, then re-run).
3. `mise run test-rust` — Expected: `test result: ok` for every binary, no `FAILED`.
4. `mise run test-py -- tests/test_rust_sources.py` — Expected: `3 failed, 2 passed` (`stunt-cli` now passes).

---

### Task 3: `stunt-core` — two helpers and 11 sites

**Files:**
- Create: `crates/stunt-core/src/test_support.rs` (the helper file; for the library's unit tests)
- Create: `crates/stunt-core/tests/it/test_support.rs` (the helper file; for the `it` integration-test binary)
- Modify: `crates/stunt-core/src/lib.rs`, `crates/stunt-core/tests/it/main.rs` (register)
- Modify: the 10 files in the table

**Interfaces:**
- Consumes: the helper file above.
- Produces: `crate::test_support::workspace_root()` in the `stunt-core` lib test build and in the `it` binary.

- [ ] **Step 1: Create both helpers and register them**

Create both files with the helper file's content. In `crates/stunt-core/src/lib.rs` replace

```rust
pub mod sprite;
pub mod vfs;
```

with

```rust
pub mod sprite;
#[cfg(test)]
mod test_support;
pub mod vfs;
```

In `crates/stunt-core/tests/it/main.rs` replace

```rust
mod sod_tap_test;
mod vfs_fuzz;
```

with

```rust
mod sod_tap_test;
mod test_support;
mod vfs_fuzz;
```

- [ ] **Step 2: Replace the sites**

Pattern A (`.parent().unwrap()` twice) — sites 17–21. Old:

```rust
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
```

New:

```rust
    crate::test_support::workspace_root()
        .join("tests")
```

| # | File:line |
|---|---|
| 17 | `crates/stunt-core/src/sod/vm_tests.rs:37` |
| 18 | `crates/stunt-core/tests/it/fixtures_test.rs:12` |
| 19 | `crates/stunt-core/tests/it/sod_spec.rs:33` |
| 20 | `crates/stunt-core/tests/it/sod_tap_test.rs:13` |
| 21 | `crates/stunt-core/tests/it/world_test.rs:16` |

Pattern B (`.join("..")` twice) — sites 22–24. Old (site 22 starts `Path::new(`, sites 23–24 start `PathBuf::from(`; site 24 is preceded by `let dir = `, which stays):

```rust
PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
```

New:

```rust
crate::test_support::workspace_root()
```

| # | File:line | first token of Old |
|---|---|---|
| 22 | `crates/stunt-core/tests/it/flm_spec.rs:39` | `Path::new(` |
| 23 | `crates/stunt-core/tests/it/flm_timeline_test.rs:12` | `PathBuf::from(` |
| 24 | `crates/stunt-core/tests/it/scene_test.rs:27` | `PathBuf::from(` |

Site 25, `crates/stunt-core/tests/it/flm_camera_test.rs:25-28`. Old:

```rust
                Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("..")
                    .join("..")
                    .join("corpus")
```

New:

```rust
                crate::test_support::workspace_root().join("corpus")
```

Site 26, `crates/stunt-core/tests/it/vfs_spec.rs:199-204`. Old:

```rust
    let manifest_dir = env!("CARGO_MANIFEST_DIR");
    let fixture_path = std::path::Path::new(manifest_dir)
        .parent()
        .unwrap()
        .parent()
        .unwrap()
        .join("tests")
```

New:

```rust
    let fixture_path = crate::test_support::workspace_root()
        .join("tests")
```

Site 27, `crates/stunt-core/tests/it/vfs_spec.rs:1504-1508`. Old:

```rust
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .parent()
        .unwrap();
```

New:

```rust
    let root = crate::test_support::workspace_root();
```

- [ ] **Step 3: Check**

Run, in order:
1. `mise run fmt-rust` — Expected: exits 0.
2. `mise run lint-rust` — Expected: exits 0 (unused-imports rule; `PathBuf` in `scene_test.rs` and `Path` in `flm_camera_test.rs`/`flm_spec.rs` are the likely ones).
3. `mise run test-rust` — Expected: no `FAILED`.
4. `mise run check-rust-matrix` — Expected: exits 0 (the no-default-features build of `stunt-core`).
5. `mise run test-py -- tests/test_rust_sources.py` — Expected: `2 failed, 3 passed`.

---

### Task 4: `stunt-gltf` and `stunt-parity` — helpers, 3 sites, first commit

**Files:**
- Create: `crates/stunt-gltf/tests/it/test_support.rs`, `crates/stunt-parity/src/test_support.rs` (the helper file, both)
- Modify: `crates/stunt-gltf/tests/it/main.rs`, `crates/stunt-parity/src/lib.rs` (register)
- Modify: `crates/stunt-gltf/tests/it/export_test.rs`, `crates/stunt-gltf/tests/it/gltf_import_test.rs`, `crates/stunt-parity/src/film.rs`
- Modify: `tests/test_gate_plan.py:196` (the regex that finds files Rust tests read)

**Interfaces:**
- Consumes: the helper file above.
- Produces: the finished first commit.

- [ ] **Step 1: Create both helpers and register them**

In `crates/stunt-gltf/tests/it/main.rs` replace `mod gltf_import_test;` with

```rust
mod gltf_import_test;
mod test_support;
```

In `crates/stunt-parity/src/lib.rs` replace `pub mod report;` with

```rust
pub mod report;
#[cfg(test)]
mod test_support;
```

- [ ] **Step 2: Replace the sites**

Sites 28 (`crates/stunt-gltf/tests/it/export_test.rs:32`) and 29 (`crates/stunt-gltf/tests/it/gltf_import_test.rs:26`) are Pattern B of Task 3 (Old starts `PathBuf::from(`); `let dir = ` stays.

Site 30, `crates/stunt-parity/src/film.rs:167-168`. Old:

```rust
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/parity/film_identity.json");
```

New:

```rust
        let path =
            crate::test_support::workspace_root().join("tests/fixtures/parity/film_identity.json");
```

- [ ] **Step 3: Teach the gate-plan test the new read form**

`tests/test_gate_plan.py::test_every_file_rust_reads_outside_crates_runs_the_rust_half` finds the files Rust tests read by the literal `"../../`, and asserts it finds `research/parity/report-fields.md`; site 9 removed that literal. In `tests/test_gate_plan.py` line 196 replace

```python
        for match in re.findall(r'"\.\./\.\./([^"]+)"', source.read_text(encoding="utf-8"))
```

with

```python
        for match in re.findall(
            r'(?:"\.\./\.\./|workspace_root\(\)\s*\.join\(\s*")([^"]+)"',
            source.read_text(encoding="utf-8"),
        )
```

The new matches (`tests`, `tests/fixtures/...`, `corpus`, `research/parity/report-fields.md`) are filtered or classify as `rust` or `other`, so the rest of the test is unchanged.

- [ ] **Step 4: Check nothing is left**

Run: `git grep --untracked -a -n "CARGO_MANIFEST_DIR" -- crates`
Expected: lines from `test_support.rs` files only (five per file: the `#![allow]` reason, the doc comment, `var_os` and the two `expect` messages), and no line containing `env!(`. Any other file, or any `env!(`: STOP.

- [ ] **Step 5: Check**

Run, in order:
1. `mise run fmt-rust`, then `mise run lint-rust` (unused-imports rule; `film.rs:129` `use std::path::Path;` is the likely one) — Expected: exits 0.
2. `mise run test-py -- tests/test_rust_sources.py tests/test_gate_plan.py` — Expected: all passed (`5 passed` from the guard among them).
3. `mise run check` — Expected: last line `[gate] PASS ...`.

- [ ] **Step 6: Commit**

In Bash:

```bash
git status
git add tests/test_rust_sources.py tests/test_gate_plan.py crates/stunt-cli crates/stunt-core crates/stunt-gltf crates/stunt-parity
git status
```

The second `git status` must show only the files of Tasks 1–4 staged (new `test_support.rs` files included). Anything else staged: STOP.

```bash
git commit -F - <<'EOF'
test: read CARGO_MANIFEST_DIR at run time in every Rust test (#486)

env!("CARGO_MANIFEST_DIR") put the build's checkout path into each test
binary and into rustc's dep-info, so a seeded worktree could never reuse a
donor's build of the workspace crates. One helper per test crate now reads
it at run time; tests/test_rust_sources.py keeps env! out, and the gate-plan
test finds the files tests read through workspace_root().

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: The seed keeps unchanged member units (done: `f8d2c7c7`)

Committed as `f8d2c7c7` (`perf(seed): keep a member unit whose sources match the donor's (#486)`). It added `prune_member_fingerprints`, `_reusable_unit` and `_unit_sources` for Cargo 1.99's flat layout (`.fingerprint/<package>-<hash>/`, `deps/<crate>-<hash>.d`). Cargo 1.100 does not use that layout, so the code finds no member unit: Task 6 step 3 measured every `stunt-*` crate rebuilt (22 s, 20 units, against 23 s and 20 units for origin/main's seed). Do not redo Task 5; Task 5R fixes it.

---

### Task 5R: Fit the seed to Cargo 1.100's layout

Why the units rebuilt (checked 2026-11-14 on `bench486-after-b`, seeded from `bench486-after-a`, cargo 1.100.0, `CARGO_TERM_VERBOSE=true mise run lint-rust`):

```
Dirty stunt-core v0.1.0 (...\bench486-after-b\crates\stunt-core): the file `crates\stunt-core\src\world\scenery.rs` has changed (13439171682.900649500s, 33s after last build at 13439171649.019108100s)
Dirty stunt-render v0.1.0 (...): the dependency `stunt-core` was rebuilt
```

The only reason given is the checkout's source modification times: the unit hashes, fingerprint JSON (`"path"` is a hash of the package-relative path) and `rustflags` matched. Copying the donor's times onto the sources makes those units fresh. Two facts about Cargo 1.100 shape the code:

- A unit lives in `target/debug/build/<package>/<hash>/` (`target/check/debug/build/...` and `target/matrix/debug/build/...` in the gate lanes): its fingerprint in `fingerprint/`, its rustc dep-info in `out/<crate>-<hash>.d` (for example `build/stunt-cli/855d84e6a30c8126/fingerprint/test-bin-stuntreel.json` and `.../out/stuntreel-855d84e6a30c8126.d`).
- Cargo's own dep-info, `fingerprint/dep-*` (binary), names a file inside the package relative to the package; the files outside it that were observed are named by absolute path. So `stunt-core`'s test units record `E:\...\bench486-after-a\crates\stunt-core\tests\it\../../../../tests/fixtures/synthetic_pfont.bin`, and every clippy unit records the donor's `clippy.toml` and workspace `Cargo.toml`. A copied unit that holds the donor's path watches the donor's file: touching the fixture in B left the test binary `Fresh`. The seed therefore also drops a unit when any file in its fingerprint directory holds the donor's path.

- A fresh 1.100 build writes no `debug/.fingerprint/` or `debug/deps/`. `donor_problem` called a target/ without `.fingerprint/` "not built" and `rank_donors` read that directory's mtime, so a target/ built only by 1.100 could never donate; the bench targets passed only through 1.99 leftovers.

The seed keeps handling the flat layout too: a target/ copied from the primary checkout still carries 1.99-era `.fingerprint/` directories, and an unverified member fingerprint must never survive in either layout.

**Files:**
- Modify: `python/stunt_reel/target_seed.py` (`uses_cargo_home`; `_reusable_unit`; the loop in `prune_member_fingerprints`; `donor_problem`; `rank_donors`)
- Test: `tests/test_target_seed.py` (replace the block Task 5 appended)

**Interfaces:**
- Produces: private `_member_units(seeded: Path, members: frozenset[str]) -> Iterator[tuple[Path, list[Path]]]`, `_names_donor(fingerprint: Path, donor: Path) -> bool` and `_last_build(target: Path) -> float | None`, plus the constant `_FINGERPRINT_DIRS`. `_reusable_unit` becomes `_reusable_unit(fingerprint: Path, dep_infos: list[Path], *, donor: Path, checkout: Path)`. `prune_member_fingerprints`' signature is unchanged.

- [ ] **Step 1: Check the starting point**

In Bash:

```bash
git log --oneline -3
git status --short
```

Expected: the first line starts `f8d2c7c7 perf(seed): keep a member unit whose sources match the donor's (#486)`, the second `7e28b21a test: read CARGO_MANIFEST_DIR at run time in every Rust test (#486)`; `git status --short` prints nothing, or only ` M work/2026-11/486_manifest-dir-runtime/plan.md`. Anything else: STOP.

- [ ] **Step 2: Replace the tests**

In `tests/test_target_seed.py`, delete everything from the line

```python
#: A member unit's fingerprint directory, its dep-info, and the source it names. The hash differs
```

to the end of the file (the block Task 5 appended, 74 lines), and append in its place:

```python
#: A member unit's hash, the source its dep-info names, and that source's modification time in
#: the donor, in nanoseconds (2001-09-09). The hash differs from ``_built``'s serde_core
#: dep-info, which would otherwise match the same ``*-<hash>.d``.
UNIT_HASH = "fedcba9876543210"
SOURCE = "crates/core/src/lib.rs"
OLD_NS = 1_000_000_000_000_000_000
#: Where member stunt-core's unit keeps its fingerprint and its dep-info under ``target/debug``:
#: Cargo 1.100's ``build/<package>/<hash>/`` and older Cargo's flat layout.
LAYOUTS = {
    "build": (f"build/stunt-core/{UNIT_HASH}/fingerprint", f"build/stunt-core/{UNIT_HASH}/out"),
    "flat": (f".fingerprint/stunt-core-{UNIT_HASH}", "deps"),
}


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def _member_build(donor: Path, here: Path, variant: str, layout: str) -> None:
    """The donor's debug build of member stunt-core from ``SOURCE`` in *layout*, which *here*
    holds too, spoiled the way *variant* names; ``same`` spoils nothing."""
    theirs = donor / SOURCE
    theirs.parent.mkdir(parents=True, exist_ok=True)
    theirs.write_text("pub fn a() {}\n", encoding="utf-8")
    os.utime(theirs, ns=(OLD_NS, OLD_NS))
    if variant != "missing":
        ours = here / SOURCE
        ours.parent.mkdir(parents=True, exist_ok=True)
        text = "pub fn b() {}\n" if variant == "differs" else "pub fn a() {}\n"
        ours.write_text(text, encoding="utf-8")
    debug = donor / "target" / "debug"
    fingerprint, dep_infos = LAYOUTS[layout]
    (debug / fingerprint).mkdir(parents=True)
    (debug / dep_infos).mkdir(parents=True, exist_ok=True)
    dep_info = debug / dep_infos / f"stunt_core-{UNIT_HASH}.d"
    named = f"{donor.as_posix()}/{SOURCE}" if variant == "absolute" else SOURCE
    lines = [f"{dep_info.as_posix()}: {named}", "", f"{named}:"]
    if variant == "env_dep":
        value = str(donor / "crates" / "core").replace("\\", "\\\\")
        lines.append(f"# env-dep:CARGO_MANIFEST_DIR={value}")
    if variant == "garbled":
        dep_info.write_bytes(b"\xff\xfe" + SOURCE.encode() + b":\n")
    elif variant != "no_dep_info":
        dep_info.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if variant == "ambiguous":
        (debug / dep_infos / f"it-{UNIT_HASH}.d").write_text(f"{SOURCE}:\n", encoding="utf-8")
    # Cargo's own dep-info names a file in the package relative to it, and any other file, such
    # as a fixture under the workspace's tests/, by its absolute path.
    recorded = b"\x00src\\lib.rs"
    if variant == "watches_donor":
        recorded += b"\x00" + str(donor / "tests" / "fixtures" / "a.bin").encode()
    (debug / fingerprint / "dep-lib-stunt_core").write_bytes(recorded)


def _seed_member_build(tmp_path: Path, variant: str, layout: str) -> tuple[Path, Path]:
    here = _fresh(tmp_path / "here", "stunt-core")
    donor = _donor(tmp_path / "d")
    _member_build(donor, here, variant, layout)
    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_copy_tree,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor}")
    return here, donor


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_seed_keeps_a_member_unit_whose_sources_match_the_donor(
    tmp_path: Path, layout: str
) -> None:
    """The kept unit's sources take the donor's times, so Cargo judges it as the donor would."""
    here, _ = _seed_member_build(tmp_path, "same", layout)
    assert (here / "target" / "debug" / LAYOUTS[layout][0]).is_dir()
    assert (here / SOURCE).stat().st_mtime_ns == OLD_NS


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
@pytest.mark.parametrize(
    "variant",
    [
        "differs",
        "missing",
        "absolute",
        "env_dep",
        "garbled",
        "ambiguous",
        "no_dep_info",
        "watches_donor",
    ],
)
def test_seed_drops_a_member_unit_it_cannot_prove_unchanged(
    tmp_path: Path, variant: str, layout: str
) -> None:
    here, donor = _seed_member_build(tmp_path, variant, layout)
    fingerprint = LAYOUTS[layout][0]
    assert not (here / "target" / "debug" / fingerprint).exists()
    assert (donor / "target" / "debug" / fingerprint).is_dir()
    if variant != "missing":
        assert (here / SOURCE).stat().st_mtime_ns != OLD_NS


def test_seed_drops_member_fingerprints_in_cargo_1_100_layout(tmp_path: Path) -> None:
    """Cargo 1.100 keeps a unit in ``build/<package>/<hash>/``: the seed deletes a member's
    ``fingerprint/`` there in every lane and leaves other packages' units alone."""
    here = _fresh(tmp_path / "here", "stunt-core", "stunt-cli")
    donor = _donor(tmp_path / "d", lanes=("check", "matrix"))
    kept = ("serde", "stunt-core-extra")
    dropped = ("stunt-core", "stunt-cli")
    for profile in ("debug", "check/debug", "matrix/debug"):
        for name in (*kept, *dropped):
            unit = donor / "target" / profile / "build" / name / "0123456789abcdef"
            (unit / "fingerprint").mkdir(parents=True)
    out = seed(
        here,
        checkouts=[donor],
        rustc_vv=RUSTC,
        cargo_home=Path(HOME),
        copy=_copy_tree,
        volume_clones=_clones,
    )
    assert out == SeedOutcome("seeded", f"from {donor}")
    for profile in ("debug", "check/debug", "matrix/debug"):
        build = here / "target" / profile / "build"
        left = sorted(entry.parent.parent.name for entry in build.glob("*/*/fingerprint"))
        assert left == sorted(kept), profile
        assert (build / "stunt-core" / "0123456789abcdef").is_dir(), profile
        assert (donor / "target" / profile / "build" / dropped[0] / "0123456789abcdef").is_dir()


def test_a_target_built_only_by_cargo_1_100_can_donate(tmp_path: Path) -> None:
    """Cargo 1.100 writes no ``.fingerprint/`` or ``deps/``: a unit and its dep-info sit in
    ``build/<package>/<hash>/``."""
    here = _fresh(tmp_path / "here")
    a = _donor(tmp_path / "a")
    shutil.rmtree(a / "target" / "debug" / ".fingerprint")
    shutil.rmtree(a / "target" / "debug" / "deps")
    out = a / "target" / "debug" / "build" / "serde_core" / "0123456789abcdef" / "out"
    out.mkdir(parents=True)
    source = HOME + r"\registry\src\index\serde_core\src\lib.rs"
    (out / "serde_core-0123456789abcdef.d").write_text(
        f"{out}\\serde_core-0123456789abcdef.d: {source}\n", encoding="utf-8"
    )
    assert uses_cargo_home(a / "target", Path(HOME))
    assert not uses_cargo_home(a / "target", Path(r"E:\packages\cargo"))
    assert rank_donors([a], here=here, rustc_vv=RUSTC, cargo_home=Path(HOME)) == [a]
```

Write the block with the Edit or Write tool, not through a shell or a Python string literal: either can turn a doubled backslash into one. The backslashes must reach the file exactly as shown, notably in `b"\x00src\\lib.rs"` and `f"{out}\\serde_core-0123456789abcdef.d: {source}\n"`. If Step 3 reports a `SyntaxError` about an invalid escape sequence, make those lines match the block above and rerun.

- [ ] **Step 3: Run them and see the new cases fail**

Run: `mise run test-py -- tests/test_target_seed.py`
Expected: `12 failed, 43 passed`, and the failures are exactly:

```
test_seed_keeps_a_member_unit_whose_sources_match_the_donor[build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[differs-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[missing-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[absolute-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[env_dep-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[garbled-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[ambiguous-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[no_dep_info-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[watches_donor-build]
test_seed_drops_a_member_unit_it_cannot_prove_unchanged[watches_donor-flat]
test_seed_drops_member_fingerprints_in_cargo_1_100_layout
test_a_target_built_only_by_cargo_1_100_can_donate
```

Any other count or name: STOP.

- [ ] **Step 4: Implement**

In `python/stunt_reel/target_seed.py`:

(a) In `uses_cargo_home`, replace

```python
    names a registry source decides.
    """
    wanted = _norm(cargo_home)
    dep_infos = (target / "debug" / "deps").glob("*.d")
```

with

```python
    names a registry source decides. Cargo 1.100 writes dep-info to ``build/<package>/<hash>/out/``,
    older Cargo to ``deps/``; both are read.
    """
    wanted = _norm(cargo_home)
    debug = target / "debug"
    dep_infos = [*(debug / "deps").glob("*.d"), *(debug / "build").glob("*/*/out/*.d")]
```

(b) Replace the head of `_reusable_unit`, from its `def` line through its `if len(dep_infos) != 1:` line and the `return None` under it:

```python
def _reusable_unit(
    fingerprint: Path, *, donor: Path, checkout: Path
) -> list[tuple[Path, os.stat_result]] | None:
    """*checkout*'s files the unit *fingerprint* was built from, each with *donor*'s stat.

    ``None`` unless exactly one dep-info in the sibling ``deps/`` carries the unit's hash and
    every file it names is byte-identical in both checkouts and unchanged while read.
    """
    unit_hash = fingerprint.name.rsplit("-", 1)[1]
    dep_infos = list((fingerprint.parent.parent / "deps").glob(f"*-{unit_hash}.d"))
    if len(dep_infos) != 1:
        return None
```

with

```python
def _member_units(seeded: Path, members: frozenset[str]) -> Iterator[tuple[Path, list[Path]]]:
    """Each unit of *members* in the copied directory *seeded*: its fingerprint directory and
    the rustc dep-info files that carry its hash.

    Cargo 1.100 keeps a unit in ``build/<package>/<hash>/``, its fingerprint in ``fingerprint/``
    and its dep-info in ``out/``; older Cargo kept ``.fingerprint/<package>-<hash>/`` and
    ``deps/``. A copy can hold both.
    """
    flat = re.compile("(?:" + "|".join(map(re.escape, sorted(members))) + r")-([0-9a-f]{16})")
    for profile in (seeded, *(entry for entry in seeded.iterdir() if entry.is_dir())):
        fingerprints = profile / ".fingerprint"
        if fingerprints.is_dir():
            for entry in fingerprints.iterdir():
                if match := flat.fullmatch(entry.name):
                    yield entry, list((profile / "deps").glob(f"*-{match[1]}.d"))
        for member in sorted(members):
            for fingerprint in (profile / "build" / member).glob("*/fingerprint"):
                unit = fingerprint.parent
                yield fingerprint, list((unit / "out").glob(f"*-{unit.name}.d"))


def _names_donor(fingerprint: Path, donor: Path) -> bool:
    """Whether a file in the unit's fingerprint directory *fingerprint* holds *donor*'s path.

    Cargo records a file outside the package, such as a fixture read by ``include_bytes!`` or
    clippy's ``clippy.toml``, by its absolute path, so a copied unit would watch the donor's file.
    """
    wanted = {_norm(donor), _norm(os.path.realpath(donor))}
    try:
        held = [entry.read_bytes() for entry in fingerprint.iterdir() if entry.is_file()]
    except OSError:
        return True
    texts = [_norm(data.decode("utf-8", "replace")) for data in held]
    return any(path in text for text in texts for path in wanted)


def _reusable_unit(
    fingerprint: Path, dep_infos: list[Path], *, donor: Path, checkout: Path
) -> list[tuple[Path, os.stat_result]] | None:
    """*checkout*'s files the unit *fingerprint* was built from, each with *donor*'s stat.

    ``None`` unless *dep_infos*, the unit's rustc dep-info files, is exactly one, no file in
    *fingerprint* holds *donor*'s path, and every file the dep-info names is byte-identical in
    both checkouts and unchanged while read.
    """
    if len(dep_infos) != 1 or _names_donor(fingerprint, donor):
        return None
```

The rest of `_reusable_unit` (from `sources = _unit_sources(dep_infos[0], donor)` on) stays.

(c) In `prune_member_fingerprints`, replace everything after `        return` (the end of `if not members:`) to the end of the function:

```python
    unit = re.compile("(?:" + "|".join(map(re.escape, sorted(members))) + r")-[0-9a-f]{16}")
    for fingerprints in (seeded / ".fingerprint", *seeded.glob("*/.fingerprint")):
        if not fingerprints.is_dir():
            continue
        for entry in fingerprints.iterdir():
            if not unit.fullmatch(entry.name):
                continue
            stamps = _reusable_unit(entry, donor=donor, checkout=checkout)
            if stamps is None:
                shutil.rmtree(entry)
                continue
            for path, stat in stamps:
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
```

with

```python
    # Listed before any deletion, which would otherwise change the directories being walked.
    for fingerprint, dep_infos in list(_member_units(seeded, members)):
        stamps = _reusable_unit(fingerprint, dep_infos, donor=donor, checkout=checkout)
        if stamps is None:
            shutil.rmtree(fingerprint)
            continue
        for path, stat in stamps:
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
```

(d) Replace the head of `donor_problem`:

```python
def donor_problem(checkout: Path, *, rustc_vv: str, cargo_home: Path) -> str | None:
    """Why *checkout*'s target/ cannot seed another, or ``None`` when it can."""
    target = checkout / "target"
    if not (target / "debug" / ".fingerprint").is_dir():
        return "not built"
```

with

```python
#: Where a profile keeps its units' fingerprints: ``build/`` since Cargo 1.100, ``.fingerprint/``
#: before.
_FINGERPRINT_DIRS: tuple[str, ...] = ("build", ".fingerprint")


def _last_build(target: Path) -> float | None:
    """The newest modification time of *target*'s debug fingerprint directories, or ``None``
    when it has none: *target* was never built."""
    times = [
        _mtime(target / "debug" / name)
        for name in _FINGERPRINT_DIRS
        if (target / "debug" / name).is_dir()
    ]
    return max(times) if times else None


def donor_problem(checkout: Path, *, rustc_vv: str, cargo_home: Path) -> str | None:
    """Why *checkout*'s target/ cannot seed another, or ``None`` when it can."""
    target = checkout / "target"
    if _last_build(target) is None:
        return "not built"
```

(e) In `rank_donors`, delete the line

```python
        fingerprint = checkout / "target" / "debug" / ".fingerprint"
```

and replace

```python
        ranked.append((same_lock, fingerprint.stat().st_mtime, checkout))
```

with

```python
        ranked.append((same_lock, _last_build(checkout / "target") or 0.0, checkout))
```

`Iterator` is already imported under `if TYPE_CHECKING:`; add no import.

- [ ] **Step 5: Run the tests**

Run: `mise run fix`, then `mise run test-py -- tests/test_target_seed.py`
Expected: `55 passed`. Otherwise STOP.

Run: `git status --short`
Expected: ` M python/stunt_reel/target_seed.py`, ` M tests/test_target_seed.py`, and ` M work/2026-11/486_manifest-dir-runtime/plan.md` if this plan was edited in place. `mise run fix` also rewrites `research/MAP.md` from the notes (it did not change it on 2026-11-14); if `research/MAP.md` is listed, nothing in this task touched `research/`, so run `git restore research/MAP.md`, and if `mise run check` in Step 6 then fails on it: STOP and report. Any other file listed: STOP.

Run: `mise run check-py`
Expected: `[gate] PASS 4/4 steps ...`. A ruff or mypy finding in the lines above: STOP and report it.

- [ ] **Step 6: Commit**

Run `mise run check` (Expected: `[gate] PASS ...`), then in Bash:

```bash
git status
git add python/stunt_reel/target_seed.py tests/test_target_seed.py
git commit -F - <<'EOF'
fix(seed): find member units in Cargo 1.100's build/ layout (#486)

Cargo 1.100 keeps a unit in build/<package>/<hash>/ (fingerprint/ and
out/<crate>-<hash>.d), not .fingerprint/ and deps/, so the seed found no
member unit and a seeded worktree rebuilt every workspace crate: the
checkout's sources are newer than the donor's build. The seed now walks
both layouts. It also drops a unit whose fingerprint holds the donor's
path: Cargo records a file outside the package, a fixture read by
include_bytes! or clippy's clippy.toml, by its absolute path, so the copy
would watch the donor's file. A target/ with build/ but no .fingerprint/,
which a fresh 1.100 build makes, now counts as built and can donate, and
uses_cargo_home reads 1.100's dep-info too.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

`git status` before `git add` must list only those two files as modified, and `work/2026-11/486_manifest-dir-runtime/plan.md` if this plan was edited in place; never stage `plan.md`.

---

### Task 6: Measure before and after on `E:`, record, update the docs

This task runs on the primary machine only (the issue is `local-only`): seeding needs ReFS, and `E:` is the ReFS volume. The measuring commands are PowerShell 5.1 (no `&&`). PowerShell variables do not survive between tool calls, so every block starts by setting them again; replace `<before hash>` and `<after hash>` with the values step 1 printed. Do not run another build on the machine while timing; if `Get-Process cargo,rustc -ErrorAction SilentlyContinue` lists anything at a timing step, wait for it to finish and note it.

The four bench worktrees may already exist from the first attempt (they did on 2026-11-14). Steps 2 and 3 reuse an existing A worktree, which keeps its build, and always make B afresh, so B's sources are newer than A's build exactly as in a new worktree.

**Files:**
- Create: `work/2026-11/486_manifest-dir-runtime/journal.md`
- Modify: `work/2026-11/486_manifest-dir-runtime/README.md` (`outcome`)
- Modify: `docs/development.md:174`, `docs/adr/0030-new-worktrees-seed-target-by-block-clone.md` (Status)

**Units built** below means the lines of B's `target\check.log` matching `^\s+(Compiling|Checking|Documenting) `.

- [ ] **Step 1: Record the two commits to compare**

```powershell
git merge-base HEAD origin/main
git rev-parse HEAD
```

The first line is `<before hash>`, the second `<after hash>`. Write both down.

- [ ] **Step 2: Measure "before" (origin/main's seed)**

```powershell
$P = 'E:\git\stunt-reel'; $Before = '<before hash>'; $W = "$P\.claude\worktrees\bench486-before-a"
if (Test-Path $W) { git -C $W checkout --detach $Before } else { git -C $P worktree add --detach $W $Before }
Set-Location $W
mise run check-rust
mise run check-rust
```

A `git checkout` error (local changes in the worktree): STOP. The second run is the donor's warm time: record its `[gate] PASS ... in Ns` figure as **warm**. Then:

```powershell
$P = 'E:\git\stunt-reel'; $Before = '<before hash>'; $W = "$P\.claude\worktrees\bench486-before-b"
Set-Location $P
if (Test-Path $W) { git -C $P worktree remove --force $W }
git -C $P worktree add --detach $W $Before
Set-Location $W
mise run init
```

Expected: a line `target/ seeded from E:\git\stunt-reel\.claude\worktrees\bench486-before-a`. Another donor named, or `not seeded`: STOP and report the line. If `mise` says a config file is not trusted: STOP.

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-before-b'
mise run check-rust
(Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) ').Count
Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) stunt' | ForEach-Object { $_.Line.Trim() }
```

Record as **before**: the `[gate] PASS ... in Ns` figure, each step's seconds, the units-built count, and the `stunt` lines.

- [ ] **Step 3: Measure "after" (this branch's seed)**

```powershell
$P = 'E:\git\stunt-reel'; $After = '<after hash>'; $W = "$P\.claude\worktrees\bench486-after-a"
if (Test-Path $W) { git -C $W checkout --detach $After } else { git -C $P worktree add --detach $W $After }
Set-Location $W
mise run check-rust
mise run check-rust
```

Expected: both `[gate] PASS`. A `git checkout` error: STOP. Then:

```powershell
$P = 'E:\git\stunt-reel'; $After = '<after hash>'; $W = "$P\.claude\worktrees\bench486-after-b"
Set-Location $P
if (Test-Path $W) { git -C $P worktree remove --force $W }
git -C $P worktree add --detach $W $After
Set-Location $W
mise run init
```

Expected: a line `target/ seeded from E:\git\stunt-reel\.claude\worktrees\bench486-after-a`. Another donor named, or `not seeded`: STOP and report the line.

Check that the seed gave B's sources the donor's times:

```powershell
$P = 'E:\git\stunt-reel'
(Get-Item "$P\.claude\worktrees\bench486-after-b\crates\stunt-core\src\lib.rs").LastWriteTimeUtc -eq (Get-Item "$P\.claude\worktrees\bench486-after-a\crates\stunt-core\src\lib.rs").LastWriteTimeUtc
```

Expected: `True`. `False`: the seed kept no `stunt-core` unit; STOP and report.

Count the member units the seed kept in each lane, and the kept fingerprint files that still name A:

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
foreach ($l in 'debug','check\debug','matrix\debug') { "$l " + @(Get-Item "target\$l\build\stunt-*\*\fingerprint").Count }
@(Get-Item "target\debug\build\stunt-*\*\fingerprint\*","target\check\debug\build\stunt-*\*\fingerprint\*","target\matrix\debug\build\stunt-*\*\fingerprint\*" | Select-String -SimpleMatch -List 'bench486-after-a').Count
```

Expected (2026-11-14): `debug 10`, `check\debug 4`, `matrix\debug 1`, then `0`. Record the three counts as **kept**; other non-zero counts are fine. A lane at `0`, or a last line other than `0` (a kept unit would watch A's files): STOP and report.

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
mise run check-rust
(Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) ').Count
Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) stunt' | ForEach-Object { $_.Line.Trim() }
```

Record as **after**: the `[gate] PASS ... in Ns` figure, each step's seconds, the units-built count, and the `stunt` lines. Expected: `[gate] PASS`, which is the issue's "tests pass from a seeded worktree whose donor sits at a different path" (a FAIL: STOP and report the failing step's log). Expected `stunt` lines (2026-11-14: 13 units built in all, every one of them a `stunt` line), the units the seed must drop:

- `Checking stunt-core`, `stunt-parity`, `stunt-render`, `stunt-gltf`, `stunt-cli`: clippy's units, which record A's `clippy.toml` and `Cargo.toml` by absolute path;
- `Documenting` the same five: rustdoc's units, which have no dep-info;
- `Compiling stunt-core` (twice: test lane and matrix lane) and `Compiling stunt-render`: test units that `include_*` files under the workspace's `tests/fixtures/`, which Cargo records by absolute path.

A `Compiling stunt-gltf`, `Compiling stunt-parity` or `Compiling stunt-cli` line, or a `stunt` line of a kind not listed: STOP and report the lines.

- [ ] **Step 4: Check that a kept unit still rebuilds on an edit**

`stunt-gltf`'s units were all kept and none rebuilt in step 3.

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
(Get-Item crates\stunt-gltf\src\lib.rs).LastWriteTime = Get-Date
mise run test-rust 2>&1 | Select-String 'Compiling stunt-gltf'
```

Expected: at least one `Compiling stunt-gltf` line.

- [ ] **Step 5: Check that an included fixture rebuilds its unit**

`tests/fixtures/synthetic_pfont.bin` reaches `stunt-core`'s `it` binary through `include_bytes!`. The seed dropped that unit and step 3 rebuilt it in B, so this checks that Cargo now watches B's copy of the fixture, not A's.

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
(Get-Item tests\fixtures\synthetic_pfont.bin).LastWriteTime = Get-Date
mise run test-rust 2>&1 | Select-String 'Compiling stunt-core'
```

Expected: at least one `Compiling stunt-core` line. If step 4 or step 5 prints nothing, the seed keeps a unit Cargo judges against the donor's files: STOP, keep the worktrees, and report.

- [ ] **Step 6: Remove the four worktrees**

These were made by `git worktree add` and hold no data-root links, so `git worktree remove` is right for them (the `reap` rule covers worktrees an older `init` linked).

```powershell
$P = 'E:\git\stunt-reel'
Set-Location 'E:\orca\workspaces\stunt-reel\open-tasks-dsh'
foreach ($w in 'before-a','before-b','after-a','after-b') { git -C $P worktree remove --force "$P\.claude\worktrees\bench486-$w" }
git -C $P worktree list | Select-String bench486
```

Expected: the last command prints nothing.

- [ ] **Step 7: Write the journal entry**

Create `work/2026-11/486_manifest-dir-runtime/journal.md` (replace each `<...>` with the recorded value; the date is the day you measured):

```markdown
# Journal: Read `CARGO_MANIFEST_DIR` at run time (#486)

## <YYYY-MM-DD>: First check-rust of a seeded worktree, before and after

- **Question**: How long does a new worktree's first `mise run check-rust` take once the seed keeps unchanged workspace units, against origin/main's seed, which drops them all?
- **Method**: On `E:` (ReFS), for each commit, worktree A built by `mise run check-rust` twice, then worktree B made with `git worktree add --detach`, seeded by `mise run init` from A, and timed with `mise run check-rust` (the gate's own total). Before: `<before hash>`; after: `<after hash>`. Units built counted from B's `target/check.log` (`Compiling`, `Checking` and `Documenting` lines). In the after B, `crates/stunt-core/src/lib.rs` carried A's modification time after the seed, no kept fingerprint file named A's path, a touched `crates/stunt-gltf/src/lib.rs` made `mise run test-rust` compile `stunt-gltf`, and a touched `tests/fixtures/synthetic_pfont.bin` made it compile `stunt-core`. Cargo 1.100.0 keeps a unit in `build/<package>/<hash>/` (`fingerprint/`, `out/<crate>-<hash>.d`), and its own dep-info (`fingerprint/dep-*`) names a file outside the package by absolute path: clippy's `clippy.toml` and `Cargo.toml`, and fixtures under `tests/fixtures/`; the seed drops such units.
- **Result**: Warm (A's second run): <warm> s. Before: <before> s, <before count> units built (<before stunt lines, comma-separated>). After: <after> s, <after count> units built (<after stunt lines, comma-separated>); member units kept per lane: debug <n>, check <n>, matrix <n>. Per step before/after: fmt <s>/<s>, clippy <s>/<s>, test <s>/<s>, doc <s>/<s>, matrix <s>/<s>. <Note any other build seen running.>
- **Verdict**: adopted: the after B passed the gate, rebuilt only the units the seed must drop (clippy's, rustdoc's, and the test units that embed workspace fixtures), and rebuilt `stunt-gltf` and `stunt-core` on the two touches; its first Rust lanes took <after> s against <before> s.
- **Lives in**: [`docs/development.md`](../../../docs/development.md) (Shared tool cache) and [ADR 0030](../../../docs/adr/0030-new-worktrees-seed-target-by-block-clone.md) (Status).
```

If **after** is not lower than **before**, write the verdict as `rejected: <after> s against <before> s` and STOP before step 8: report the figures.

- [ ] **Step 8: Update the docs and the README**

`docs/development.md` line 174: replace

```
every dependency arrives fresh, and the workspace crates always rebuild. A new worktree's first Rust lanes take about 40 s instead of 91 s.
```

with

```
every dependency arrives fresh, and a workspace crate's unit is kept only where every file it was built from is byte-identical to the donor's and Cargo records none of them by the donor's absolute path; clippy's and rustdoc's units, and test units that embed files under `tests/fixtures/`, rebuild. A new worktree's first Rust lanes take about <after, rounded to whole seconds> s instead of 91 s.
```

`docs/adr/0030-new-worktrees-seed-target-by-block-clone.md`: insert directly under the `## Status` heading and its blank line, before the `amended 2026-11-04 ...` paragraph (newest amendment first), this paragraph and one blank line:

```
amended <YYYY-MM-DD> for [#486](https://github.com/neilsh/stunt-reel/issues/486): Rust tests
read `CARGO_MANIFEST_DIR` at run time, and the seed keeps a workspace crate's unit only where
every file it was built from is byte-identical to the donor's and Cargo records none of them by
the donor's absolute path, giving those files the donor's modification times; clippy's and
rustdoc's units, and test units that embed workspace fixtures, still rebuild. A new worktree's
first Rust lanes took <after> s against <before> s
([journal](../../work/2026-11/486_manifest-dir-runtime/journal.md)).
```

`work/2026-11/486_manifest-dir-runtime/README.md`: set the `outcome:` line to

```
outcome: "Tests read CARGO_MANIFEST_DIR at run time; the seed keeps unchanged workspace units. First seeded check-rust <after> s against <before> s (journal.md)."
```

- [ ] **Step 9: Commit**

Run `mise run check` (Expected: `[gate] PASS ...`), then in Bash:

```bash
git status
git add work/2026-11/486_manifest-dir-runtime/journal.md work/2026-11/486_manifest-dir-runtime/README.md docs/development.md docs/adr/0030-new-worktrees-seed-target-by-block-clone.md
git status
```

The second `git status` must show only those four files staged (`plan.md` is already committed on the plans branch and unchanged). Anything else staged: STOP.

```bash
git commit -F - <<'EOF'
docs(seed): record the seeded worktree's check-rust before and after (#486)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Do not push: the `docs/` changes need a fresh reviewer first (AGENTS.md, Committing rule 5). Report: the four commit hashes, the before, after and warm figures, the units-built counts and `stunt` lines, and that nothing was pushed.

- [ ] **Step 10 (whoever pushes the branch): Sync with `main` before merging.** This branch and its sibling PRs (#514 and the other plans' PRs) each carry the same plans commit, and a sibling's squash merge does not make that commit an ancestor here. So after any sibling has merged, and before this PR merges, run in Git Bash: `git fetch origin && git merge origin/main`. An add/add conflict under `work/2026-11/` is expected: for each conflicted path under `work/2026-11/486_manifest-dir-runtime/`, run `git checkout --ours -- <path>`; for each other conflicted path under `work/2026-11/`, run `git checkout --theirs -- <path>`. Then `git add` those paths, `git commit --no-edit`, run `mise run check` (expect `PASS`), and push. Any conflict outside `work/2026-11/`: STOP and report.
