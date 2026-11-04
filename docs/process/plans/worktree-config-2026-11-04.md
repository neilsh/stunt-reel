# Worktrees reach shared state by configuration, not links (2026-11-04)

Status: **design agreed 2026-11-04; corrected the same day while planning (sections 3, 4.1, 4.3); implemented on branch `claude/worktreeinclude-brainstorm-b409c5` as ADR 0033, not ADR 0032, which another decision had taken**.
Tasks: [`worktree-config-implementation-2026-11-04.md`](worktree-config-implementation-2026-11-04.md). Source: a session of
2026-11-04 that started from "should we use a `.worktreeinclude` for Claude", surveyed the 32
worktrees under `.claude/worktrees/` (16 never provisioned, including the session's own) and
settled on removing the per-worktree links rather than automating their creation. The decision
will be recorded as ADR 0032 (layer 1, below); this note owns the design and the delivery.

## 1. Goal

A worktree made by any tool works on its first command, with no agent turn spent setting it up:

- Claude Code desktop sessions, `claude --worktree`, subagents with `isolation: worktree`, Orca and
  DSH workspaces, and a plain `git worktree add` all end up correct;
- a new worktree holds no junctions, so whoever removes it, Claude Code, `git worktree remove` or a
  person, cannot delete shared data through it;
- the only per-worktree preparation left, seeding `target/` (ADR 0030), happens by itself before
  the first Cargo build.

Not in scope: sharing build output between running worktrees, the stale-worktree backlog (reap
handles it as today), and the upstream archives (`corpus/*.zip`) that only the primary checkout
holds and no code reads.

## 2. What forced it

- `mise run init` is the only provisioning step, and nothing runs it. On 2026-11-04 half the
  Claude worktrees had no `.cache` or `.venv` link; the ones that did were mostly subagent
  worktrees whose agent ran init by hand.
- In an unprovisioned worktree the first `uv run` task builds a real `.venv` in the checkout,
  which a later init discards ([`ensure_venv_link`](../../../python/stunt_reel/dataroot.py)).
- Claude Code offers no hook that runs after it creates a worktree. `WorktreeCreate` replaces its
  creation and so loses its cleanup-sweep marker, filter-driver neutralization and
  `.worktreeinclude`; whether `SessionStart` fires in a new desktop or subagent worktree is
  undocumented; the desktop app has no setup-script setting
  ([worktrees](https://code.claude.com/docs/en/worktrees), [hooks](https://code.claude.com/docs/en/hooks)).
- The junctions exist for two reasons that no longer hold for the main harness: DSH's
  `workspace-write` sandbox, which admits writes only inside the workspace (ADR 0013), and
  worktrees on another volume from the cache, where uv cannot hardlink (ADR 0019). Claude Code's
  worktrees sit inside the primary checkout on the same Dev Drive, and DSH no longer constrains the
  design: a DSH session runs these tasks under `danger-full-access`.

## 3. Decisions

| Area | Decision | Why |
| --- | --- | --- |
| `.worktreeinclude` | Not used. | It copies gitignored files. Everything gitignored here is data or cache that must be shared, not copied; a copied `target/` would also keep the workspace crates' fingerprints that the seed drops (ADR 0030). |
| Claude Code hooks | None: no `WorktreeCreate`, no `SessionStart`. | The first gives up Claude Code's own worktree safety for a speed-up; the second saves only the seed and a `uv sync` at the first task, on undocumented firing. Revisit if first-task latency becomes a nuisance. |
| Data root | Code resolves `corpus/` and `captures/` through `data_root()` instead of junctions; a relative `corpus/...` argument on the command line resolves the same way. | `data_root()` already honours `STUNT_DATA_ROOT` and the `<primary>.data` default; it gains a fallback to the primary checkout when `<primary>.data` does not exist, so a clone that keeps its corpus in the checkout still reads it. |
| Tool cache | `UV_CACHE_DIR` is an absolute path under the primary checkout's `.cache`, derived from `git rev-parse --git-common-dir` like `vars.cargo_home`. No `.cache` link. | One cache per machine, no link to make or break. |
| Python environment | uv's default per-checkout `.venv`. | On the same volume uv hardlinks out of the shared cache; editors find `.venv`; removing a worktree removes its environment, so no orphan sweep. Orca worktrees on `C:` copy (about 68 MB, 3 s), accepted. |
| Temporary files | The `TMP`/`TEMP` override in `[env]` goes; tasks use the OS temp directory. | It existed only for DSH's sandbox ([harness.md](../../harness.md#temporary-directories)). The Windows `mkdir` mode shim in `tests/conftest.py` and `scratch.py` stays. |
| Seeding | A hidden `ensure` task, a `depends` of every cargo task, seeds an empty `target/` and sets `core.hooksPath` when unset; otherwise it costs a few stats. `mise run init` stays as the explicit form of both. | Cargo tasks are the only ones that need a step; uv builds `.venv` itself on the first `uv run`. |
| Removal | Claude Code may remove the worktrees it creates. | A new worktree holds no links, and Claude Code documents deleting only the link where one exists. |
| Existing worktrees | No migration. | Their links keep working and nothing reads through them. `reap` keeps its unlink-and-prove step, because `git worktree remove` on a linked worktree deleted the link targets on git 2.47.1 and left the links behind on 2.55.0, the version installed now (ADR 0018). `.cache/venvs/` stays while any linked worktree points into it. |

## 4. Design

### 4.1 Data-root paths in code

- Every relative `corpus/...` and `captures/...` literal goes through one resolver:
  `data_root() / "corpus" / ...` for the game files, `parity_layout.capture_root()` resolved
  against the data root for captures. The callers are about 14 files across `python/scripts/`
  (`adversarial_formats_challenge`, `batch_parity`, `capture_playone_reference`, `capture_video`,
  `game_builds`, `make_all`, `play`, `probe_playone_light`, `unlzexe`, `verify_formats_docs`,
  `verify_schemas_corpus`) and `python/stunt_reel/` (`parity_layout`, `parity_pipeline`,
  `tac/staging`).
- Captures move from the checkout path `build/parity/captures` (a link) to
  `data_root() / "captures"`, so `parity_layout.capture_root()` returns an absolute path;
  `/captures/` joins `.gitignore` for a checkout that is its own data root.
- Command-line arguments naming `corpus/...` or `captures/...`, the form every task description
  and research note uses, resolve against the data root through an argparse `type`.
- Two Rust readers spell `corpus` relative to the checkout: the `sod-census` task passes
  `--corpus` from a mise var naming the data root, and the ignored `flm_camera_test` reads
  `STUNT_DATA_ROOT`.
- `ensure_links_or_report` and its 15 call sites go; `ensure_links` and `LINK_TARGETS` stay only
  where `reap` needs them to recognise and unlink old links.
- Command-line defaults and messages that print a `corpus\...` path print the resolved path.
- `mise run check` stays corpus-free: a test that exercises a data-root path points
  `STUNT_DATA_ROOT` at a temporary directory or a fixture.

### 4.2 Tool paths in configuration

- [`mise.toml`](../../../mise.toml) gains `vars.shared_cache` (the `cargo_home` expression without
  its `/cargo` suffix, same git fallback); `cargo_home` and `UV_CACHE_DIR` derive from it.
- `TMP` and `TEMP` leave `[env]`; [harness.md](../../harness.md) keeps the DSH symptom and the
  one-line workaround for a DSH session.
- `dataroot.py` loses `ensure_cache_link` and `ensure_venv_link`, and `worktree_init.py` loses
  the `uv venv` seed and `init`'s orphan sweep. `env_target` and the sweep stay behind
  `reap -- --prune` until `.cache/venvs/` is gone (section 7); `cache_root()` stays, since the seed
  and `reap` use it.
- The primary checkout is unchanged: its `.cache` and `.venv` are already real directories.

### 4.3 `ensure`

- `[tasks.ensure]`, `hide = true`, runs plain `python` with `PYTHONPATH` set, like `init`, so it
  works before any environment exists. Stdlib only at import time.
- Every task that runs cargo, directly or through `parity_pipeline`, lists `ensure` in `depends`;
  [`tests/test_worktree_layout.py`](../../../tests/test_worktree_layout.py) fails the gate when one
  does not. The gate runs each step as its own `mise run` ([`gate.py`](../../../python/scripts/gate.py)),
  so four lanes start `ensure` at once: it holds an exclusive lock on `target/.ensure.lock`, and
  the first holder seeds while the rest find `target/` built.
- `init` becomes `ensure` plus its report: hooks path, seed result, and a line naming any old links
  still in the checkout.

### 4.4 Documentation

- [docs/harness-setup.md](../../harness-setup.md): harness-neutral steps first (install, trust,
  data root, the first `mise run` seeds), then a Claude Code section, then short DSH and Orca
  sections. The DSH section says its sessions need `danger-full-access` for `mise run` tasks.
- [AGENTS.md](../../../AGENTS.md) SOP 6: drop "`mise run init` once per worktree"; removal is
  `reap` for linked worktrees and any tool's own removal for the rest.
- ADR 0032 records the decision. ADR 0019 gets "superseded by ADR 0032"; ADRs 0008, 0013, 0018 and
  0030 get dated "amended by ADR 0032" lines (repo convention: ADRs 0008, 0015, 0016).

## 5. Delivery

One `gh stack`, three layers, each passing `mise run check`:

1. ADR 0032 and section 4.1 (data-root paths in code).
2. Sections 4.2 and 4.3 (configuration, `ensure`, the `init` and `dataroot.py` removals).
3. Section 4.4 except ADR 0032 (harness-setup, harness.md, SOP 6, ADR status lines).

The implementation plan goes in `worktree-config-implementation-2026-11-04.md` beside this note.

## 6. Verification

- In a fresh `claude --worktree` worktree with no `init`: `mise run lint-py` passes, the checkout
  holds a real `.venv` and no reparse points, and the first cargo task seeds `target/` from a
  donor (`target/debug` present before Cargo builds anything).
- A parity command that needs no new capture (`mise run frame` on an existing one) reads the corpus
  and captures with no `corpus/` links in the checkout.
- `STUNT_DATA_ROOT` pointed elsewhere moves every corpus read, which a unit test holds.
- Removing that worktree through Claude Code's exit prompt leaves the data root and the shared
  cache untouched (size and file count before and after).
- `mise run reap -- --yes` still unlinks and removes an old linked worktree.

## 7. Open questions

- Whether uv warns or falls back silently when it cannot hardlink on the Orca `C:` worktrees;
  `UV_LINK_MODE=copy` there would silence a warning, nothing more.
- When the last linked worktree is reaped, a follow-up removes `reap`'s unlink step,
  `LINK_TARGETS` and `<primary>/.cache/venvs/`. Nothing tracks that yet.
