# Worktrees reach shared state by configuration, not links

## Status

accepted 2026-11-04 ([spec](../process/plans/worktree-config-2026-11-04.md),
[plan](../process/plans/worktree-config-implementation-2026-11-04.md)). Supersedes
[ADR 0019](0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md) and amends
[ADR 0008](0008-worktrees-share-one-read-only-data-root.md),
[ADR 0013](0013-worktrees-share-one-writable-tool-cache.md),
[ADR 0018](0018-reaping-unlinks-the-data-root-links-first.md) and
[ADR 0030](0030-new-worktrees-seed-target-by-block-clone.md).

## Context

A worktree reached the shared data root, the tool cache and its Python environment through
junctions that `mise run init` made, and nothing ran `init`. On 2026-11-04, 16 of the 32
worktrees under `.claude/worktrees/` had never been provisioned: their first `uv run` built a real
`.venv` that a later `init` discarded, and their parity scripts read the corpus only because three
of them repaired a missing link when they started.

Claude Code offers no hook that runs after it creates a worktree. `WorktreeCreate` replaces its
creation and so loses its cleanup-sweep marker, filter-driver neutralization and
`.worktreeinclude`; whether `SessionStart` fires in a new desktop or subagent worktree is
undocumented; the desktop app has no setup-script setting.

The junctions existed for two reasons that no longer hold for the main harness: DSH's
`workspace-write` sandbox admits writes only inside the workspace (ADR 0013), and a worktree on
another volume from the cache cannot hardlink out of it (ADR 0019). Claude Code's worktrees sit
inside the primary checkout on the same Dev Drive, and a DSH session runs these tasks under
`danger-full-access`.

## Decision

A new worktree holds no links. Each piece of shared state is named where it is used:

- Code reads the corpus and the captures through `dataroot.data_root()`, which honours
  `STUNT_DATA_ROOT`, then `<primary>.data`. Only the corpus falls back further, to the primary
  checkout's own `corpus/` when the data root has none, because the captures and the stage are
  written and the stage must sit outside every checkout. A relative `corpus/...` or
  `captures/...` path on the command line resolves the same way.
- `mise.toml` names the uv and Cargo caches by absolute path under the primary checkout's
  `.cache`, from `git rev-parse --git-common-dir`.
- Each worktree keeps uv's default `.venv`; on the same volume uv hardlinks it out of the cache.
- Tasks use the operating system's temporary directory.
- A hidden `ensure` task, a dependency of every task that builds Rust, seeds an empty `target/`
  (ADR 0030) and sets `core.hooksPath`, under a lock. `mise run init` does the same eagerly.

Claude Code may remove the worktrees it creates. Existing linked worktrees are not migrated: their
links keep working, and `mise run reap` keeps its unlink-and-prove step for them (ADR 0018).

## Considered Options

- **`.worktreeinclude`.** It copies gitignored files, and everything gitignored here is data or
  cache that must be shared, not copied. A copied `target/` also keeps the workspace crates'
  fingerprints that the seed drops.
- **A `WorktreeCreate` hook that runs `init`.** It gives up Claude Code's own worktree handling
  for a speed-up, and still leaves junctions for Claude Code's removal to meet.
- **A `SessionStart` hook that runs `init`.** Its firing in new worktrees is undocumented, and it
  saves only the seed and a `uv sync` that the first task does anyway.
- **Automate `init` and keep the links.** Every tool that makes a worktree would need its own
  trigger, and every tool that removes one would need to unlink first.
- **A per-worktree `UV_PROJECT_ENVIRONMENT` in the shared cache.** It keeps ADR 0019's orphan
  sweep and its marker files for an environment uv already places well by default.

## Consequences

- ADR 0019 is superseded. ADRs 0008, 0013, 0018 and 0030 keep their decisions with a dated
  amendment line each (the documentation task of the plan adds them).
- `ensure_links_or_report`, `ensure_cache_link` and `ensure_venv_link` go. `LINK_TARGETS`,
  `ensure_links`, `env_target` and the orphan sweep stay for `reap` until the last linked
  worktree is reaped.
- A worktree on another volume (Orca's on `C:`) copies its environment instead of hardlinking it,
  about 68 MB and 3 s.
- The first building task in a new worktree pays the seed, about 40 s, before Cargo starts.
