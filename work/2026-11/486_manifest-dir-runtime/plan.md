# Read `CARGO_MANIFEST_DIR` at run time; seed keeps unchanged workspace units — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new worktree seeded from a donor keeps the donor's builds of the workspace crates whose sources are unchanged, so its first `mise run check-rust` drops from about 40 s toward the 22 s warm time.

**Architecture:** Two changes, one branch, two code commits. (1) Every Rust test finds the workspace root at run time through one helper, `test_support::workspace_root()`, copied byte-for-byte into each test crate, so no binary records the donor's `CARGO_MANIFEST_DIR` (rustc writes an `env!` read into dep-info as `# env-dep:`, and Cargo rebuilds a unit whose recorded value differs). (2) `target_seed.py` stops dropping every member fingerprint: it keeps a member unit when every file its rustc dep-info lists is byte-identical in the new checkout, and copies the donor's modification times onto those files, so Cargo judges the unit exactly as it would in the donor.

**Tech Stack:** Rust 2024 (cargo test, clippy pedantic), Python 3.14 (pytest, ruff), mise tasks, PowerShell 5.1 for the benchmark.

**Spec:** [issue #486](https://github.com/neilsh/stunt-reel/issues/486) (triage comment: the agent brief; item 2, `mbx`, moved to #511 and is out of scope) and [`work/2026-11/target-seeding/spec.md`](../target-seeding/spec.md) § 2 and § 7 (the follow-up "Make workspace units reusable safely").

## Global Constraints

- Run every command through `mise run <task>`; `mise tasks` lists them. Do not run `cargo` directly: the cargo tasks set `CARGO_HOME`, and a bare `cargo` rebuilds every dependency.
- `mise run check` must pass with no warnings before each commit (AGENTS.md, Committing rule 2).
- Stage files by name; never `git add -A`, `git commit -a`, anything under `corpus/`, or the untracked folders `work/2026-11/473_memory-map-split/` and `work/2026-11/507_reviewer-pr-comments/`.
- Commit subjects are Conventional Commits; end every commit message with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (or the attribution line your harness gives).
- Do not push and do not open a PR. Task 6 ends with a report. The `docs/` changes of Task 6 need a fresh reviewer before any push (AGENTS.md, Committing rule 5); that happens after this plan.
- Commit with a Bash (Git Bash) heredoc, `git commit -F - <<'EOF' … EOF`, as each commit step shows. Never commit from PowerShell: a here-string is an argument, not stdin, and PowerShell 5.1 mangles quotes in `-m`.
- `plan.md` and `README.md` of this folder reach `origin/main` through a separate plans PR before you start. Never stage `plan.md`.
- `grep` calls `crates/stunt-core/tests/it/vfs_spec.rs` a binary file (it holds one NUL byte inside a literal). It is valid UTF-8; edit it normally and search it with `grep -a`.
- **STOP and ask** (do not guess) wherever a step says STOP, and whenever a command's output differs from the "Expected" line in a way the step does not cover.

## Decisions already made (do not revisit)

- 30 sites, not the issue's 29 (counted by `grep -rn 'CARGO_MANIFEST_DIR' crates/` plus `grep -an` on `vfs_spec.rs`). All are test code.
- One helper, copied as one identical file into each of the five test crates. A shared crate or a `pub` function in `stunt-core` would put run-time environment reads into the pure core (`[I7]`); `#[path]` to a file in `crates/` would sit inside the `crates/*` members glob.
- Every site calls the helper by its full path, `crate::test_support::workspace_root()`, so no `use` line is added anywhere.
- `include_str!` / `include_bytes!` with relative paths stay: rustc records them workspace-relative (`crates\stunt-core\tests\it\../../../../tests/fixtures/...`), which resolve inside each checkout. Task 6 step 5 checks this on a real seeded worktree.
- A fingerprint directory `<package>-<hash>` and its rustc dep-info `deps/<crate_name>-<hash>.d` share the hash (checked on `E:\git\stunt-reel\target\debug` on 2026-11-14: `.fingerprint/stunt-core-7c670b3f046ddfe9` ↔ `deps/it-7c670b3f046ddfe9.d`). A unit with zero or several matching `.d` files rebuilds.
- rustc dep-info lists each source a second time as a phony rule, a line that ends in `:`; the parser reads only those lines and the `# env-dep:` lines.
- One PR, three commits (Tasks 4, 5 and 6), branched from `origin/main` after the plans PR that adds this file has merged.
- ADR 0030 is amended in place, in ADR 0035's form (`amended <date> for [#486](…)`, newest amendment first).

## Review Focus

1. A source edited in the donor after its last build: the copied modification time is newer than the donor's fingerprint, so Cargo rebuilds the unit in the new checkout as it would in the donor. Pinned by `test_seed_keeps_a_member_unit_whose_sources_match_the_donor` asserting the copied `st_mtime_ns`.
2. A fixture pulled in by `include_bytes!` and edited (touched) in the new worktree must rebuild the unit. Pinned by Task 6 step 5 on a real seeded worktree.
3. A dep-info file that is not UTF-8, missing, or ambiguous (two `.d` with one hash): the unit rebuilds. Pinned by the `garbled`, `no_dep_info`, `ambiguous` cases in Task 5.
4. A unit that still reads the donor's path at compile time (a future `env!("CARGO_MANIFEST_DIR")`): the seed drops it (`env_dep` case), and the guard test of Task 1 fails the gate.
5. Tests run outside Cargo (`CARGO_MANIFEST_DIR` unset): the helper panics with `CARGO_MANIFEST_DIR is unset: run the tests through cargo`. Not tested; every gate lane runs through Cargo.

---

### Task 1: Branch and the guard test

**Files:**
- Create: `tests/test_rust_sources.py`

**Interfaces:**
- Produces: `test_no_crate_reads_cargo_manifest_dir_at_compile_time[<crate dir>]`, one case per `crates/*` directory holding a `Cargo.toml`.

- [ ] **Step 1: Check the plan is on `origin/main`**

In Bash:

```bash
git fetch origin
git cat-file -e origin/main:work/2026-11/486_manifest-dir-runtime/plan.md && echo plan-on-main
```

Expected: `plan-on-main`. Anything else (the plans PR has not merged): STOP.

- [ ] **Step 2: Clear untracked copies of this folder's files**

An untracked `plan.md` or `README.md` here would block the switch to `origin/main`, which tracks them. In Bash:

```bash
for f in plan.md README.md; do
  p=work/2026-11/486_manifest-dir-runtime/$f
  if [ -n "$(git status --porcelain -- "$p" | grep '^??')" ]; then
    if [ "$(git hash-object "$p")" = "$(git rev-parse "origin/main:$p")" ]; then rm "$p"; echo "removed $p"; else echo "DIFFERS $p"; fi
  fi
done
```

Expected: nothing, or `removed ...` lines. Any `DIFFERS` line: STOP (the local copy holds edits that `origin/main` lacks).

- [ ] **Step 3: Make the branch**

```bash
git switch -c perf/486-manifest-dir-runtime origin/main
```

Expected: `Switched to a new branch 'perf/486-manifest-dir-runtime'`. The untracked folders `work/2026-11/473_memory-map-split/` and `work/2026-11/507_reviewer-pr-comments/` stay untracked. If git refuses, STOP.

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

### Task 5: The seed keeps unchanged member units

**Files:**
- Modify: `python/stunt_reel/target_seed.py` (module docstring lines 1–11; replace `drop_member_fingerprints` lines 170–186; `_copy_from` lines 466–487)
- Test: `tests/test_target_seed.py` (append)

**Interfaces:**
- Produces: `prune_member_fingerprints(seeded: Path, members: frozenset[str], *, donor: Path, checkout: Path) -> None` (replaces `drop_member_fingerprints`, whose only caller is `_copy_from`). Private helpers `_unit_sources(dep_info: Path, donor: Path) -> list[str] | None` and `_reusable_unit(fingerprint: Path, *, donor: Path, checkout: Path) -> list[tuple[Path, os.stat_result]] | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_target_seed.py`:

```python
#: A member unit's fingerprint directory, its dep-info, and the source it names. The hash differs
#: from ``_built``'s serde_core dep-info, which would otherwise match the same ``*-<hash>.d``.
UNIT = "stunt-core-fedcba9876543210"
UNIT_DEP_INFO = "stunt_core-fedcba9876543210.d"
SOURCE = "crates/core/src/lib.rs"
#: The donor source's modification time, in nanoseconds (2001-09-09).
OLD_NS = 1_000_000_000_000_000_000


def _copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination)


def _member_build(donor: Path, here: Path, variant: str) -> None:
    """The donor's debug build of member stunt-core from ``SOURCE``, which *here* holds too,
    spoiled the way *variant* names; ``same`` spoils nothing."""
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
    (debug / ".fingerprint" / UNIT).mkdir(parents=True)
    named = f"{donor.as_posix()}/{SOURCE}" if variant == "absolute" else SOURCE
    lines = [f"{debug.as_posix()}/deps/{UNIT_DEP_INFO}: {named}", "", f"{named}:"]
    if variant == "env_dep":
        value = str(donor / "crates" / "core").replace("\\", "\\\\")
        lines.append(f"# env-dep:CARGO_MANIFEST_DIR={value}")
    dep_info = debug / "deps" / UNIT_DEP_INFO
    if variant == "garbled":
        dep_info.write_bytes(b"\xff\xfe" + SOURCE.encode() + b":\n")
    elif variant != "no_dep_info":
        dep_info.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if variant == "ambiguous":
        (debug / "deps" / "it-fedcba9876543210.d").write_text(f"{SOURCE}:\n", encoding="utf-8")


def _seed_member_build(tmp_path: Path, variant: str) -> tuple[Path, Path]:
    here = _fresh(tmp_path / "here", "stunt-core")
    donor = _donor(tmp_path / "d")
    _member_build(donor, here, variant)
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


def test_seed_keeps_a_member_unit_whose_sources_match_the_donor(tmp_path: Path) -> None:
    """The kept unit's sources take the donor's times, so Cargo judges it as the donor would."""
    here, _ = _seed_member_build(tmp_path, "same")
    assert (here / "target" / "debug" / ".fingerprint" / UNIT).is_dir()
    assert (here / SOURCE).stat().st_mtime_ns == OLD_NS


@pytest.mark.parametrize(
    "variant",
    ["differs", "missing", "absolute", "env_dep", "garbled", "ambiguous", "no_dep_info"],
)
def test_seed_drops_a_member_unit_it_cannot_prove_unchanged(tmp_path: Path, variant: str) -> None:
    here, donor = _seed_member_build(tmp_path, variant)
    assert not (here / "target" / "debug" / ".fingerprint" / UNIT).exists()
    assert (donor / "target" / "debug" / ".fingerprint" / UNIT).is_dir()
    if variant != "missing":
        assert (here / SOURCE).stat().st_mtime_ns != OLD_NS
```

- [ ] **Step 2: Run them and see the keep test fail**

Run: `mise run test-py -- tests/test_target_seed.py`
Expected: exactly one failure, `test_seed_keeps_a_member_unit_whose_sources_match_the_donor` (the unit is dropped today); the seven `drops` cases and every existing test pass. Otherwise STOP.

- [ ] **Step 3: Implement**

In `python/stunt_reel/target_seed.py`:

(a) Module docstring: replace these three lines (lines 5–7)

```
cache by the same path: a different ``CARGO_HOME`` path alone rebuilds every dependency. The
checkout's own crates always rebuild, because the seed drops their fingerprints
(``drop_member_fingerprints``). On ReFS the copy clones blocks instead of writing them, so a
```

with these four

```
cache by the same path: a different ``CARGO_HOME`` path alone rebuilds every dependency. A unit
of the checkout's own crates keeps its fingerprint only where every file it was built from
matches the donor's, and rebuilds otherwise (``prune_member_fingerprints``). On ReFS the copy
clones blocks instead of writing them, so a
```

(b) Below `_REGISTRY_MARKERS = ...` add:

```python
#: The dep-info line prefix rustc writes for an environment variable a crate read at compile time.
_ENV_DEP = "# env-dep:"
```

(c) Replace the whole `drop_member_fingerprints` function (lines 170–186) with:

```python
def _unit_sources(dep_info: Path, donor: Path) -> list[str] | None:
    """The workspace-relative files rustc read to build a unit, from its dep-info *dep_info*.

    ``None`` when the unit cannot be reused: the file is unreadable or names no source, a source
    is absolute, or a recorded environment value holds *donor*'s path.
    """
    try:
        text = dep_info.read_text(encoding="utf-8")
    except OSError, ValueError:
        return None
    donor_path = _norm(donor)
    sources: list[str] = []
    for line in text.splitlines():
        if line.startswith(_ENV_DEP):
            # rustc doubles each backslash in an env-dep value.
            if donor_path in _norm(line.removeprefix(_ENV_DEP).replace("\\\\", "\\")):
                return None
            continue
        # Each source appears once more as a phony rule of its own: a line ending in a colon.
        if line.startswith("#") or not line.endswith(":"):
            continue
        source = line[:-1].replace("\\ ", " ")
        if source.startswith(("/", "\\")) or os.path.splitdrive(source)[0]:
            return None
        sources.append(source)
    return sources or None


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
    sources = _unit_sources(dep_infos[0], donor)
    if sources is None:
        return None
    stamps: list[tuple[Path, os.stat_result]] = []
    for source in sources:
        theirs, ours = donor / source, checkout / source
        try:
            before = theirs.stat()
            same = theirs.read_bytes() == ours.read_bytes()
            after = theirs.stat()
        except OSError:
            return None
        if not same or before.st_mtime_ns != after.st_mtime_ns:
            return None
        stamps.append((ours, before))
    return stamps


def prune_member_fingerprints(
    seeded: Path, members: frozenset[str], *, donor: Path, checkout: Path
) -> None:
    """Delete the fingerprints of *members*' units under the copied directory *seeded*, except
    those whose sources are byte-identical in *checkout* and *donor*.

    Cargo calls a workspace unit fresh when its sources are older than its outputs, whatever they
    hold, so a unit that may differ from the donor's must rebuild. A kept unit's sources take the
    donor's modification times, so Cargo judges it here as it would in *donor*.
    """
    if not members:
        return
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

(d) In `_copy_from`: replace the docstring sentence

```
    The copy keeps no fingerprint of *members*, the checkout's own crates: they always rebuild.
```

with

```
    The copy keeps a fingerprint of *members*, the checkout's own crates, only where the unit's
    sources match the donor's (``prune_member_fingerprints``).
```

and replace the call

```python
                drop_member_fingerprints(staging / name, members)
```

with

```python
                prune_member_fingerprints(
                    staging / name, members, donor=donor, checkout=target.parent
                )
```

- [ ] **Step 4: Run the tests**

Run: `mise run fix`, then `mise run test-py -- tests/test_target_seed.py`
Expected: all pass, including `test_seed_drops_workspace_fingerprints` unchanged: its fingerprint directories are still dropped, since none has a dep-info that names a workspace source.

Run: `mise run check-py`
Expected: exits 0 (ruff, mypy, pytest). A mypy error about `os.stat_result` or the `except OSError, ValueError:` form: STOP.

- [ ] **Step 5: Commit**

Run `mise run check` (Expected: `[gate] PASS ...`), then in Bash:

```bash
git status
git add python/stunt_reel/target_seed.py tests/test_target_seed.py
git commit -F - <<'EOF'
perf(seed): keep a member unit whose sources match the donor's (#486)

A workspace unit was always rebuilt in a seeded worktree, about 18 s. Now
the seed keeps a member's fingerprint when every file its rustc dep-info
lists is byte-identical in the new checkout, and gives those files the
donor's times, so Cargo judges the unit as it would in the donor. A unit
whose dep-info is missing, ambiguous, names an absolute path or records the
donor's path still rebuilds.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Measure before and after on `E:`, record, update the docs

This task runs on the primary machine only (the issue is `local-only`): seeding needs ReFS, and `E:` is the ReFS volume. The measuring commands are PowerShell 5.1 (no `&&`). PowerShell variables do not survive between tool calls, so every block starts by setting them again; replace `<before hash>` and `<after hash>` with the values step 1 printed. Do not run another build on the machine while timing; if `Get-Process cargo,rustc -ErrorAction SilentlyContinue` lists anything at a timing step, wait for it to finish and note it.

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
$P = 'E:\git\stunt-reel'; $Before = '<before hash>'
git -C $P worktree add --detach "$P\.claude\worktrees\bench486-before-a" $Before
Set-Location "$P\.claude\worktrees\bench486-before-a"
mise run check-rust
mise run check-rust
```

The second run is the donor's warm time: record its `[gate] PASS ... in Ns` figure as **warm**. Then:

```powershell
$P = 'E:\git\stunt-reel'; $Before = '<before hash>'
git -C $P worktree add --detach "$P\.claude\worktrees\bench486-before-b" $Before
Set-Location "$P\.claude\worktrees\bench486-before-b"
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
$P = 'E:\git\stunt-reel'; $After = '<after hash>'
git -C $P worktree add --detach "$P\.claude\worktrees\bench486-after-a" $After
Set-Location "$P\.claude\worktrees\bench486-after-a"
mise run check-rust
mise run check-rust
```

Expected: both `[gate] PASS`. Then:

```powershell
$P = 'E:\git\stunt-reel'; $After = '<after hash>'
git -C $P worktree add --detach "$P\.claude\worktrees\bench486-after-b" $After
Set-Location "$P\.claude\worktrees\bench486-after-b"
mise run init
```

Expected: a line `target/ seeded from E:\git\stunt-reel\.claude\worktrees\bench486-after-a`. Another donor named, or `not seeded`: STOP and report the line.

Check that the seed gave B's sources the donor's times:

```powershell
$P = 'E:\git\stunt-reel'
(Get-Item "$P\.claude\worktrees\bench486-after-b\crates\stunt-core\src\lib.rs").LastWriteTimeUtc -eq (Get-Item "$P\.claude\worktrees\bench486-after-a\crates\stunt-core\src\lib.rs").LastWriteTimeUtc
```

Expected: `True`. `False`: the seed kept no `stunt-core` unit; STOP and report.

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
mise run check-rust
(Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) ').Count
Select-String -Path target\check.log -Pattern '^\s+(Compiling|Checking|Documenting) stunt' | ForEach-Object { $_.Line.Trim() }
```

Record as **after**: the `[gate] PASS ... in Ns` figure, each step's seconds, the units-built count, and the `stunt` lines. Expected: `[gate] PASS`, which is the issue's "tests pass from a seeded worktree whose donor sits at a different path" (a FAIL: STOP and report the failing step's log), and no `Compiling stunt` or `Checking stunt` line, since A and B hold the same sources (`Documenting stunt` lines are allowed: a rustdoc unit with no dep-info rebuilds). A `Compiling stunt` or `Checking stunt` line: STOP and report the lines.

- [ ] **Step 4: Check that a kept unit still rebuilds on an edit**

```powershell
Set-Location 'E:\git\stunt-reel\.claude\worktrees\bench486-after-b'
(Get-Item crates\stunt-core\src\lib.rs).LastWriteTime = Get-Date
mise run test-rust 2>&1 | Select-String 'Compiling stunt-core'
```

Expected: at least one `Compiling stunt-core` line.

- [ ] **Step 5: Check that an included fixture rebuilds its unit**

`tests/fixtures/synthetic_pfont.bin` reaches `stunt-core`'s `it` binary through `include_bytes!`.

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
- **Method**: On `E:` (ReFS), for each commit, worktree A built by `mise run check-rust` twice, then worktree B made with `git worktree add --detach`, seeded by `mise run init` from A, and timed with `mise run check-rust` (the gate's own total). Before: `<before hash>`; after: `<after hash>`. Units built counted from B's `target/check.log` (`Compiling`, `Checking` and `Documenting` lines). In the after B, `crates/stunt-core/src/lib.rs` carried A's modification time after the seed, and a touched `crates/stunt-core/src/lib.rs` and a touched `tests/fixtures/synthetic_pfont.bin` each made `mise run test-rust` compile `stunt-core`.
- **Result**: Warm (A's second run): <warm> s. Before: <before> s, <before count> units built (<before stunt lines, comma-separated>). After: <after> s, <after count> units built (<after stunt lines, or "none">). Per step before/after: fmt <s>/<s>, clippy <s>/<s>, test <s>/<s>, doc <s>/<s>, matrix <s>/<s>. <Note any other build seen running.>
- **Verdict**: adopted: the after B passed the gate, built no `stunt` unit but rustdoc's, and rebuilt `stunt-core` on both touches; its first Rust lanes took <after> s against <before> s.
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
every dependency arrives fresh, and a workspace crate's unit is kept only where every file it was built from is byte-identical to the donor's, and rebuilds otherwise. A new worktree's first Rust lanes take about <after, rounded to whole seconds> s instead of 91 s.
```

`docs/adr/0030-new-worktrees-seed-target-by-block-clone.md`: insert directly under the `## Status` heading and its blank line, before the `amended 2026-11-04 ...` paragraph (newest amendment first), this paragraph and one blank line:

```
amended <YYYY-MM-DD> for [#486](https://github.com/neilsh/stunt-reel/issues/486): Rust tests
read `CARGO_MANIFEST_DIR` at run time, and the seed keeps a workspace crate's unit only where
every file it was built from is byte-identical to the donor's, giving those files the donor's
modification times; a new worktree's first Rust lanes took <after> s against <before> s
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

The second `git status` must show only those four files staged (`plan.md` is already on `origin/main` and unchanged). Anything else staged: STOP.

```bash
git commit -F - <<'EOF'
docs(seed): record the seeded worktree's check-rust before and after (#486)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

Do not push: the `docs/` changes need a fresh reviewer first (AGENTS.md, Committing rule 5). Report: the three commit hashes, the before, after and warm figures, the units-built counts and `stunt` lines, and that nothing was pushed.
