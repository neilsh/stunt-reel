# Development guide

Setup, project layout and the quick task map for working on `stunt-reel`; the gate, CI and toolchain references are on their pages, and each task's commands are a [how-to guide](#how-to-guides).
The project overview is in the [README](../README.md); contributor and agent rules are in [`AGENTS.md`](../AGENTS.md).

## Requirements

- **[mise](https://mise.jdx.dev/)** (recommended environment and tool manager)
- **[Rust](https://www.rust-lang.org/)** 2024 edition (MSRV 1.100; the pinned toolchain is 1.100.0), managed via `mise` or `rustup`
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

Pinned versions live in [`mise.toml`](../mise.toml); `mise run init` runs `uv sync`, which installs the `kaitaistruct==0.11` runtime for the schema checks.
It also points git's `core.hooksPath` at the committed [`.githooks/`](../.githooks/), whose pre-commit hook runs `mise run pre-commit` (see [quality gate](quality-gate.md)).

> [!NOTE]
> The quality gate (`mise run check`) runs on Linux, macOS and Windows.
> Capture, parity and corpus workflows are Windows + dosbox-automation + local-corpus only; elsewhere you can still build, test and render from synthetic fixtures.

### 2. dosbox-automation

`mise install` puts `dosbox` on the `mise` path; `capture-ref`, `make-all` and `play` find it through `mise exec` (or `DOSBOX_AUTOMATION_EXE`).
Nothing is registered with an agent: each run stages a mount and a conf under the data root (`<data>/stage/<film>-<label>/`), starts the emulator on a free web-server port with a random bearer token passed in the environment, and talks to it over REST.
A capture is a plan, a trace pass and a dump pass of Lua that Python checks against each other ([ADR 0025](adr/0025-capture-runs-are-plans-not-sessions.md)), so two runs never collide.

### 3. Worktrees and the shared data root

Several agents can work at once, each in its own `git worktree` under the primary checkout's gitignored `.claude/worktrees/` or `.agents/worktrees/`, where `mise run reap` looks for merged worktrees; one candidate with modified or untracked files stops the whole batch unless `--stash-dirty` or `--discard-untracked` allows it.
The game files and the captures are gitignored, so they live once per machine instead of once per checkout:

```text
<parent-of-checkout>\stunt-reel.data\   corpus\{stisldem,siarchive,stuntisl,patches}, captures\<film>\{frames,video,archives}\
```

Code reads them there through `stunt_reel.dataroot` (`data_root()`, `corpus_root()`, `resolve_data_path()`), so a worktree holds no link and needs no setup step; a `--film corpus/...` argument resolves against the data root too, and a clone that keeps its game files in its own `corpus/` is read there only when `STUNT_DATA_ROOT` is unset, the data root has no `corpus/` directory at all (an empty one still wins), and the primary checkout's `corpus/` holds a folder of game files ([ADR 0036](adr/0036-worktrees-reach-shared-state-by-configuration.md)).
Build outputs, the Python tool caches and `.venv` stay per worktree (see [Shared tool cache](toolchain.md#shared-tool-cache)).
`STUNT_DATA_ROOT` names a different data root, and `mise run init -- --migrate` first converts an old-layout data root (`stisldem`, `si_archive`, `oracle`, `target_bin`, `reference`) to the layout above, refusing a root that holds both old and new names, then moves an existing in-checkout `corpus/` into it.
Worktrees an older `init` linked keep their junctions until reaped: `reap` finds them as reparse points and unlinks them, and `LINK_TARGETS` in `python/stunt_reel/dataroot.py` names the old paths for `init`'s report and `--migrate`.

A film needs an `.ALL` to be captured: one beside its `.FLM`, one rebuilt from the film's committed manifest under `manifests/all/`, or one that `make-all` stored under `captures/<film>/archives/` ([Make a film's archive](howto/make-a-films-archive.md)).
The demo ships one for `INTRO` and `CTRY` only, and a film whose `references.toml` row pins `makeone = "patch3"` refuses the shipped unpatched one.
Nothing writes `corpus/`.
A film has one capture of each kind, and a successful `capture-ref` or `capture-video` replaces the old one by swap; `--out` writes anywhere else, replaces nothing and refuses a directory that already holds files.
Parity scores a film against its frame capture only while the content hash [`research/parity/references.toml`](../research/parity/references.toml) pins still matches, so promoting a capture is a reviewed commit, and a machine without it, or with a replaced one, fails naming the film ([ADR 0022](adr/0022-captures-are-add-only-beside-a-read-only-corpus.md), [ADR 0028](adr/0028-a-film-has-one-capture-of-each-kind.md)).
Retire a worktree the way its tool does, or an older linked one with `mise run reap -- --yes`, which unlinks the junctions before `git worktree remove` runs; `mise run clean -- --yes` only clears outputs of a checkout you are keeping.
See [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) and [ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md).

The corpus ships the unpatched 1992 executables; `mise run game-builds` makes an unpatched and a Patch #3 tree under `<data>/builds/`, which `capture-ref` and `make-all` pick by default (the build the film's `references.toml` row names, else `patch3`) and `play` runs with `--game-root`, and a capture records which `PLAYONE.EXE` it ran in `meta.json` ([Build the game builds](howto/build-the-game-builds.md), [`research/playone-exe/patch3.md`](../research/playone-exe/patch3.md)).

---

## Project Structure

| Path | Contents |
| --- | --- |
| `crates/stunt-core/` | Seam contracts, `.RES`/`.ALL`/`.SOD`/`.FLM` parsers, and the `.SOD` bytecode VM |
| `crates/stunt-render/` | `wgpu` pipelines, Mode 13h palette LUT, headless renderer |
| `crates/stunt-parity/` | Parity artifact port: typed, versioned, validated render, capture, video and report documents, and their committed JSON Schemas in `schema/`, which the Python adapter is tested against ([ADR 0048](adr/0048-the-python-parity-adapter-is-checked-against-a-generated-schema.md)); the [crate docs](../crates/stunt-parity/src/lib.rs) say how to regenerate them |
| `crates/stunt-cli/` | `stuntreel` binary: interactive/headless presentation plus the `parity`, `export-gltf`, `shape-views`, `sod-trace` and `film-slots` subcommands |
| `crates/stunt-score/` | The parity engine as a library, with no GPU dependency: SSIM/IoU scoring, the render store, the render and capture documents' reader and writer, and the ZMBV/AVI video reader; `stuntreel parity` calls it |
| `python/stunt_reel/tac/` | dosbox-automation harness: Lua generator, REST client, capture plans, staging, MAKEONE driver — [`research/playone-exe/capture.md`](../research/playone-exe/capture.md) |
| `crates/stunt-gltf/` | glTF 2.0 (`.glb`) exporter for shapes and single scene frames, driven by `stunt-cli export-gltf` |
| `python/scripts/` | Entry points for capture, parity, format and documentation checks (e.g. `capture_playone_reference.py`, `parity_run.py`, `parity_sweep.py`, `verify_schemas_corpus.py`, `verify_formats_docs.py`) plus maintenance tools |
| `tests/` | Python suite and synthetic fixtures — [`tests/fixtures/README.md`](../tests/fixtures/README.md); Rust integration tests live in `crates/*/tests/it/` (one test binary per crate: add a test as a module in `it/main.rs`, run one with `cargo test -p <crate> --test it -- <module>::`), apart from stunt-render's GPU tests in `tests/gpu/`, which stay a second binary so the hang-rate loop can run them alone |
| `docs/` | Living spec, architecture routing, ADRs, and guides (`howto/`, `agents/`) |
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
- [Run the GPU tests](howto/run-the-gpu-tests.md) under the per-test hang deadline
- [Render on lavapipe beside a GPU](howto/render-on-lavapipe.md): name the mesa-dist-win ICD and pass `--software-only`
- [Run the class agreement batch](howto/run-the-agreement-batch.md): measure and pin where lavapipe and the GPU differ
- [Measure a headless render's memory](howto/measure-a-renders-memory.md): `--report-memory` prints the stage and peak resident set
- [Take a commit from another session's branch](howto/take-a-commit-from-another-session.md)

---

## Development & Quality Assurance

The gate script, its step list, the pre-commit hook, its lanes and CI are in [quality gate](quality-gate.md).

| Task | Runs |
| --- | --- |
| `check` / `check-rust` / `check-py` / `check-docs` | `gate.py` over the steps the branch touches (`check`; `-- --full` for every step) or one half (format, lint, module layers, strict typing, rustdoc, both test suites, the no-default-features matrix), one line per step, log in `target/check.log` |
| `pre-commit` | what the committed pre-commit hook runs: `prek run --quiet --config prek.toml` over the staged content, printing only the hooks that fail ([ADR 0026](adr/0026-commit-hooks-run-the-gates-own-tasks.md)). A fast subset, not the gate |
| `check-work-frozen` | [check_work_frozen.py](../python/scripts/check_work_frozen.py): a staged file added to a frozen work folder (its README has an `outcome` at the merge base of `HEAD` and the gate's base, `HEAD` when no base resolves), or a staged change to that README's `outcome` line ([work/README.md, Lifecycle](../work/README.md#lifecycle)); edits to existing files pass; a pre-commit hook on every commit. `-- --branch` checks the branch since the gate's base instead, which `tests/test_work_frozen.py` runs in the gate |
| `test-py-docs` | every test module marked `docs` (`pytest -m docs`: the documentation invariants, the formats catalog, the schema contract); the docs half of the gate, run by `check-docs` and by a scoped `check` without the Python half |
| `test-docs` | `tests/test_doc_invariants.py` alone: anchors, Markdown links, cited paths, links into dated records only where [`work/README.md`](../work/README.md#links) allows; a pre-commit hook on every commit |
| `claim-words` | [claim_words.py](../python/scripts/claim_words.py): each line the branch adds under an [AGENTS.md rule 5](../AGENTS.md#committing) path that holds one of that rule's over-broad words as a whole word, with the line and its nearest evidentiary tier tag; advisory, exits 0 whatever it finds, so each hit is a line to narrow or justify (`mise run claim-words -- [<base>]`) |
| `check-windows` | the non-GPU half of the gate used by the Windows job on `main` (`fmt-check` + `lint` + `check-layers` + `typecheck` + `test`)
| `check-windows-smoke` | the Windows-only slice of the pytest suite, every module marked `windows` (junctions, reparse points, the pytest basetemp workaround, the target seed's build locks, and tach's module layers), used by the pull-request Windows job; `tests/test_windows_marker.py` fails a module that checks the platform without the marker
| `fmt-check` / `fmt` | `cargo fmt` and `ruff format` check/apply |
| `fix` | every automatic fix the gate's lint and format steps can apply: `ruff check --fix`, `ruff format`, `cargo fmt`. The gate names it when `lint-py`, `fmt-check-py` or `fmt-check-rust` fails; it changes nothing on a clean tree |
| `lint` | `cargo clippy -- -D warnings` and `ruff check .` |
| `check-layers` | `uv run tach check`: the module layers of `python/stunt_reel/` and the scripts above them, as [`tach.toml`](../tach.toml) states them ([ADR 0050](adr/0050-the-python-packages-module-layers-are-checked-by-tach.md)); a step of `check-py` |
| `typecheck` | `uv run mypy` (strict), once with `--platform win32` and once with `--platform linux` |
| `doc` | rustdoc with `RUSTDOCFLAGS=-D warnings` |
| `check-rust-matrix` | `stunt-core` without the `serde`/`bytemuck` features |
| `test` | `cargo test --workspace --all-features` and `uv run pytest` |
| `fmt-rust`, `fmt-py`, `fmt-check-rust`, `fmt-check-py`, `lint-rust`, `lint-py`, `test-rust`, `test-py` | single-language halves of the tasks above. Arguments after `--` reach the tool, so `mise run test-py -- tests/test_target_seed.py` runs one file |
| `cov-rust` | `cargo llvm-cov` test coverage (line and region) of the whole Rust workspace, GPU tests included; prints a summary and writes `target/coverage/lcov.info`; not part of `check`, run by the CI `coverage` job |
| `cov-py` | `pytest` with coverage.py over `python/stunt_reel` and `python/scripts` (lines and branches, subprocesses included, [`[tool.coverage]`](../pyproject.toml)); prints a term-missing report and writes `target/coverage/coverage.xml` and `coverage.json`; no fail-under; run by the CI `coverage` job |
| `cov-summary` | the Rust table (a row per crate) and the Python table (a row per package) from the files `cov-rust` and `cov-py` wrote, as Markdown (the CI job's summary) |
| `deny` | `cargo deny check` — advisories, license allow-list, wildcard bans, and registry sources |
| `capture-digest` | a capture's `sha256` as `references.toml` pins it, and the entry that would promote it (`mise run capture-digest -- vault-ctry`) |
| `capture-compare` | two frame captures of one film compared page by page, paired by exact `film_tick`: identical pages, median and p90 differing pixels, equal palettes (`mise run capture-compare -- A B`) |
| `capture-ref` | the film's frame capture, `<data root>/captures/<film>/frames`, replaced by swap once a capture succeeds; `--out` writes elsewhere and replaces nothing (`--max-frames` defaults to 2,000) |
| `stub-sound-samples` | write a copy of a `.ALL` with every sound sample stubbed, as captures play it, and print both hashes (`mise run stub-sound-samples -- IN.ALL -o OUT.ALL [--sound-ids-from OWN.ALL]`) |
| `verify-corpus` | `.ksy` catalog check against `corpus/` |
| `test-corpus` | the Rust tests that read the game files, which `test-rust` skips |
| `play` | play a film in `PLAYONE.EXE` on dosbox-automation |
| `frame` | render a list of film ticks in one process and write each beside its reference capture frame ([Render a film](howto/render-a-film.md#render-chosen-ticks-beside-their-capture)) |
| `shape-diff` | list the shapes whose geometry hash or decode failure changes with a `DBG_*` switch, and draw only those ([Inspect a shape](howto/inspect-a-shape.md#find-the-shapes-a-switch-changes)) |
| `parity-residue` | differing index-plane pixels between two render-store trees of `<film>_current` stores, film by film: ticks compared and differing, mean differing pixels per tick, the largest and its tick, and with `--ticks` the count at each named tick under the film that holds it, a tick no store holds going to stderr instead (`mise run parity-residue -- <render root A> <render root B> [--films f1,f2] [--ticks t1,t2]`) |
| `parity-probe`, `verify-docs`, `unlzexe`, `pair-builds`, `re-tool`, `flm-events`, `adversarial` | analysis and diagnostic scripts |

The quality gate page also holds [the GPU tests' hang rationale](quality-gate.md#gpu-tests), [the Windows `PermissionError` investigation](quality-gate.md#a-permissionerror-on-windows) with its ruled-out causes, and [the `stunt-core` spec, fuzz and props test kinds](quality-gate.md#stunt-core-test-kinds).
The toolchain page holds [the shared tool cache and target seeding](toolchain.md#shared-tool-cache), [running a tool outside a task](toolchain.md#running-individual-commands), [the Python dependency bar](toolchain.md#python-dependencies), and [Renovate with the pin, floor and target conventions](toolchain.md#dependency-updates).

### Commit messages

The subject is a Conventional Commit, e.g. `feat(core): add a parser`.
Write a body whenever a reviewer would have to ask "why this way?": what forced the change, the cause with the offset, measurement or journal entry that proves it, and what you rejected.
One paragraph, then a bullet per file when several move together; never retell the diff.
Renames, formatting and generated files need none.
Longer reasoning belongs in the owning note or an ADR, cited from the body.
The commit-msg hook (`mise run commit-msg-check`) checks the subject and, on a commit that changes a work `spec.md` or `plan.md`, the `Fresh-review:` trailer that [AGENTS.md § Committing](../AGENTS.md#committing) rule 5 asks for; a pull request's required checks, not the message, prove the full gate on the branch tip ([ADR 0044](adr/0044-commit-messages-carry-no-gate-line.md)), or only its docs half for a docs-only pull request ([ADR 0047](adr/0047-ci-scopes-a-docs-only-pull-request.md)).
A commit from another session's branch keeps its author, which the pre-push hook rejects, so [re-commit it](howto/take-a-commit-from-another-session.md).

A pull request's title becomes its squash commit's subject, so it is a Conventional Commit too, ending with the issue or issues it serves: `fix(parity): repin the reference films (#305)`, or `(#305, 2/2)` for one PR of a stack.
GitHub appends the PR's own `(#N)` on merge, so leave it out of the title; a PR that serves no issue names none.
The `PR title` workflow checks the title with the commit-msg hook's own subject rule and re-runs when the title is edited; CI checks no pull request's individual commit messages, so only the local hook sees those.
The repository owner turns off rebase merging and sets squash merges' title to "Pull request title", so the checked title is the one that lands ([ADR 0026](adr/0026-commit-hooks-run-the-gates-own-tasks.md#amendment-2026-11-15-ci-checks-the-pull-request-title)).

### Docstrings and doc comments

A Python docstring or Rust `///` comment states the contract a caller needs, in the fewest words that carry it:

- The first line says what the item returns or does, in one sentence.
- Further lines carry only what the signature hides: units and coordinate frame, constraints on inputs, what is raised or returned on failure, side effects (files written, processes started, caches reused), and the anchor, ADR or research note that owns the reasoning.
- Parameters are named inline (*flm*, `data`); their types live in the annotations.
- The why, the history and the alternatives ruled out live in the owning research note or ADR.
  Code cites a document by its path or a registered anchor token (`[MEM-*]`, `[FMT-*]`, `[I*]`), never by a heading, so rewriting a note's headings breaks no citation.
- Rust keeps the `# Errors` and `# Panics` sections clippy's pedantic lints require, one line per case.

Most land under 60 words.
A longer one usually narrates the body; move the narration into a comment beside the code it explains, or drop it.

### Markdown line breaks

Start each sentence on its own line.
Never break inside inline math, or inside a link or code span: the link checker reads those only to a line end.
Exceptions and why: [ADR 0051](adr/0051-markdown-breaks-lines-at-sentences.md).
