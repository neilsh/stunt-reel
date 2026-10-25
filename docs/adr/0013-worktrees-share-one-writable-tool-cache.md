# Worktrees share one writable tool cache

`CARGO_HOME` and `UV_CACHE_DIR` point at `<checkout>/.cache`, and `mise run init`
links that directory to the primary checkout's copy, so every worktree of this
repository reuses one set of downloaded crates and uv artifacts instead of
paying for its own. Build outputs (`target/`), the virtualenv and the Python
tool caches stay per worktree: they are revision-specific or not relocatable,
and a shared `CARGO_TARGET_DIR` serialises whole builds — two concurrent probe
builds on one artifact directory took 26.6 s against 13.4 s on separate ones.
The shared cache is writable, unlike the data root, because downloaded crates
and uv artifacts are disposable; `rm -rf .cache` is the reset.

## What enforces this

- **The link.** [`ensure_cache_link`](../../python/stunt_reel/dataroot.py) runs
  from `mise run init` ([`worktree_init.py`](../../python/scripts/worktree_init.py)):
  it creates the primary's `.cache`, moves a cache that the first `uv sync` made
  before the link existed into it, and replaces the directory with a junction
  on Windows (a symlink elsewhere). [`test_dataroot.py`](../../tests/test_dataroot.py)
  covers the worktree, primary and adoption cases.
- **The environment.** [`mise.toml`](../../mise.toml) sets `UV_CACHE_DIR` from
  `{{config_root}}` and `CARGO_HOME` on the tasks that invoke cargo, so every
  checkout resolves to its own `.cache` link without a machine-specific path.
  `CARGO_HOME` is per task rather than global on purpose: mise installs its
  rustup shim **into** `$CARGO_HOME`, and an executable inside this checkout
  carries the checkout's low integrity label, so it runs at low integrity and
  cannot write the user's `RUSTUP_HOME` -- nor should a shared cache hold a
  toolchain that every worktree then executes.
- **Walker hygiene.** The directory is gitignored, ruff-excluded and skipped by
  the recursive walkers; [`test_worktree_layout.py`](../../tests/test_worktree_layout.py)
  fails when it is not, the rule ADR 0008 already applies to worktrees.
- **Reset.** `mise run clean` reports the shared cache and never removes it.

## Considered Options

- **Per-worktree caches.** Rejected: every worktree re-downloads the same
  registry crates and uv artifacts.
- **A generated `.mise.local.toml` with absolute paths.** Rejected: the mapping
  would be untracked, per machine, and silently stale after a rename, where a
  committed template plus one junction keeps one source of truth.
- **A shared `CARGO_TARGET_DIR`.** Rejected: cargo locks the artifact directory
  for the whole build (measured above), serialising parallel `mise run check`
  runs. See [ADR 0008](0008-worktrees-share-one-read-only-data-root.md), which
  reached the same conclusion for build output.
- **`sccache`.** Deferred, not rejected: it shares compiled dependencies without
  the target lock, but it needs incremental compilation off, one local server,
  and a spike before its client/server channel is trusted under the Windows
  sandbox's restricted token.
- **Labelling the user-profile caches `low`.** Rejected: DSH's Windows sandbox
  runs children with a write-restricted token whose restricting SIDs the profile
  ACLs do not carry, so a mandatory label alone would not grant the write; adding
  the capability ACE would let a sandboxed session poison caches every
  unconfined build trusts.

## Consequences

A worktree's first `uv sync` runs before the link exists and is adopted into the
shared cache by `init`; later runs write the shared cache directly. The test
tasks point `TMP`/`TEMP` at the shared cache's `tmp/`, and pytest pins a
per-checkout basetemp, because a low-integrity test binary cannot write the
user's temp directory. Cargo's
package-cache lock briefly serialises worktree builds, which is acceptable where
the artifact-directory lock was not. A checkout that never runs `init` silently
keeps a local `.cache`; `init` prints the link state so the drift is visible.
