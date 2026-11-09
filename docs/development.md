# Development guide

Setup, project layout and the quality gate for working on `stunt-reel`; each task's commands are a [how-to guide](#how-to-guides). The project overview is in the [README](../README.md); contributor and agent rules are in [`AGENTS.md`](../AGENTS.md).

## Requirements

- **[mise](https://mise.jdx.dev/)** (recommended environment and tool manager)
- **[Rust](https://www.rust-lang.org/)** 2024 edition (MSRV 1.88; the pinned toolchain is 1.99.1), managed via `mise` or `rustup`
- **[uv](https://docs.astral.sh/uv/)** (installed by `mise`, which pins the exact version; `required-version` in [`pyproject.toml`](../pyproject.toml) refuses a standalone uv older than that pin) and **Python ≥ 3.15** (mise installs the pinned interpreter; under `mise`, `[tool.uv] python-preference` keeps uv on it instead of downloading a newer one the floor allows)
- **[ffmpeg](https://ffmpeg.org/)** on `PATH` (only for `--video` export)
- **[dosbox-automation](https://github.com/dosbox-automation/dosbox-automation) `0.85.1`** (a DOSBox Staging fork with a REST and Lua API; Windows x64 portable zip, installed by `mise`)
- **Java 21 (Temurin)** and **Kaitai Struct Compiler `0.11`** (managed via `mise`; needed only for the `.ksy` corpus checks)

---

## Setup

### 1. mise

```powershell
mise trust     # once per fresh clone, if mise asks you to trust the config
mise install   # pinned toolchains, dosbox-automation, Kaitai compiler
mise run init  # optional: seed target/, set the hooks path and uv sync now
```

Pinned versions live in [`mise.toml`](../mise.toml); `mise run init` runs `uv sync`, which installs the `kaitaistruct==0.11` runtime for the schema checks. It also points git's `core.hooksPath` at the committed [`.githooks/`](../.githooks/), whose pre-commit hook runs `mise run pre-commit` (see [Development & Quality Assurance](#development--quality-assurance)).

> [!NOTE]
> The quality gate (`mise run check`) runs on Linux, macOS and Windows. Capture, parity and corpus workflows are Windows + dosbox-automation + local-corpus only; elsewhere you can still build, test and render from synthetic fixtures.

### 2. dosbox-automation

`mise install` puts `dosbox` on the `mise` path; `capture-ref`, `probe-light`, `make-all` and `play` find it through `mise exec` (or `DOSBOX_AUTOMATION_EXE`). Nothing is registered with an agent: each run stages a mount and a conf under the data root (`<data>/stage/<film>-<label>/`), starts the emulator on a free web-server port with a random bearer token passed in the environment, and talks to it over REST. A capture is a plan, a trace pass and a dump pass of Lua that Python checks against each other ([ADR 0025](adr/0025-capture-runs-are-plans-not-sessions.md)), so two runs never collide.

### 3. Worktrees and the shared data root

Several agents can work at once, each in its own `git worktree` under `.claude/worktrees/` or `.agents/worktrees/`, gitignored directories inside the primary checkout, where `mise run reap` looks for merged worktrees; one candidate with modified or untracked files stops the whole batch unless `--stash-dirty` or `--discard-untracked` allows it. The game files and the captures are gitignored, so they live once per machine instead of once per checkout:

```text
<parent-of-checkout>\stunt-reel.data\   corpus\{stisldem,siarchive,stuntisl,patches}, captures\<film>\{frames,video,archives}\
```

Code reads them there through `stunt_reel.dataroot` (`data_root()`, `corpus_root()`, `resolve_data_path()`), so a worktree holds no link and needs no setup step; a `--film corpus/...` argument resolves against the data root too, and a clone that keeps its game files in its own `corpus/` is read there only when `STUNT_DATA_ROOT` is unset, the data root has no `corpus/` directory at all (an empty one still wins), and the primary checkout's `corpus/` holds a folder of game files ([ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md)). Build outputs, the Python tool caches and `.venv` stay per worktree (see [Shared tool cache](#shared-tool-cache)). `STUNT_DATA_ROOT` names a different data root, and `mise run init -- --migrate` first converts an old-layout data root (`stisldem`, `si_archive`, `oracle`, `target_bin`, `reference`) to the layout above, refusing a root that holds both old and new names, then moves an existing in-checkout `corpus/` into it. Worktrees an older `init` linked keep their junctions until reaped: `reap` finds them as reparse points and unlinks them, and `LINK_TARGETS` in `python/stunt_reel/dataroot.py` names the old paths for `init`'s report and `--migrate`.

A film needs an `.ALL` to be captured: one beside its `.FLM`, or one that `make-all` stored under `captures/<film>/archives/` and recorded as a committed manifest under `manifests/all/` ([Make a film's archive](howto/make-a-films-archive.md)). The demo ships one for `INTRO` and `CTRY` only. Nothing writes `corpus/`. A film has one capture of each kind, and a successful `capture-ref` or `capture-video` replaces the old one by swap; `--out` writes anywhere else, replaces nothing and refuses a directory that already holds files. Parity scores a film against its frame capture only while the content hash [`research/parity/references.toml`](../research/parity/references.toml) pins still matches, so promoting a capture is a reviewed commit, and a machine without it, or with a replaced one, fails naming the film ([ADR 0022](adr/0022-captures-are-add-only-beside-a-read-only-corpus.md), [ADR 0028](adr/0028-a-film-has-one-capture-of-each-kind.md)). Retire a worktree the way its tool does, or an older linked one with `mise run reap -- --yes`, which unlinks the junctions before `git worktree remove` runs; `mise run clean -- --yes` only clears outputs of a checkout you are keeping. See [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) and [ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md).

The corpus ships the unpatched 1992 executables; `mise run game-builds` makes an unpatched and a Patch #3 tree under `<data>/builds/`, which `capture-ref`, `play` and `make-all` run with `--game-root`, and a capture records which `PLAYONE.EXE` it ran in `meta.json` ([Build the game builds](howto/build-the-game-builds.md), [`research/playone-exe/patch3.md`](../research/playone-exe/patch3.md)).

---

## Project Structure

| Path | Contents |
| --- | --- |
| `crates/stunt-core/` | Seam contracts, `.RES`/`.ALL`/`.SOD`/`.FLM` parsers, and the `.SOD` bytecode VM |
| `crates/stunt-render/` | `wgpu` pipelines, Mode 13h palette LUT, headless renderer |
| `crates/stunt-parity/` | Parity artifact port: typed render, capture and report documents with a schema version and validation |
| `crates/stunt-cli/` | `stuntreel` binary: interactive/headless presentation plus the `parity` (SSIM/IoU comparator), `export-gltf`, `shape-views` and `sod-trace` subcommands |
| `python/stunt_reel/tac/` | dosbox-automation harness: Lua generator, REST client, capture plans, staging, MAKEONE driver — [`research/playone-exe/capture.md`](../research/playone-exe/capture.md) |
| `crates/stunt-gltf/` | glTF 2.0 (`.glb`) exporter for shapes and single scene frames, driven by `stunt-cli export-gltf` |
| `python/scripts/` | Entry points for capture, parity, format and documentation checks (e.g. `capture_playone_reference.py`, `parity_run.py`, `parity_sweep.py`, `verify_schemas_corpus.py`, `verify_formats_docs.py`) plus maintenance tools |
| `tests/` | Python suite and synthetic fixtures — [`tests/fixtures/README.md`](../tests/fixtures/README.md); Rust integration tests live in `crates/*/tests/it/` (one test binary per crate: add a test as a module in `it/main.rs`, run one with `cargo test -p <crate> --test it -- <module>::`), apart from stunt-render's GPU tests in `tests/gpu/`, which stay a second binary for the hang watchdog |
| `docs/` | Living spec, architecture routing, ADRs, and process documents (`process/`) |
| `manifests/all/` | One committed TOML manifest per film whose `.ALL` `make-all` stored: the game items the archive is rebuilt from, with their hashes ([ADR 0032](adr/0032-a-films-archive-is-committed-as-a-manifest.md)) |
| `research/` | Format specifications beside their `.ksy` layouts plus `PLAYONE.EXE` analysis notes — [`research/formats/INDEX.md`](../research/formats/INDEX.md) |
| `corpus/` | Gitignored demo, full retail install (`stuntisl/`), patches and archive data, kept in the shared data root (`<data root>/corpus/`) and read through `stunt_reel.dataroot`; the checkout's `corpus/` holds only the tracked READMEs — [`corpus/README.md`](../corpus/README.md) |
| `build/` | Gitignored outputs: `build/parity/{ours,report}/` and `build/gltf_output/`; the captures live in the data root, `<data root>/captures/` (ADR 0036); `build/oracle/` holds the synthetic oracle trajectory |
| `tools/dosbox/` | `dosbox-utils.conf`, a by-hand profile for the period utilities — [`tools/dosbox/README.md`](../tools/dosbox/README.md) |

---

## How-to guides

One task per file in [`docs/howto/`](howto/):

- [Play a film in the original player](howto/play-a-film.md)
- [Build the unpatched and Patch #3 game trees](howto/build-the-game-builds.md)
- [Make a film's archive](howto/make-a-films-archive.md) with `MAKEONE.EXE`
- [Score a render change against `PLAYONE`](howto/score-a-render-change.md): capture a reference, render, score and compare
- [Render a film in the native engine](howto/render-a-film.md): interactive, at an interval, or at chosen ticks
- [Export a film to video or glTF](howto/export-a-film.md)
- [Inspect a shape's geometry](howto/inspect-a-shape.md): `sod-trace`, `shape-views`, `shape-diff`
- [Validate the format catalog against the corpus](howto/validate-formats-against-the-corpus.md)
- [Run the GPU tests](howto/run-the-gpu-tests.md) under the hang watchdog
- [Re-gate a branch after a rebase](howto/re-gate-after-a-rebase.md)
- [Take a commit from another session's branch](howto/take-a-commit-from-another-session.md)

---

## Development & Quality Assurance

The gate is `mise run check`: one script ([gate.py](../python/scripts/gate.py), [ADR 0014](adr/0014-the-gate-is-one-ordered-script.md) and [ADR 0016](adr/0016-the-gate-runs-independent-lanes.md)) that prints one line per step, quotes the tail of every failing step, writes the whole output to `target/check.log`, and ends with PASS or FAIL. Independent steps run as concurrent lanes — cargo steps that share a target directory stay in one ordered lane, everything else runs beside them — so one run also reports every failing step, not only the first. `mise run check-rust` and `mise run check-py` run the same step list for one language, and `mise run check-docs` runs only the documentation tests (`test-py-docs`, the modules marked `docs`). A failing run's last line says what to run next: `fix: mise run fix` when a format or `lint-py` step failed, and `re-run: mise run check-rust` / `check-py` / `check-docs` for the half that failed (a scoped run never names itself).

`mise run check` runs only what the branch touches ([ADR 0038](adr/0038-the-local-gate-runs-what-a-change-touches.md)). It reads the paths changed since the merge base with `origin/main` (with `main` when there is no `origin/main`), untracked files included, and sorts each one: `tests/fixtures/**` is other; `crates/**`, `Cargo.toml`, `Cargo.lock`, `deny.toml` and `research/parity/report-fields.md` (a Rust test reads it) are Rust; `*.py`, `pyproject.toml` and `uv.lock` are Python; `*.md` and `*.ksy` are docs; anything else is other. Rust paths run the Rust half, Python paths the Python half, and a run without the Python half adds the docs half. It runs the full gate, and prints why, on `mise run check -- --full`, when `CI` is set, for any other path, when nothing changed, and when git cannot say (neither `origin/main` nor `main`); `-- --base <ref>` counts from another branch. The gate prints its scope and the paths behind it first and, on PASS, the gate line the commit body closes with. CI's `quality` job always runs the full gate. Individual tasks:

| Task | Runs |
| --- | --- |
| `check` / `check-rust` / `check-py` / `check-docs` | `gate.py` over the steps the branch touches (`check`; `-- --full` for every step) or one half (format, lint, strict typing, rustdoc, both test suites, the no-default-features matrix), one line per step, log in `target/check.log` |
| `pre-commit` | what the committed pre-commit hook runs: `prek run --quiet --config prek.toml` over the staged content, printing only the hooks that fail ([ADR 0026](adr/0026-commit-hooks-run-the-gates-own-tasks.md)). A fast subset, not the gate |
| `diff-check` | `git diff --cached --check`: staged conflict markers and whitespace errors; a pre-commit hook |
| `crlf-check` | [check_crlf.py](../python/scripts/check_crlf.py): staged text files whose working copy has CRLF line endings: one that differs from its index blob only in line endings is rewritten from the index (`git checkout-index`) and named as repaired, one with unstaged edits is named and fails the commit, left untouched; `*.bat`, `*.cmd` (`eol=crlf` in `.gitattributes`) and binary files are skipped; a pre-commit hook on every commit |
| `check-work-frozen` | [check_work_frozen.py](../python/scripts/check_work_frozen.py): a staged file added to a frozen work folder (its README has an `outcome` at `HEAD`), or a staged change to that README's `outcome` line ([work/README.md, Lifecycle](../work/README.md#lifecycle)); edits to existing files pass; a pre-commit hook on every commit. `-- --branch` checks the branch since the gate's base instead, which `tests/test_work_frozen.py` runs in the gate |
| `test-py-docs` | every test module marked `docs` (`pytest -m docs`: the documentation invariants, the formats catalog, the schema contract); the docs half of the gate, run by `check-docs` and by a scoped `check` without the Python half |
| `test-docs` | `tests/test_doc_invariants.py` alone: anchors, Markdown links, cited paths, links into dated records only where [`work/README.md`](../work/README.md#links) allows; a pre-commit hook on every commit |
| `check-windows` | the non-GPU half of the gate used by the Windows job on `main` (`fmt-check` + `lint` + `typecheck` + `test`)
| `check-windows-smoke` | the Windows-only slice of the pytest suite, every module marked `windows` (junctions, reparse points, the pytest basetemp workaround, the target seed's build locks), used by the pull-request Windows job; `tests/test_windows_marker.py` fails a module that checks the platform without the marker
| `fmt-check` / `fmt` | `cargo fmt` and `ruff format` check/apply |
| `fix` | every automatic fix the gate's lint and format steps can apply: `ruff check --fix`, `ruff format`, `cargo fmt`. The gate names it when `lint-py`, `fmt-check-py` or `fmt-check-rust` fails; it changes nothing on a clean tree |
| `lint` | `cargo clippy -- -D warnings` and `ruff check .` |
| `typecheck` | `uv run mypy` (strict), once with `--platform win32` and once with `--platform linux` |
| `doc` | rustdoc with `RUSTDOCFLAGS=-D warnings` |
| `check-rust-matrix` | `stunt-core` without the `serde`/`bytemuck` features |
| `test` | `cargo test --workspace --all-features` and `uv run pytest` |
| `fmt-rust`, `fmt-py`, `fmt-check-rust`, `fmt-check-py`, `lint-rust`, `lint-py`, `test-rust`, `test-py` | single-language halves of the tasks above. Arguments after `--` reach the tool, so `mise run test-py -- tests/test_target_seed.py` runs one file |
| `cov-rust` | `cargo llvm-cov` line-coverage summary for `stunt-core` and `stunt-gltf` (not part of `check`) |
| `cov-py` | `pytest` with `--cov=stunt_reel` term-missing report (no fail-under) |
| `deny` | `cargo deny check` — advisories, license allow-list, wildcard bans, and registry sources |
| `capture-digest` | a capture's `sha256` as `references.toml` pins it, and the entry that would promote it (`mise run capture-digest -- vault-ctry`) |
| `capture-ref` | the film's frame capture, `<data root>/captures/<film>/frames`, replaced by swap once a capture succeeds; `--out` writes elsewhere and replaces nothing (`--max-frames` defaults to 2,000) |
| `verify-corpus` | `.ksy` catalog check against `corpus/` |
| `test-corpus` | the Rust tests that read the game files, which `test-rust` skips |
| `play` | play a film in `PLAYONE.EXE` on dosbox-automation |
| `frame` | render a list of film ticks in one process and write each beside its reference capture frame ([Render a film](howto/render-a-film.md#render-chosen-ticks-beside-their-capture)) |
| `shape-diff` | list the shapes whose geometry hash or decode failure changes with a `DBG_*` switch, and draw only those ([Inspect a shape](howto/inspect-a-shape.md#find-the-shapes-a-switch-changes)) |
| `parity-probe`, `verify-docs`, `unlzexe`, `pair-builds`, `xref`, `probe-light`, `flm-events`, `adversarial` | analysis and diagnostic scripts that previously had to be called by file path |

The pre-commit hook is installed by `mise run init` (`core.hooksPath = .githooks`) and holds no command of its own: it runs `mise run pre-commit`, which is [prek](https://github.com/j178/prek) over [`prek.toml`](../prek.toml) ([ADR 0026](adr/0026-commit-hooks-run-the-gates-own-tasks.md)). prek sets unstaged edits aside first, so the hooks check what is being committed. Its local hooks are leaf tasks of `mise.toml` — `diff-check`, `crlf-check` (CRLF in a staged text file's working copy, which `.gitattributes` would normalise away but the format check still reads; repaired when that is the only difference), `test-docs` and `check-work-frozen` (a file added to a frozen work folder, or its outcome changed) on every commit, `fmt-check-rust` when Rust is staged, `fmt-check-py` and `lint-py` when Python is — so they cannot drift from the gate the way the deleted `.pre-commit-config.yaml` did; the rest are prek built-ins (large files, Windows-illegal names, case conflicts, merge conflicts, TOML and YAML syntax, private keys). No hook changes what is committed, and `crlf-check` alone writes a file, one git already sees as unchanged: `mise run fix` (or `mise run fmt`, which only formats) fixes a format failure. It catches what commits most often broke (conflict markers left by a rebase, broken doc links) in seconds; it does not replace `mise run check` before a commit, and CI runs the built-ins on every pull request and push to `main`. Setting `core.hooksPath` turns off untracked hooks in `.git/hooks`, so `.githooks/pre-commit` and `.githooks/pre-push` chain to one there if present, and `init` names any other it turns off. `git commit --no-verify` skips the hook once.

The gate's lanes build the check profile into `target/check` and the no-default-features matrix into `target/matrix`, so those builds can run beside the `target/` build instead of waiting on its lock. All three directories sit under `target/`, which `.gitignore`, ruff's exclude, the recursive walkers and `mise run clean` already cover.

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) invokes the mise tasks instead of restating them. Every pull request runs the full `mise run check` gate on Ubuntu, with Mesa's lavapipe installed and `STUNT_REQUIRE_GPU=1` set so a missing adapter fails the GPU tests instead of skipping them ([ADR 0006](adr/0006-ci-renders-on-lavapipe.md)), and `check-windows-smoke` on Windows for the tests that can behave differently there. Windows gets a smoke test rather than the whole gate on pull requests because every Windows-only behaviour in this repository lives in the Python tree — `crates/` has no `cfg(windows)` — while a warm Windows Rust build costs about nine minutes. Pushes to `main` run the full `check-windows` too (format, lint, typecheck and both test suites; GPU tests skip without a driver), and `workflow_dispatch` runs every job on any branch. A separate job checks the declared MSRV (`1.88`), and a `cargo deny` job enforces the dependency policy; both run on every pull request and push rather than being path-filtered, since the runners are free once the repository is public. The cargo cache falls back to the newest previous lockfile through `restore-keys`, so a dependency bump rebuilds a delta instead of the whole workspace — a cold gate run measured 10m40 against 4m19 warm. Each job installs only the toolchain its task list uses (`rust`, `python`, `uv`, and Java with the Kaitai compiler where `test-py` runs), because `mise run` otherwise installs every tool `mise.toml` declares before its first task — compiling `cargo-deny` and `cargo-llvm-cov` from source and downloading DOSBox inside the gate — so the jobs set `MISE_AUTO_INSTALL=false`. Corpus- and emulator-dependent tasks stay local. A ruleset on `main` requires the four jobs that run on every pull request — `quality`, `windows-smoke`, `msrv` and `deny` — and blocks force pushes and deletion; repository admins may bypass it to push straight to `main`. The full Windows gate runs only on pushes to `main`, so it is not a required check. Actions are pinned to commit SHAs with the release in a trailing comment, and Renovate bumps them ([Dependency updates](#dependency-updates)).

### GPU tests

The `gpu` test binary (`crates/stunt-render/tests/gpu/`, kept apart from the merged `it` binary so the watchdog can run it alone) exercises the Vulkan/DX12/GL loader and vendor driver locks, and a wedge there leaves a plain `cargo test` waiting forever without printing a result; [run it under the watchdog](howto/run-the-gpu-tests.md). Every test in it wraps its body in `common::gpu_test`, which holds one process-wide lock and runs the body on a thread it joins before releasing the lock; opening a renderer outside it panics. The join is the point: a thread that had used NVIDIA's OpenGL driver (`nvoglv64.dll`, reached through the software-only adapter's all-backends instance, or a dropped GL instance's `wgpu-hal WGL Instance Thread`) and exited after the lock was released ran its `DllMain` detach holding the loader lock, and deadlocked against the next test's Vulkan `request_device` loading a DLL (`[Bounded Observation]`: one NVIDIA RTX 4070 laptop, 12 hangs in 150 runs without the join, none in 200 with it). For the same reason a test that builds its own `wgpu::Instance` leaves out `Backends::GL`: wgpu ends the WGL thread after the instance drops, outside any lock. _Source: [2026-11-07: GPU tests hang on an NVIDIA laptop](../work/2026-11/distill-development/journal.md#2026-11-07-gpu-tests-hang-on-an-nvidia-laptop)._

### `stunt-core` test kinds


`stunt-core` tests come in three kinds. Named single inputs with exact expected results go in the `*_spec.rs` and `*_test.rs` files. Never-panics checks over random or mutated bytes are the fixed-seed `XorShift64` loops in the `*_fuzz.rs` files. A property that must hold for every valid input goes in a `*_props.rs` file, or in a `props` module beside the crate-private code it tests: write then read gives back the input, two implementations of one rotation agree, sampling at a keyframe returns that keyframe. These use [proptest](https://docs.rs/proptest), which builds constrained inputs (unit quaternions, timelines with same-tick slices) from composable strategies and shrinks a failure to a minimal case. Each runs 256 cases from a fixed seed, so the gate sees the same cases every run; setting `PROPTEST_CASES=10000` or `PROPTEST_RNG_SEED=<n>` for a `mise run test-rust` explores further without an edit. No regression files are written: when a property fails, add its shrunk input to the matching spec file as a named test, then fix the code or the property.

### Commit messages

The subject is a Conventional Commit, e.g. `feat(core): add a parser`. Write a body whenever a reviewer would have to ask "why this way?": what forced the change, the cause with the offset, measurement or journal entry that proves it, and what you rejected. One paragraph, then a bullet per file when several move together; never retell the diff. Renames, formatting and generated files need none. Longer reasoning belongs in the owning note or an ADR, cited from the body. Close with the gate line a passing `mise run check` prints last, such as `mise run check passes.` or `mise run check-docs passes; check-rust not run; check-py not run.` The commit-msg hook (`mise run commit-msg-check`) checks the subject and the gate line.

### The gate line is checked

A commit body ends with the gate line a passing `mise run check` prints (AGENTS.md, Committing). The commit-msg hook ([check_commit_msg.py](../python/scripts/check_commit_msg.py)) holds each `<name> passes` claim for `check`, `check-rust`, `check-py` or `check-docs` to a run that passed. When a gate run starts, [gate_record.py](../python/scripts/gate_record.py) takes the tree of the working copy, written through a copy of the index so the real one is untouched: every tracked file and every unignored untracked one, as `git add -A` would stage them. When the run passes, it is recorded in `target/gate/<name>.tree` under the task of each half it ran, and under `check` too when it ran both `check-rust` and `check-py`. The hook refuses the line unless the staged tree is the tree a passing run of that name, or of the full `check`, recorded, and it names the paths that differ.

So stage exactly what the gate tested. A commit of some of the changed files, with other edits left in the working copy, is refused, because the gate passed with those edits present. Move them aside (a WIP commit on another branch, or `git stash push -u -m <tag>`) and rerun the gate, or write `not run` for the part you did not run. CI checks the line's wording only (`commit-msg-check -- --range`), since it never saw your run. After a rebase, [re-gate the branch](howto/re-gate-after-a-rebase.md); a commit from another session's branch keeps its author, which the pre-push hook rejects, so [re-commit it](howto/take-a-commit-from-another-session.md).

### Docstrings and doc comments

A Python docstring or Rust `///` comment states the contract a caller needs, in the fewest words that carry it:

- The first line says what the item returns or does, in one sentence.
- Further lines carry only what the signature hides: units and coordinate frame, constraints on inputs, what is raised or returned on failure, side effects (files written, processes started, caches reused), and the anchor, ADR or research note that owns the reasoning.
- Parameters are named inline (*flm*, `data`); their types live in the annotations.
- The why, the history and the alternatives ruled out live in the owning research note or ADR. Code cites a document by its path or a registered anchor token (`[MEM-*]`, `[FMT-*]`, `[I*]`), never by a heading, so rewriting a note's headings breaks no citation.
- Rust keeps the `# Errors` and `# Panics` sections clippy's pedantic lints require, one line per case.

Most land under 60 words. A longer one usually narrates the body; move the narration into a comment beside the code it explains, or drop it.

### Shared tool cache

`mise.toml` points `UV_CACHE_DIR` at the primary checkout's `.cache/uv`, and the cargo tasks' `CARGO_HOME` at its `.cache/cargo`, both by absolute path, so every worktree reuses one set of downloaded crates and uv artifacts with no link. Build outputs (`target/`) and the Python tool caches stay per worktree, because they are revision-specific or not relocatable.

On a ReFS volume, the hidden `ensure` task, which every task that builds Rust runs first, seeds an empty `target/` by cloning another checkout's build output under a lock (`mise run init` and `mise run seed` do it on demand): the clone shares disk blocks with its donor, every dependency arrives fresh, and the workspace crates always rebuild. A new worktree's first Rust lanes take about 40 s instead of 91 s. The donor must sit on the same drive (a clone cannot cross volumes), be built by the same `rustc` against the same `CARGO_HOME`, and not be building; a clippy or matrix lane built otherwise is left out. It prints which donor it used or, when it fails, why it seeded nothing, and warns when `CARGO_HOME` is not the shared cache's own path. See [ADR 0030](adr/0030-new-worktrees-seed-target-by-block-clone.md).

Each worktree keeps uv's own `.venv`; on the cache's volume uv hardlinks the packages out of it, and on another volume (Orca's worktrees on `C:`) it copies them, about 68 MiB and 3 s. Worktrees an older `init` linked still hold a `.venv` junction into `<cache>/venvs/`; `reap` deletes a reaped worktree's environment there and `reap --prune` sweeps those whose checkout is gone. See [ADR 0013](adr/0013-worktrees-share-one-writable-tool-cache.md) and [ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md).

### Running individual commands

For a one-off that no task covers, run the pinned tool through mise: `mise exec -- uv run ruff check python/foo.py`. `mise exec` puts the versions [`mise.toml`](../mise.toml) pins on `PATH`; a bare `uv` can be a different version. `[tool.uv] required-version` in [`pyproject.toml`](../pyproject.toml) is a floor at the pin, not an exact match: an older uv refuses to run, a newer one runs. It cannot be exact because Renovate's `pep621` manager runs its own, newer uv and stops with `tool_version_not_supported` when the project names a different version; raise the floor whenever `mise.toml` raises the pin.

### Python dependencies

The Python half runs on the standard library unless a dependency earns its place. [ADR 0010](adr/0010-python-scripts-may-take-well-established-dependencies.md) holds the bar: wheels on every CI platform, typed, an acceptable licence, and a release within about two years, with the admitting ADR stating the job the dependency does and why the standard library cannot. The shipped `stunt_reel` wheel stays dependency-free; a tooling-only dependency belongs in the dev group, where `python/scripts/` can import it. pydantic, pydantic-settings and Typer were considered for the parity scripts and refused in that ADR.

### Dependency updates

Renovate keeps every ecosystem current — crates, Python dev dependencies, GitHub Actions pinned to commit SHAs, and the tools [`mise.toml`](../mise.toml) pins, which Dependabot could never reach. A dependency bot that cannot touch the toolchain is not managing the most consequential dependency in the tree: a crate bump changes one library, while a `rust` bump changes the compiler that produced every artifact and the verdict in the `msrv` job.

It runs as the Mend-hosted app rather than a self-hosted workflow. The allowed-actions policy admits GitHub-owned actions and the two third-party patterns [`ci.yml`](../.github/workflows/ci.yml) names, so self-hosting would mean admitting a third pattern and keeping a token or App key alive — for a job that is a schedule and an API client. The hosted app costs one file, [`.github/renovate.jsonc`](../.github/renovate.jsonc), and no repository secrets.

The rules that matter operationally:

- **Nothing auto-merges.** `msrv` and `deny` are the only enforcement of the Rust floor and the licence allow-list, and Renovate cannot read either: MSRV filtering for the `crate` datasource is undocumented in practice, and no option exists for a licence allow-list. Every bot PR runs the full gate like any other.
- **Groups split by what a failure implicates.** Patch and minor crate bumps share a PR; majors get their own, because a red `msrv` or `deny` should name one crate rather than hide behind a green action bump. Actions, Python dev dependencies and the mise pins have their own groups.
- **New releases wait three days** (`minimumReleaseAge`), and lock files refresh monthly (`lockFileMaintenance`): a yanked crate or a transitive advisory has no upgrade for `vulnerabilityAlerts` to propose, so the lock file needs a refresh that is not a version bump.
- **Two pins are frozen.** `kaitai_struct_compiler` carries a `sha256` of its release zip and the dosbox-automation entry names an `asset_pattern` and a `checksum`; for those a version bump alone installs nothing, and no gate run on any platform would catch it.
- **Security fixes still arrive.** Dependabot's alerts stay on and Renovate raises the fix PRs from them; Dependabot's own version and security updates are off, so one bot writes lock files and one raises advisories.

Three conventions keep the pins honest. A **pin** is what gets installed ([`mise.toml`](../mise.toml) `[tools]`, [`rust-toolchain.toml`](../rust-toolchain.toml)), and only a pin may move automatically. A **floor** is the minimum the project claims (`rust-version = "1.88"`, `requires-python = ">=3.15"`), and moving one is a deliberate act after `msrv` proves it. A **target** is what ruff and mypy assume, which Renovate cannot see, so a pin moves only when its targets move with it (mypy's target equals the pin; ruff's may trail it by one minor between an upgrade PR and its apply-ruff PR). The **interpreter** the gate runs on is the pin's minor: `python-preference` keeps uv on the Python mise puts on PATH, and only a `uv` run outside `mise` against a different PATH interpreter drifts from it. [`tests/test_toolchain_pins.py`](../tests/test_toolchain_pins.py) fails the gate if a pin, a floor, a target and the running interpreter drift apart — and that test is what lets the compiler stay declared in two files at all: `rust-toolchain.toml` resolves (rustup reports the active toolchain overridden by it) while `mise.toml` installs, so the two are one Renovate group and the test proves them equal.
