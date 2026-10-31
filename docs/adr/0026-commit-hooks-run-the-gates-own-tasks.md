# Commit hooks run through prek, calling the gate's own tasks

## Status

accepted. Supersedes the `staged` plan that
[#32](https://github.com/neilsh/stunt-reel/pull/32) added to
[`gate.py`](../../python/scripts/gate.py); keeps that change's committed `.githooks/` and its
installation by `mise run init`. Reverses the deletion of `.pre-commit-config.yaml` recorded in
[`review-dsh-friction-salvage.md`](../process/plans/review-dsh-friction-salvage.md) on the
condition that removed it: the hooks hold no copy of the gate.

## Context

The repository once shipped a `.pre-commit-config.yaml`. Nothing installed or ran it, and it
pinned ruff `0.9.1` while the gate ran `0.17.1`. It was deleted for the reason
[ADR 0014](0014-the-gate-is-one-ordered-script.md) gives: a second copy of the gate drifts.

#32 then added a committed pre-commit hook: `mise run init` points `core.hooksPath` at
`.githooks/`, whose `pre-commit` runs `mise run pre-commit`, which ran `gate.py staged`. That plan
read the staged paths, ran `fmt-check-py` and `lint-py` (and `test-docs` when Markdown was
staged) and `git diff --cached --check`. It is a small hook runner of the repository's own, and
it has two gaps:

- **It checks the working tree, not the commit.** `gate.py staged` lists the staged paths and
  then runs ruff over the tree as it stands, so an unstaged edit can fail a clean commit or pass
  a broken one.
- **Each new check is code.** Choosing steps by file type, and checks such as large files or
  Windows-illegal names, are Python branches with their own tests.

[prek](https://github.com/j178/prek) is a single-binary, pre-commit-compatible hook runner. Before
a default run it saves unstaged changes to a patch, checks the index out over the tree
(`git checkout --`), runs the hooks, and reapplies the patch (prek 0.5.5 `src/cli/run/stash.rs`),
so hooks see what is being committed. It selects hooks by file type from configuration and ships
native built-in checks that need no network or Python environment.

## Decision

prek runs the commit-time checks; `gate.py` stays the gate.

- **Installation is unchanged.** `.githooks/pre-commit` still chains to an untracked hook and then
  runs `mise run pre-commit`; `mise run init` still sets `core.hooksPath`. The `pre-commit` task
  now runs `prek run --config prek.toml`. No `prek install`: the committed hook is the shim, and
  because `core.hooksPath` is relative, a checkout of an older branch runs that branch's own
  `.githooks/`.
- **`prek.toml` holds the plan.** Every local hook is exactly `mise run <task>` for a leaf task of
  [`mise.toml`](../../mise.toml), with `pass_filenames = false`, so each command is still defined
  once. A hook fires on its file types, or on every commit with `always_run = true`:

  | hook id | entry | fires on |
  | --- | --- | --- |
  | `diff-check` | `mise run diff-check` (`git diff --cached --check`) | every commit (`always_run`) |
  | `fmt-check-rust` | `mise run fmt-check-rust` | `types = ["rust"]` |
  | `fmt-check-py` | `mise run fmt-check-py` | `types = ["python"]` |
  | `lint-py` | `mise run lint-py` | `types = ["python"]` |
  | `test-docs` | `mise run test-docs` | every commit (`always_run`) |

  prek passes no deleted file to a hook, so a commit that only deletes a linked page would skip a
  hook filtered to Markdown; `test-docs` and `diff-check` therefore run on every commit.
  `fmt-check-rust` is new: #32's plan checked no Rust. The rest are prek built-ins that back a rule
  this repository already states:

  | hook id | rule it backs |
  | --- | --- |
  | `check-added-large-files` | asset isolation `[I7]`: no game binaries in Git |
  | `check-illegal-windows-names`, `check-case-conflict` | the gate and the capture tooling run on Windows |
  | `check-merge-conflict` | union-merged append-only files ([SOP 6.4](../../AGENTS.md)) must not keep markers |
  | `check-toml`, `check-yaml` | `mise.toml`, `pyproject.toml`, `.github/` and `.coderabbit.yaml` are configuration |
  | `detect-private-key` | the repository is public ([ADR 0015](0015-publication-with-a-documented-palette-exception.md)) |

  No hook rewrites files: the whitespace and end-of-file fixers are left out, and the fix for a
  format failure is `mise run fmt`.
- **`gate.py staged` is removed** with its constants, its log path and its tests; `gate.py` runs
  only `all`, `rust` and `py` again.
- **CI runs the hooks' extra checks.** The `quality` job installs prek and runs it with the
  gate-step hooks skipped (`SKIP=diff-check,fmt-check-rust,fmt-check-py,lint-py,test-docs`), since
  the gate it already runs covers them: a pull request over `--from-ref origin/<base>`, a push to
  `main` over `--from-ref <previous tip>` (admins may push there without a pull request), and a
  manual run over `--all-files`. A commit made with `--no-verify` or without hooks no longer reaches `main`
  unchecked for the built-ins.
- **prek is pinned in `mise.toml`** like every other tool; the hooks carry no versions.

## What enforces this

- [`tests/test_prek_config.py`](../../tests/test_prek_config.py) reads `prek.toml` and fails the
  gate if a local hook's entry is not `mise run <task>` for a leaf task of `mise.toml`, if a local
  hook sets any key beyond `id`, `name`, `entry`, `language`, `pass_filenames`, `types` and
  `always_run`, if the hook or built-in sets differ from the tables above, if a repository
  other than `local` or `builtin` appears, or if the `pre-commit` task stops running prek.
- A prek integration test ([`tests/test_prek_hooks.py`](../../tests/test_prek_hooks.py)) builds a
  scratch repository, stages a valid TOML file, leaves a broken edit unstaged, and asserts
  `prek run` passes and the edit survives; the reverse must fail. The same file holds CI's `SKIP`
  list to the local hook ids. It runs
  where prek is installed and is required in CI (`STUNT_REQUIRE_PREK=1`), the way
  `STUNT_REQUIRE_KSC` guards the schema test.

## Considered Options

- **Keep `gate.py staged` and add the missing checks to it.** Rejected: more of the repository's
  own runner to maintain, and it still checks the working tree, not the commit.
- **Keep #32's runner and call prek from `.githooks/pre-commit` for the built-ins only.**
  Rejected: two runners in one hook, and the working-tree gap stays.
- **`prek install` into `.git/hooks`.** Rejected: `core.hooksPath` turns those hooks off, and the
  shared hooks directory fails commits in checkouts without `prek.toml` unless installed with
  `--allow-missing-config`. The committed `.githooks/` has neither problem.
- **Hooks that call the tools directly on the staged files** (`uv run ruff check {files}`).
  Rejected: a second argument list beside the mise task is the drift being avoided.
- **Upstream hook repositories** (`astral-sh/ruff-pre-commit` and others). Rejected: a second
  version pin kept in step by hand, which is the deleted file.
- **Move the untracked noreply `pre-push` check into prek.** Not taken here: whether that policy
  is tracked is a separate decision. `.githooks/pre-push` still chains to it.

## Consequences

- A commit runs the checks that match its staged files, against the staged content, with the
  gate's tool versions. Untracked files are not stashed, so a whole-tree step such as ruff still
  sees untracked `.py` files, as before.
- The hook's output is prek's pass/fail list; #32's one-line-per-step report and
  `target/pre-commit.log` go away with `gate.py staged`.
- prek is a required tool for every checkout that runs `mise run init`, and for CI.
- `git commit --no-verify` skips the hooks. The gate covers the gate-step hooks and the CI step
  covers the built-ins.
- Adding a hook means adding a leaf task or choosing a built-in, then updating this record and
  the hook test.
