# The Python package's module layers are checked by tach

## Status

accepted 2026-11-18. The admitting record that
[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) asks for, for the `tach`
dev dependency, which checks the module layers of [`python/stunt_reel/`](../../python/stunt_reel/)
in `mise run check-py` ([#700](https://github.com/neilsh/stunt-reel/issues/700)).

## Context

`python/stunt_reel/` is a flat namespace of about 40 modules doing three jobs: the capture
harness, the parity loop, and repository tooling (worktrees, work folders, docs, cloud assets).
Nothing stated which module may import which, so the layering held only by habit.

#700 sorted the modules into those three groups plus shared helpers and counted ten imports that
crossed between groups, six of them into `parity_layout` and `link`, which behave as shared
path-layout modules. Its table is not complete. Among the crossings it leaves out, under its own
grouping, are `capture_run` → `references`, `tac` → `parity_artifacts`, `cloud_assets` →
`references`, and `all_archive`, `capture_run` and `tac.staging` → `parity_layout`.

## Decision

[`tach.toml`](../../tach.toml) states the layers, and `mise run check-layers` (`tach check`) is a
step of the gate's Python half. No file moves.

| Group | Members | May import |
|---|---|---|
| scripts | `python/scripts/` | anything |
| tooling | `cloud_assets`, `doc_anchors`, `frontmatter`, `markdown_links`, `research_notes`, `site_pages`, `target_seed`, `work_items`, `worktree_*` | the tooling modules it names, and shared |
| parity | `batch_films`, `batch_ledger`, `batch_stages`, `bench`, `expected_scores`, `matched_frames`, `parity_figures`, `parity_judge`, `parity_pictures`, `parity_pipeline` | parity, capture, shared |
| capture | the package's `__init__` (`stunt_reel`, which imports `tac`), `all_archive`, `avi`, `capture_run`, `capture_store`, `game_builds`, `references`, `tac` | capture, shared |
| shared | `dataroot`, `flm_walk`, `git_env`, `gvpoly_stream`, `hashing`, `kaitai`, `link`, `parity_artifacts`, `parity_layout`, `process_tree`, `scene_tree`, `scratch`, `uv` | shared |

Five modules are not where #700's table put them, two of them moved as #700 proposed. Each move
removes crossings rather than allowing them:

- **`parity_layout` and `link` are shared**, as #700 proposed: one says where the parity artifacts
  live, the other runs `stuntreel link` on a film's `.ALL`, and capture, parity and tooling all
  use them.
- **`parity_artifacts` is shared.** It imports nothing from the package and only the standard
  library: it is the typed readers and writers of the files the Rust binaries, the capture
  harness and the parity loop pass between them. `parity_layout` says where those files are;
  `parity_artifacts` says what they hold.
- **`git_env` is shared.** It builds the environment for a git command that must act on the
  repository it names, imports nothing from the package, and both `work_items` and
  `expected_scores` use it.
- **`references` is capture.** It reads which capture is a film's reference and which game build
  made it, and imports `capture_store`; `capture_run` needs it to choose the build before it
  captures, and parity uses it from above.

One import that the layers forbid remains, allowed by name in `tach.toml`: `cloud_assets` →
`references`. The captures archive a cloud session fetches is pinned to each reference's capture
digest, which only `references.capture_digest` computes, and packing checks each digest against
the row `references` reads.

tach's layers form one stack, so the groups sit in it in the table's order. Two settings make the
stack hold the tooling rule: `layers_explicit_depends_on` takes away the free use of lower layers
that a layer otherwise gives, so tooling must name what it imports, and shared is a `utility`
layer that every module may use without naming it. Capture and parity name nothing, so they may
use what their place in the stack allows. Code in no group is tach's `<root>` module, placed in the
top layer: a script may import anything, and no grouped module may import one. A module added to
the package without a group belongs to the `stunt_reel` module, so it is checked as capture until
it joins a group, and a test fails until it does. tach skips imports under `TYPE_CHECKING` by
default; `ignore_type_checking_imports = false` checks them, since a type-only import is a
dependency too.

Two tests prove the configuration catches a change, in
[`test_module_layers.py`](../../tests/test_module_layers.py): every module of the package is in a
group, and a planted import (capture → parity, tooling → capture, a package module or the
package's `__init__` → a script, and a type-only capture → parity) fails `tach check` on a copy
of `python/`. The module is marked `windows`, so the pull-request Windows
job runs tach there; the Windows gate on `main` runs `check-layers` itself.

ADR 0010's checks:

- **Wheels:** `tach` ships `abi3` wheels for Windows, Linux and macOS. One dependency has no
  wheel for Python 3.15: `pyyaml`, which tach imports only to migrate a deprecated `tach.yml`.
  `[tool.uv] exclude-dependencies` keeps it out of the lock, so `uv sync --locked` builds nothing
  from source.
- **Typed:** not met: `tach` ships no `py.typed` and has no mypy plugin. This record sets the
  check aside because no code imports tach: the gate runs its CLI, and the test runs
  `python -m tach` in a child process, so mypy never reads it.
- **Licence:** MIT.
- **Maintained:** fourteen releases in the year to 2026-11-18, from 0.32.0 (2025-11-19) to
  0.35.3 (2026-10-06), and commits to 2026-10-29. The repository moved from `gauge-sh/tach` to
  `tach-org/tach`; both names resolve to one history, and PyPI's `tach` is released from it.
- **Dependency tree:** `uv tree --package tach`. `rich` (with `markdown-it-py`, `mdurl` and
  `pygments`, the last already locked) prints the report, and `tomli-w` (already locked, ADR 0049)
  writes `tach.toml` for `tach mod` and for a config tach migrates. The rest exist for commands
  the gate does not run: `prompt-toolkit` (with `wcwidth`) the interactive `tach mod`, `gitpython`
  (with `gitdb`, `smmap`) the pytest plugin's changed files and the report upload, and `networkx`
  and `pydot` (with `pyparsing`) `tach show`'s graph. All are under MIT or BSD licences, and all
  but `wcwidth` ship only a pure-Python wheel; `wcwidth` adds compiled wheels beside its
  `py3-none-any` one.

## Considered Options

- **A test that walks the package's imports with `ast`.** Rejected: it would reimplement what tach
  resolves already, relative and `lazy` imports (PEP 810), imports under `TYPE_CHECKING`, and
  subpackages, and the count #700 made by reading imports missed crossings.
- **Keeping #700's grouping and allowing each crossing by name.** Rejected: more than a dozen named
  exceptions would record a grouping the imports contradict. Moving five modules removes all but
  one.
- **Moving the groups into subpackages.** Out of scope: #700 moves no files. Subpackages would let
  `tach.toml` name a group by a glob instead of a list.
- **A source build of `pyyaml`.** Rejected by ADR 0010's first check: no other locked package
  builds from source, and `tach check` never imports it.

## Consequences

- A module added to `python/stunt_reel/` joins a group in `tach.toml`, or the test fails; until
  then tach checks it as capture.
- A change to `tach.toml` runs the gate's Python half (`gate.py` classifies it with
  `pyproject.toml` and `uv.lock`).
- tach installs a pytest plugin that diffs against the base branch on every run once `tach.toml`
  exists. pytest's `addopts` turn it off with `-p no:tach`.
- If a future tach imports `yaml` on the `tach check` path, the exclusion fails the gate's
  `check-layers` step, and this record's wheel check needs revisiting.
