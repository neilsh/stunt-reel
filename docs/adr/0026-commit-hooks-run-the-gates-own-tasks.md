# Commit hooks run the gate's own tasks

## Status

accepted. Reverses the deletion of `.pre-commit-config.yaml` recorded in
[`review-dsh-friction-salvage.md`](../process/plans/review-dsh-friction-salvage.md) on the
condition that removed it: the new hooks cannot hold a copy of the gate.

## Context

The repository once shipped a `.pre-commit-config.yaml`. Nothing installed or ran it, the README
said its hooks "mirror the gate", and it pinned ruff `0.9.1` while the gate ran `0.17.1`. It was
deleted with `quiet_check.py` for the reason [ADR 0014](0014-the-gate-is-one-ordered-script.md)
gives: a second copy of the gate drifts from the first.

The wish behind it has not gone away. A formatting or lint slip is cheapest to catch at
`git commit`, before a full `mise run check` (55–64 s cold, about 18 s warm, per
[ADR 0017](0017-the-gate-keeps-no-compiler-cache.md)) or CI reports it.
[prek](https://github.com/j178/prek) is a single-binary, pre-commit-compatible hook runner whose
built-in hooks are implemented natively, so they need no network, no Python environment and no
pinned hook repository.

## Decision

Opt-in pre-commit hooks, run by prek, configured in `prek.toml` at the repository root. Every
hook is one of two kinds:

1. **A gate step.** A `repo = "local"` hook whose `entry` is exactly `mise run <task>`, where
   `<task>` is a step in `STEPS` of [`gate.py`](../../python/scripts/gate.py). It sets
   `pass_filenames = false` and fires only when a file of its kind is staged:

   | hook id | entry | fires on |
   | --- | --- | --- |
   | `fmt-check-rust` | `mise run fmt-check-rust` | `types = ["rust"]` |
   | `fmt-check-py` | `mise run fmt-check-py` | `types = ["python"]` |
   | `lint-py` | `mise run lint-py` | `types = ["python"]` |

   Only the fast, read-only steps qualify. Clippy, the test suites, mypy, rustdoc and the
   feature matrix stay in `mise run check`. A hook never rewrites files; the fix is
   `mise run fmt`.
2. **A prek built-in** (`repo = "builtin"`) that backs a rule this repository already states:

   | hook id | rule it backs |
   | --- | --- |
   | `check-added-large-files` | asset isolation `[I7]`: no game binaries in Git |
   | `check-illegal-windows-names`, `check-case-conflict` | the gate and the capture tooling run on Windows |
   | `check-merge-conflict` | union-merged append-only files ([SOP 6.4](../../AGENTS.md)) must not keep markers |
   | `check-toml`, `check-yaml` | `mise.toml`, `pyproject.toml`, `.github/` and `.coderabbit.yaml` are configuration |
   | `detect-private-key` | the repository is public ([ADR 0015](0015-publication-with-a-documented-palette-exception.md)) |

   Whitespace and end-of-file fixers are excluded: they rewrite files, and `.editorconfig`
   already owns that policy.

`prek.toml` sets `default_install_hook_types = ["pre-commit"]`. prek is pinned in
[`mise.toml`](../../mise.toml) like every other tool, and `mise run hooks` runs
`prek install --allow-missing-config`. Git keeps hooks in the common `.git/hooks`, so one install
serves every linked worktree, and a worktree whose branch predates `prek.toml` commits without
hooks instead of failing; only the
`pre-commit` shim is written, which leaves the untracked noreply-email `pre-push` hook from the
[public-release plan](../process/plans/public-release-2026-10-28.md) untouched.

## What enforces this

- **The hook test.** [`tests/test_prek_config.py`](../../tests/test_prek_config.py) reads
  `prek.toml` and fails the gate if a local hook's entry is anything other than
  `mise run <task>` for a task in `gate.STEPS`, if a local hook passes filenames, if a repository
  other than `local` or `builtin` appears (no remote hook repository, so no second version pin),
  or if `default_install_hook_types` names anything but `pre-commit`.
- **One pin.** prek's version lives only in `mise.toml`; the hooks themselves carry none.

## Considered Options

- **Hooks call the tools directly on the staged files** (`uv run ruff check {files}`). Rejected:
  slightly faster, and still the uv.lock ruff, but a second argument list beside the mise task is
  the softer form of the drift being avoided.
- **Upstream hook repositories** (`astral-sh/ruff-pre-commit`, `doublify/pre-commit-rust`).
  Rejected: this is the deleted file — a second version pin kept in step by hand.
- **`mise run check` on `pre-push`.** Rejected for now: about a minute per push, and CI already
  runs the gate on every pull request. It would also contend with the existing untracked
  `pre-push` hook.
- **Install the hooks from `mise run init`.** Rejected: hooks stay opt-in, and `init` runs in
  sandboxed sessions where writing `.git/hooks` in the common directory is outside the workspace.
- **`.pre-commit-config.yaml` instead of `prek.toml`.** Rejected: the old file name invites
  running it with Python pre-commit, which cannot run the `builtin` hooks.
- **Run prek in CI.** Rejected: CI runs the full gate, which is a superset.

## Consequences

- A commit that stages Rust or Python runs the formatting and lint checks the gate would run, with
  the same tool versions, in a few seconds. They check the whole tree, not only the staged files,
  so an unformatted file elsewhere also blocks the commit until `mise run fmt`.
- `git commit --no-verify` skips the hooks; the gate and CI remain the enforcement.
- Hooks need `mise` on the `PATH` that Git's hook shell sees. On Windows that is Git for
  Windows' `sh`, which inherits the user's `PATH`.
- Adding a hook means adding a gate step first, or choosing a built-in; the hook test refuses
  anything else.
