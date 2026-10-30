# Development guide

Setup, workflows and the quality gate for working on `stunt-reel`. The project overview is in the [README](../README.md); contributor and agent rules are in [`AGENTS.md`](../AGENTS.md).

## Requirements

- **[mise](https://mise.jdx.dev/)** (recommended environment and tool manager)
- **[Rust](https://www.rust-lang.org/)** 2024 edition (MSRV 1.88; the pinned toolchain is 1.99.1), managed via `mise` or `rustup`
- **[uv](https://docs.astral.sh/uv/)** (installed by `mise`, which pins the exact version; `required-version` in [`pyproject.toml`](../pyproject.toml) refuses a standalone uv older than that pin) and **Python ≥ 3.11**
- **[ffmpeg](https://ffmpeg.org/)** on `PATH` (only for `--video` export)
- **[DOSBox-X](https://dosbox-x.com/) `2026.10.01`** (Windows x64 portable SDL2 build, installed by `mise`)
- **[`dosbox-x-mcp-server`](https://github.com/caiiiycuk/dosbox-x-mcp-server) `0.1.2`** (managed via `mise`)
- **Java 21 (Temurin)** and **Kaitai Struct Compiler `0.11`** (managed via `mise`; needed only for the `.ksy` corpus checks)

---

## Setup

### 1. mise

```powershell
mise trust     # once per fresh clone, if mise asks you to trust the config
mise install   # pinned toolchains, DOSBox-X, Kaitai compiler
mise run init  # link the shared data root and cached environment, then uv sync
```

Pinned versions live in [`mise.toml`](../mise.toml); `mise run init` links the shared cache and then runs `uv sync`, which installs the `kaitaistruct==0.11` runtime for the schema checks.

> [!NOTE]
> The quality gate (`mise run check`) runs on Linux, macOS and Windows. Capture, parity and corpus workflows are Windows + DOSBox-X + local-corpus only; elsewhere you can still build, test and render from synthetic fixtures.

### 2. DOSBox-X debugger over MCP (optional)

Only needed to inspect the original player live from an MCP-capable AI coding agent; building, testing, rendering and the parity loop do not use it.

```powershell
mise run mcp                    # launch dosbox-x-mcp-server over stdio; it reports its port through dosbox_mcp_port
mise run ensure-dosbox -- --mcp-port <port>   # start DOSBox-X dialling that port (once per debugger session)
```

Register the server in your agent's MCP configuration (the file and key names depend on the agent) and make sure `dosbox-x-mcp-server` is on `PATH`. A typical entry:

```json
{
  "mcpServers": {
    "dosbox-x": {
      "command": "dosbox-x-mcp-server",
      "args": []
    }
  }
}
```

> [!NOTE]
> DOSBox-X always dials *out*; it never listens. A profile carries no port: `mise run capture-ref` binds port 0, passes the port the OS gave it with `-set "dosbox mcp_server=<port>"`, and two captures therefore never collide ([ADR 0021](adr/0021-capture-chooses-its-control-port.md)). For the interactive debugger, ask the MCP server for `dosbox_mcp_port` and pass it to `mise run ensure-dosbox -- --mcp-port <port>`.

### 3. Worktrees and the shared data root

Several agents can work at once, each in its own `git worktree`: beside the checkout (`<checkout>.wt\<slug>` on Windows) or under a gitignored directory inside it (`.claude/worktrees/`, `.agents/worktrees/`). The game files and the captures are gitignored, so they live once per machine instead of once per checkout:

```text
<parent-of-checkout>\stunt-reel.data\   corpus\{stisldem,siarchive,stuntisl,patches}, captures\<film>\<capture id>\
```

Each corpus folder is its own link, because `corpus/README.md` and `corpus/siarchive.md` are tracked and `corpus/` cannot itself be one; `captures\` is linked as `build/parity/captures/`. `LINK_TARGETS` in `python/stunt_reel/dataroot.py` is the one place that names them.

`mise run init` links those into a worktree with junctions, so the relative `corpus/` and `build/parity/captures/` paths work unchanged; build outputs and the Python tool caches stay per worktree, while the virtualenv lives in the shared cache (see [Shared tool cache](#shared-tool-cache), and [ADR 0019](adr/0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md)). `STUNT_DATA_ROOT` names a different data root, and `mise run init -- --migrate` first converts an old-layout data root (`stisldem`, `si_archive`, `oracle`, `target_bin`, `reference`) to the layout above, refusing a root that holds both old and new names, then moves an existing in-checkout `corpus/` into it: plain `mise run init` refuses a checkout that already holds data rather than linking only the paths that are still empty. A sandboxed agent session cannot create those junctions under `workspace-write`, because their targets are outside the workspace; provision the worktree with one run at wider file access — see [docs/harness-setup.md](harness-setup.md).

A film needs its `.ALL` beside its `.FLM` to be captured. The demo ships one for `INTRO` and `CTRY` only; for any other film run `mise run make-all -- --film <path>.FLM` once (about 90 s or more: `MAKEONE.EXE` plays the film in real time in DOSBox-X), which stores the archive under `captures/all/<film>/<id>/`, and `capture-ref` then finds it by the film's hash ([ADR 0023](adr/0023-make-all-generates-archives-with-makeone.md), [`research/makeone-exe/driving.md`](../research/makeone-exe/driving.md)). Nothing writes `corpus/`, and a capture adds a new directory under `captures/` and never changes one; `mise run capture-ref` refuses an `--out` that already holds files. Parity scores a film against the capture [`research/parity/references.toml`](../research/parity/references.toml) names by id and content hash, so promoting a capture is a reviewed commit, and a machine without that capture fails with its id ([ADR 0022](adr/0022-captures-are-add-only-beside-a-read-only-corpus.md)). Retire a worktree with `mise run reap -- --yes`, which unlinks the junctions before `git worktree remove` runs; `mise run clean -- --yes` only clears outputs of a checkout you are keeping. See [ADR 0008](adr/0008-worktrees-share-one-read-only-data-root.md) and [ADR 0018](adr/0018-reaping-unlinks-the-data-root-links-first.md).

---

## Project Structure

| Path | Contents |
| --- | --- |
| `crates/stunt-core/` | Seam contracts, `.RES`/`.ALL`/`.SOD`/`.FLM` parsers, and the `.SOD` bytecode VM |
| `crates/stunt-render/` | `wgpu` pipelines, Mode 13h palette LUT, headless renderer, SSIM/IoU comparator |
| `crates/stunt-parity/` | Parity artifact port: typed render, capture and report documents with a schema version and validation |
| `crates/stunt-cli/` | `stuntreel` binary: interactive/headless presentation plus the `parity` and `export-gltf` subcommands |
| `python/stunt_reel/tac/` | DOSBox-X TAC harness: control transport, BIOS Data Area input, frame capture — [`research/playone-exe/capture.md`](../research/playone-exe/capture.md) |
| `crates/stunt-gltf/` | glTF 2.0 (`.glb`) exporter for shapes and single scene frames, driven by `stunt-cli export-gltf` |
| `python/scripts/` | Entry points for capture, parity, format and documentation checks (e.g. `capture_playone_reference.py`, `parity_run.py`, `parity_sweep.py`, `verify_schemas_corpus.py`, `verify_formats_docs.py`) plus maintenance tools |
| `tests/` | Python suite and synthetic fixtures — [`tests/fixtures/README.md`](../tests/fixtures/README.md); Rust integration tests live in `crates/*/tests/` |
| `docs/` | Living spec, architecture routing, ADRs, and process documents (`process/`) |
| `research/` | Format specifications beside their `.ksy` layouts plus `PLAYONE.EXE` analysis notes — [`research/formats/INDEX.md`](../research/formats/INDEX.md) |
| `corpus/` | Gitignored demo, full retail install (`stuntisl/`), patches and archive data, linked from the shared data root — [`corpus/README.md`](../corpus/README.md) |
| `build/` | Gitignored outputs: `build/parity/{ours,report}/` and `build/gltf_output/`; `build/parity/captures/` borrows the shared captures; `build/oracle/` holds the synthetic oracle trajectory |
| `tools/dosbox/` | DOSBox-X configs (`dosbox-playone.conf` interactive play, `dosbox-parity.conf` capture, `dosbox-mcp.conf` agent debugger, `dosbox-utils.conf` period tools) and `play_ctry.bat`, a launcher for `mise run play` — [`tools/dosbox/README.md`](../tools/dosbox/README.md) |

---

## Workflows

### Play a film in the original player

```powershell
mise run play        # or: .	ools\dosbox\play_ctry.bat
```

`tools/dosbox/dosbox-playone.conf` mounts `corpus/stisldem`, launches `PLAYONE.EXE`, and queues the autotype sequence that selects `CTRY.FLM`.

### Capture reference frames and score a render

```bash
mise run capture-ref
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --frames 1..1344 \
    --sidata corpus/siarchive/Developer/FreeFlight/SIDATA \
    --out-dir build/parity/ours/ctry --width 320 --height 200 --viewport-rows 185
cargo run -p stunt-cli -- parity --reference build/parity/captures/ctry/<id> \
    --test build/parity/ours/ctry --output build/parity/report/ctry
# after a change: re-render, then score against the previous report (before/after sheets need its render dir)
cargo run -p stunt-cli -- parity --reference build/parity/captures/ctry/<id>     --test build/parity/ours/ctry --output build/parity/report/ctry_new     --compare build/parity/report/ctry/report.json --compare-test build/parity/ours/ctry_prev
```

`capture-ref` stores 140 reference frames, each tagged in `meta.json` with the film clock (`film_tick`) it was captured at. `--frames 1..1344` (also the default range) renders ticks 0 through 1,342, the film's last tick included, as `tick_00000.png`–`tick_01342.png`, named by 0-based 50 Hz tick (the end-hold captures sit at tick 1,342), plus `render.json` (typed, written last: film identity, raster geometry, and each tick's palette variables and camera); parity reads it and falls back to the legacy `palette_controls.json` that older renders still carry. The comparator pairs each capture with the render at its `film_tick` (captures made before film-clock tagging must be recaptured). The comparator writes `report.json` (per-frame `ssim`/`iou`, `fade_level`, `scored`; run-level `sky_indices`, `unmatched`, `mean_ssim`, `min_ssim`, `mean_iou`, `mean_ssim_scored`, `mean_iou_scored`, `min_fade_level`, `scored_frames`, `excluded_frames`) and `contact_NNNN.png` sheets under `build/parity/report/ctry/`. `--min-fade-level <F>` (default 0.25) sets the floor for the end-of-film palette fade: the film's authored brightness decides whether a frame is scored and the measured level stays a cross-check, frames below the floor are reported but not scored, and the headline is `mean_ssim_scored` with its scored-frame count (see [`research/parity/method.md`](../research/parity/method.md#21-fade-floor)).

`--compare <report.json>` pairs the fresh scores with a previous report by `film_tick` and prints mean SSIM/IoU before → after over the frames present in both, the 5 most improved and 5 most regressed frames, and how many frames moved by more than 0.005; it also writes `compare.json`. The basis is `scored` (SSIM over frames scored in both runs) when both reports carry `scored`, and `all` (SSIM over all common frames) for older reports; the first `[compare]` line states which. With `--compare-test <dir>` (the previous run's render directory) it writes `compare_regressed_tick_NNNNN.png` and `compare_improved_tick_NNNNN.png` (`reference | before | after | |ref−before| | |ref−after|`) for the single biggest mover each way. The method and a dated results table are in [`research/parity/method.md`](../research/parity/method.md) and [`research/parity/log.md`](../research/parity/log.md).

Prerequisites: `corpus/stisldem/VAULT/CTRY.FLM` and `CTRY.ALL`. No port needs to be free. How the dialog is driven (BIOS Data Area keystrokes) and how frames are sampled (post-retrace breakpoint at `0D51:0C5E`) is recorded in [`method.md`](../research/parity/method.md#1-the-loop) and [`research/playone-exe/capture.md`](../research/playone-exe/capture.md).

### Render in the native engine

```powershell
cargo run -p stunt-cli -- corpus/stisldem/VAULT/CTRY.FLM --all corpus/stisldem/VAULT/CTRY.ALL
```

Opens the interactive presentation (Space pauses, C toggles authored/free camera, WASD/QE fly the free camera, Esc exits). Interactive playback follows the authored 50 Hz timeline and interpolates between slices. `--help` lists the headless flags, `--frames <A..B>` (half-open, 1-based 50 Hz tick ordinals), `--ticks`, and the `parity` subcommand. `ANCHORPT.DAT`, `MAP.BIN`, and `SCENERY.scn` are searched for in `--sidata <dir>` first, then the archive's directory, its parent and grandparent, then `sidata/` or `SIDATA/` inside the parent (filename case ignored); the demo's `corpus/siarchive/Developer/FreeFlight/SIDATA` needs an explicit `--sidata`.

### Export a film to video container

```powershell
# Export film sequence to an MP4 video sampled at 30 fps
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --video build/ctry.mp4
```

Export a shape, or one frame of a film, to glTF 2.0 for viewing in Blender or any glTF viewer:

```powershell
cargo run -p stunt-cli -- export-gltf --archive corpus/stisldem/VAULT/CTRY.ALL \
    --film corpus/stisldem/VAULT/CTRY.FLM --tick 400 --out build/gltf_output/CTRY_t400.glb
cargo run -p stunt-cli -- export-gltf --archive corpus/stisldem/VAULT/CTRY.ALL --shape 0x0408 --out build/gltf_output/shape.glb
```

Headless video export samples the authored 50 Hz timeline at `--fps` (default 30), interpolates between slices, and encodes directly into a standard video container (`.mp4`, `.webm`, `.mkv`, or `.avi`) via `ffmpeg`, with physical $4:3$ aspect ratio correction ($320 \times 240$, `[I6]`). `--frames <A..B>` limits the export to a half-open range of 1-based tick ordinals. `CTRY.FLM` spans 1,342 ticks (26.84 s), producing 806 sampled frames at 30 fps; the container is trimmed to the authored span, so ffmpeg encodes 805 frames and ffprobe reports 26.833 s (nearest whole frame; 26.84 s exactly at `--fps 50`). Requires `ffmpeg` on `PATH`.

### Interval-based frame capture for rapid audits

```powershell
# Capture one frame every 25 ticks (0.5 s) across the full 1,342-tick film
cargo run -p stunt-cli -- --headless corpus/stisldem/VAULT/CTRY.FLM \
    --all corpus/stisldem/VAULT/CTRY.ALL --frames 1..1343 --frame-step 25 \
    --out-dir build/parity/ours/ctry_sparse
```

`--frames` uses 1-based 50 Hz tick ordinals; `--frame-step <N>` extracts every Nth tick, saving frames named by 0-based tick (`tick_00000.png`, `tick_00025.png`, etc.) without redundant disk consumption. `--sample-count <N>` writes `sample_0001.png`… (1-based sample index) instead; those are not parity inputs.

### Validate the format catalog against a local corpus

```powershell
mise run verify-corpus              # report anomalies
mise run verify-corpus -- --strict  # fail on them
```

Compiles `research/formats/**/*.ksy` and checks documented headers, offsets, and opcodes against `corpus/`. Local-only: `corpus/` is gitignored and absent in CI.

---

## Development & Quality Assurance

The gate is `mise run check`: one script ([gate.py](../python/scripts/gate.py), [ADR 0014](adr/0014-the-gate-is-one-ordered-script.md) and [ADR 0016](adr/0016-the-gate-runs-independent-lanes.md)) that prints one line per step, quotes the tail of every failing step, writes the whole output to `target/check.log`, and ends with PASS or FAIL. Independent steps run as concurrent lanes — cargo steps that share a target directory stay in one ordered lane, everything else runs beside them — so one run also reports every failing step, not only the first. `mise run check-rust` and `mise run check-py` run the same step list for one language. Individual tasks:

| Task | Runs |
| --- | --- |
| `check` / `check-rust` / `check-py` | `gate.py` over every step (format, lint, strict typing, rustdoc, both test suites, the no-default-features matrix), one line per step, log in `target/check.log` |
| `check-windows` | the non-GPU half of the gate used by the Windows job on `main` (`fmt-check` + `lint` + `typecheck` + `test`)
| `check-windows-smoke` | the Windows-only slice of the pytest suite (junctions, reparse points, the `.cache` link, the pytest basetemp workaround), used by the pull-request Windows job
| `fmt-check` / `fmt` | `cargo fmt` and `ruff format` check/apply |
| `lint` | `cargo clippy -- -D warnings` and `ruff check .` |
| `typecheck` | `uv run mypy` (strict) |
| `doc` | rustdoc with `RUSTDOCFLAGS=-D warnings` |
| `check-rust-matrix` | `stunt-core` without the `serde`/`bytemuck` features |
| `test` | `cargo test --workspace --all-features` and `uv run pytest` |
| `fmt-rust`, `fmt-py`, `fmt-check-rust`, `fmt-check-py`, `lint-rust`, `lint-py`, `test-rust`, `test-py` | single-language halves of the tasks above |
| `cov-rust` | `cargo llvm-cov` line-coverage summary for `stunt-core` and `stunt-gltf` (not part of `check`) |
| `cov-py` | `pytest` with `--cov=stunt_reel` term-missing report (no fail-under) |
| `deny` | `cargo deny check` — advisories, license allow-list, wildcard bans, and registry sources |
| `capture-ref` | new capture into `build/parity/captures/ctry/<id>`, never over an existing one (`--max-frames` defaults to 140) |
| `verify-corpus` | `.ksy` catalog check against `corpus/` |
| `play` | launch `tools/dosbox/dosbox-playone.conf` |
| `ensure-dosbox`, `mcp` | agent debugger plumbing |
| `parity-probe`, `verify-docs`, `unlzexe`, `probe-light`, `flm-events`, `adversarial` | analysis and diagnostic scripts that previously had to be called by file path |

The gate's lanes build the check profile into `target/check` and the no-default-features matrix into `target/matrix`, so those builds can run beside the `target/` build instead of waiting on its lock. All three directories sit under `target/`, which `.gitignore`, ruff's exclude, the recursive walkers and `mise run clean` already cover.

CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)) invokes the mise tasks instead of restating them. Every pull request runs the full `mise run check` gate on Ubuntu, with Mesa's lavapipe installed and `STUNT_REQUIRE_GPU=1` set so a missing adapter fails the GPU tests instead of skipping them ([ADR 0006](adr/0006-ci-renders-on-lavapipe.md)), and `check-windows-smoke` on Windows for the tests that can behave differently there. Windows gets a smoke test rather than the whole gate on pull requests because every Windows-only behaviour in this repository lives in the Python tree — `crates/` has no `cfg(windows)` — while a warm Windows Rust build costs about nine minutes. Pushes to `main` run the full `check-windows` too (format, lint, typecheck and both test suites; GPU tests skip without a driver), and `workflow_dispatch` runs every job on any branch. A separate job checks the declared MSRV (`1.88`), and a `cargo deny` job enforces the dependency policy; both run on every pull request and push rather than being path-filtered, since the runners are free once the repository is public. The cargo cache falls back to the newest previous lockfile through `restore-keys`, so a dependency bump rebuilds a delta instead of the whole workspace — a cold gate run measured 10m40 against 4m19 warm. Each job installs only the toolchain its task list uses (`rust`, `python`, `uv`, and Java with the Kaitai compiler where `test-py` runs), because `mise run` otherwise installs every tool `mise.toml` declares before its first task — compiling `cargo-deny` and `cargo-llvm-cov` from source and downloading DOSBox inside the gate — so the jobs set `MISE_AUTO_INSTALL=false`. Corpus- and DOSBox-X-dependent tasks stay local. A ruleset on `main` requires the four jobs that run on every pull request — `quality`, `windows-smoke`, `msrv` and `deny` — and blocks force pushes and deletion; repository admins may bypass it to push straight to `main`. The full Windows gate runs only on pushes to ... (line truncated to 2000 chars)

`renderer_test` can hang on some driver stacks even with the harness's per-process GPU lock: the tests exercise the Vulkan/DX12/GL loader and vendor driver locks, and a wedge there leaves a plain `cargo test` waiting forever without printing a result. Run GPU render tests through `mise run test-render -- --runs 20` (or `uv run python python/scripts/watch_render_test.py`): it builds the binary once, gives each attempt a 60-second wall-clock bound (`--timeout-s`), kills the whole process tree on expiry, and prints `HANG` with the elapsed time, the last 20 stdout lines and the child-process count, exiting 1. If it fires, do not leave the run unbounded: re-run with a longer `--timeout-s` and attach a debugger to the stuck process, or narrow it with `--test-threads 1`, and keep the diagnostics.

### Shared tool cache

`mise run init` links each checkout's `.cache/` to the primary checkout's copy; `mise.toml` points `UV_CACHE_DIR` and the cargo tasks' `CARGO_HOME` into it, so every worktree reuses one set of downloaded crates and uv artifacts. Build outputs (`target/`) and the Python tool caches stay per worktree, because they are revision-specific or not relocatable.

The virtualenv lives in that cache too: `init` lays it out as `<cache>/venvs/<checkout>-<digest>` and points `.venv` at it with a junction, because uv can only hardlink packages onto the cache's own volume and a worktree usually sits on another one. A per-checkout environment would copy 68 MiB (3.1 s) at every fresh init; the linked one installs in about 150 ms. `reap` deletes a reaped worktree's environment, `init` and `reap --prune` sweep environments whose checkout is gone, and `mise run clean` reports it without removing it. `rm -rf .cache` deletes every environment with the cache. See [ADR 0013](adr/0013-worktrees-share-one-writable-tool-cache.md) and [ADR 0019](adr/0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md).

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
- **Two pins are frozen.** `kaitai_struct_compiler` carries a `sha256` of its release zip and the DOSBox entries name an `asset_pattern` and `bin_path`; for those a version bump alone installs nothing, and no gate run on any platform would catch it.
- **Security fixes still arrive.** Dependabot's alerts stay on and Renovate raises the fix PRs from them; Dependabot's own version and security updates are off, so one bot writes lock files and one raises advisories.

Three conventions keep the pins honest. A **pin** is what gets installed ([`mise.toml`](../mise.toml) `[tools]`, [`rust-toolchain.toml`](../rust-toolchain.toml)), and only a pin may move automatically. A **floor** is the minimum the project claims (`rust-version = "1.88"`, `requires-python = ">=3.11"`), and moving one is a deliberate act after `msrv` proves it. A **target** is what ruff and mypy assume, which Renovate cannot see, so a pin moves only when its targets move with it. [`tests/test_toolchain_pins.py`](../tests/test_toolchain_pins.py) fails the gate if a pin, a floor and a target drift apart — and that test is what lets the compiler stay declared in two files at all: `rust-toolchain.toml` resolves (rustup reports the active toolchain overridden by it) while `mise.toml` installs, so the two are one Renovate group and the test proves them equal.
