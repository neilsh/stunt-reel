# prek built-ins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade prek to 0.5.10, replace the custom `diff-check` hook with prek built-ins, fix what the new built-ins flag, and add the built-ins that cover gaps. The work ships as a stack of three PRs.

**Architecture:** Three layers, managed with `gh stack` and rooted on `main`:
1. `build/prek-upgrade`: the prek bump plus the `diff-check` replacement.
2. `style/prek-findings`: the tree fixes for the files the new checks flag.
3. `build/prek-new-builtins`: the new built-ins.

Each layer keeps `prek.toml`, [ADR 0026](../../../docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md) and `tests/test_prek_config.py` in step, as `prek.toml`'s header requires.

**Tech Stack:** prek 0.5.10 (`repo = "builtin"` hooks), mise, pytest, GitHub Actions (`.github/workflows/ci.yml`), `gh stack`.

**Spec:** none. The scope is the issue ([#462](https://github.com/neilsh/stunt-reel/issues/462)) and the decisions below, which came from running each candidate built-in read-only over the tree with prek 0.5.5 on 2026-11-13.

## Decisions

- **`diff-check` is replaced** by `trailing-whitespace --check --markdown-linebreak-ext=md` and `end-of-file-fixer --check`, with `check-merge-conflict` (already present) for conflict markers.
  - `--check` reports without rewriting, so ADR 0026's "No hook rewrites files" still holds.
  - The built-ins also run in CI over a commit range. `git diff --cached` reads an index that is empty in CI.
  - Lost: git's `space-before-tab` rule. Accepted.
- **`crlf-check` stays.** No built-in can replace it:
  - `mixed-line-ending --fix=no` passes a file that is CRLF throughout, because it is not *mixed*.
  - `--fix=lf` rewrites the file and fails the commit. ADR 0026's 2026-11-05 amendment rejected exactly that (#219).
  - prek's stash checks the index out over the tree, and the index is already LF, so a built-in may never see the working-copy CRLF that `ruff format --check` trips on.
  - Record this verdict in ADR 0026's Considered Options.
- **`commit-msg-check`, `check-work-frozen` and `test-docs` stay.**
  - `check-commit-trailers --require` is unconditional, but `Fresh-review:` is required only for work `spec.md` and `plan.md`.
  - No built-in checks a Conventional Commit subject.
- **The new built-ins are:**
  - `check-symlinks` and `destroyed-symlinks`;
  - `fix-byte-order-marker --check`;
  - `check-json`;
  - `check-vcs-permalinks`;
  - `forbid-new-submodules`.
- **These built-ins are left out:**
  - `no-commit-to-branch`: CI runs prek on pushes to `main`, so it would fail there unless it joined the `SKIP` list, which `test_ci_skips_exactly_the_local_hooks` holds to the local hooks.
  - `deny-filename-pattern`: it needs its own look at fixture false positives (follow-up).
  - `mixed-line-ending`: the index is LF by `.gitattributes`.
  - `pretty-format-json`: it reformats files.
- **The shebang pair is already in `prek.toml`** (#461, with `exclude = '(\.rs$|^work/)'`). This stack leaves it alone, except that Task 1 pins its `exclude` in `BUILTINS`.
- **Exempt paths, per hook (never a top-level `exclude`, which would also hide fixtures from `check-added-large-files` and `detect-private-key`):**
  - `^(tests/fixtures|work)/` on `trailing-whitespace`, `end-of-file-fixer` and `fix-byte-order-marker`. Fixtures are byte-exact test inputs. Work folders are dated records that change only for link fixes (AGENTS.md, directive 4).

## What the 2026-11-13 dry run flagged

| Hook | Path | Layer 2 action |
| --- | --- | --- |
| trailing-whitespace | `docs/adr/0021-capture-chooses-its-control-port.md` | fix |
| trailing-whitespace | `work/2026-11/235_sod-gates/journal.md` | exempt (`work/`) |
| end-of-file-fixer | `research/formats/sod-opcodes.md`, `LICENSE-CC-BY-4.0` | fix |
| end-of-file-fixer | 4 `work/` files, 6 `tests/fixtures/` files | exempt |
| check-vcs-permalinks | `docs/agents/issue-tracker.md:15` (`blob/<sha>/<path>#L12`) | write `#L<n>` so the example no longer matches |

The shebang rows of that dry run are moot: #461 already excludes `.rs` and `work/`. These hooks passed: check-json, check-symlinks, destroyed-symlinks, check-executables-have-shebangs, fix-byte-order-marker and mixed-line-ending.

## Global Constraints

- Every local hook is exactly `mise run <leaf task>`. Built-ins carry no `rev`.
- The prek pin lives in `mise.toml` (`prek = "0.5.10"`) and in `mise.lock` (both `linux-x64` and `windows-x64` entries).
- No hook rewrites a file except `crlf-check` (ADR 0026, amendment 2026-11-05).
- Stage paths by name. Never use `git add -A`, and never stage anything from `corpus/`.
- `mise run check` passes before each commit.
- Commit subjects are Conventional Commits.
- Layers 1 and 2 change `docs/*.md` and `research/`, so a fresh reviewer reads each diff before its push (AGENTS.md, Committing, rule 5).
- The commit that adds this `plan.md` carries a `Fresh-review:` trailer.

## Review Focus

1. **Markdown hard breaks:** a `.md` line ending in two spaces must pass `trailing-whitespace`. Covered in Task 1.
2. **Check mode is read-only:** a flagged file's bytes are unchanged after `prek run`. Covered in Task 1.
3. **Fixture bytes:** a `tests/fixtures/` file without a final newline passes. Covered in Task 1.
4. **Rust inner attributes:** a non-executable `.rs` file opening with `#![allow(...)]` passes the shebang hook. Already excluded by #461; `BUILTINS` pins the `exclude` in Task 1.
5. **The CRLF repair on Windows still works:** the existing `tests/test_check_crlf.py` covers it, and it must still pass in Task 1's gate run.

---

### Task 0: Stack and plan commit

- [ ] **Step 1:** From the primary checkout, run `git switch main`, then `git pull --ff-only`, then `gh stack init build/prek-upgrade`. The README and this plan are untracked, so they come along.
- [ ] **Step 2:** Have a fresh reviewer read `plan.md` against ADR 0026, `prek.toml` and the dry-run table. Then commit `work/2026-11/462_prek-builtins/README.md` and `plan.md` as `docs(work): plan the prek built-ins stack (#462)`, with a `Fresh-review: <what it read>` trailer.

### Task 1 (layer 1): Upgrade prek and replace `diff-check`

**Files:**
- Modify: `mise.toml` (the `prek` pin; delete `[tasks.diff-check]`)
- Modify: `mise.lock`
- Modify: `prek.toml`
- Modify: `.github/workflows/ci.yml` (drop `diff-check` from `SKIP`, and its mention in the step comment)
- Modify: `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md`
- Modify: `docs/development.md` (the `diff-check` row in the task table, and any prose naming it)
- Test: `tests/test_prek_config.py`, `tests/test_prek_hooks.py`

- [ ] **Step 1: Update the config tests (they go red).** In `test_prek_config.py`:
  - drop `"diff-check"` from `LOCAL_HOOKS`;
  - replace the `BUILTINS` set with `BUILTINS: dict[str, dict[str, Any]]`, mapping each id to its exact table minus `id`;
  - make `test_builtin_hooks_are_the_adr_set` assert `{h["id"]: {k: v for k, v in h.items() if k != "id"} for h in _hooks("builtin")} == BUILTINS`, so that args and excludes are pinned too;
  - delete the `tasks["diff-check"]` assertion in `test_pre_commit_task_runs_prek`;
  - update the module comment. The new entries:

  ```python
  EXEMPT = "^(tests/fixtures|work)/"
  "trailing-whitespace": {"args": ["--check", "--markdown-linebreak-ext=md"], "exclude": EXEMPT},
  "end-of-file-fixer": {"args": ["--check"], "exclude": EXEMPT},
  "check-added-large-files": {"args": ["--enforce-all"]},
  "check-merge-conflict": {"args": ["--assume-in-merge"]},
  "check-shebang-scripts-are-executable": {"exclude": r"(\.rs$|^work/)"},
  # the other six existing built-ins (windows-names, case-conflict, toml, yaml, private-key,
  # executables-have-shebangs) map to {}
  ```

- [ ] **Step 2: Add the integration tests (they go red).** In `test_prek_hooks.py`:
  - Extend `test_ci_built_ins_catch_a_committed_change` with two params, `("notes.txt", "a \n")` (id `trailing-whitespace`) and `("notes.txt", "a")` (id `missing-final-newline`).
  - Add `test_ci_built_ins_pass_exempt_content`, built the same way. It is parametrized over `("breaks.md", "a  \nb\n")`, `("tests/fixtures/x.flm", "a")` and `("work/2026-01/1_x/journal.md", "a \n")`, and asserts `returncode == 0`.
  - Add `test_check_mode_leaves_the_file_alone`: stage `notes.txt` = `"a \n"` with a plain `prek run --config prek.toml`, then assert that the run fails and that the file's bytes are still `b"a \n"`.
  - Create parent directories before writing the files.
- [ ] **Step 3:** Run `mise run test-py -- tests/test_prek_config.py tests/test_prek_hooks.py`. Expected: the new and changed tests fail.
- [ ] **Step 4: Bump prek.** Run `mise use prek@0.5.10`.
  - Check that `git diff mise.lock` shows `v0.5.10` URLs for both `linux-x64` and `windows-x64`. If one is missing, run `mise lock --platform linux-x64,windows-x64 prek`.
  - Check that `mise exec -- prek --version` prints `prek 0.5.10`.
- [ ] **Step 5: Edit `prek.toml`.**
  - Delete the `diff-check` local hook.
  - Add `trailing-whitespace` and `end-of-file-fixer` to the builtin repo exactly as `BUILTINS` says.
  - Extend the comment above the built-ins: the two fixers run with `--check`, so they rewrite nothing, and fixtures and work folders are exempt.
- [ ] **Step 6:** Delete `[tasks.diff-check]` from `mise.toml`. Edit `ci.yml`: the `SKIP` list loses `diff-check`, and the comment stops citing it. Grep `git grep -n diff-check -- ':!work/'` and fix each remaining hit in the files listed above.
- [ ] **Step 7: Amend ADR 0026.**
  - Add a dated Status note.
  - Remove the `diff-check` row from the local-hook table, and drop `diff-check` from the "run on every commit" sentence.
  - Add a built-in table row: `trailing-whitespace`, `end-of-file-fixer` back `.editorconfig`'s whitespace rules.
  - Reword "No hook rewrites files" to say that the two fixers run in `--check` mode.
  - Update the CI `SKIP` text.
  - Append an `## Amendment 2026-11-xx` section that gives the `diff-check` and `crlf-check` verdicts from **Decisions**, with the rejected options.
- [ ] **Step 8:** Rerun Step 3's command. Expected: PASS. Then run `mise run check`. Expected: PASS with no warnings.
- [ ] **Step 9:** Have a fresh reviewer read the `docs/development.md` and ADR diff. Then commit the files above by name, as `build(hooks): upgrade prek to 0.5.10 and replace diff-check with built-ins (#462)`.

### Task 2 (layer 2): Fix the flagged files

**Files:**
- Modify: `docs/adr/0021-capture-chooses-its-control-port.md` (trailing whitespace)
- Modify: `research/formats/sod-opcodes.md` and `LICENSE-CC-BY-4.0` (final newline)
- Modify: `docs/agents/issue-tracker.md:15` (`#L12` becomes `#L<n>`)

- [ ] **Step 1:** Run `gh stack add style/prek-findings`.
- [ ] **Step 2:** Write the layer-3 `prek.toml` built-ins to a scratch config, plus the layer-1 ones, then run `mise exec -- prek run --config <scratch> --all-files`. Expected: only the four paths above fail. Any other hit is new since 2026-11-13: fix it here, or add it to the exemption decision and say so in the PR.
- [ ] **Step 3:** Make the four edits. Whitespace and newline edits change bytes only. For the permalink, the example still reads as a placeholder (`.../blob/<sha>/<path>#L<n>`).
- [ ] **Step 4:** Rerun Step 2's command. Expected: every hook passes. Then run `mise run check`. Expected: PASS.
- [ ] **Step 5:** Have a fresh reviewer read the diff, as rule 5 requires because of `research/`. Then commit the four paths as `style: fix whitespace, final newlines and a permalink the prek built-ins flag (#462)`.

### Task 3 (layer 3): Add the new built-ins

**Files:**
- Modify: `prek.toml`
- Modify: `docs/adr/0026-commit-hooks-run-the-gates-own-tasks.md`
- Modify: `work/2026-11/462_prek-builtins/README.md` (`outcome`)
- Test: `tests/test_prek_config.py`, `tests/test_prek_hooks.py`

- [ ] **Step 1:** Run `gh stack add build/prek-new-builtins`.
- [ ] **Step 2: Extend `BUILTINS` (the test goes red).**

  ```python
  "check-symlinks": {}, "destroyed-symlinks": {}, "check-json": {},
  "fix-byte-order-marker": {"args": ["--check"], "exclude": EXEMPT},
  "check-vcs-permalinks": {}, "forbid-new-submodules": {},
  ```

- [ ] **Step 3: Add the CI-range tests (they go red).**
  - Extend `test_ci_built_ins_catch_a_committed_change` with three params:
    - `("bad.json", "{")` (id `json`);
    - `("bom.txt", "﻿a\n")` (id `bom`);
    - `("doc.md", "https://github.com/o/r/blob/main/f.py#L3\n")` (id `permalink`).
  - If the BOM param writes through `write_text`, pass `encoding="utf-8"`; the `﻿` character supplies the BOM bytes.
- [ ] **Step 4:** Run `mise run test-py -- tests/test_prek_config.py tests/test_prek_hooks.py`. Expected: the new params fail.
- [ ] **Step 5:** Add the five hooks to `prek.toml`'s builtin repo exactly as `BUILTINS` says. Check that `mise exec -- prek run --config prek.toml --all-files` reports no config error.
- [ ] **Step 6:** Add ADR 0026 built-in table rows with the rule each backs:
  - symlinks: `.claude/skills` is a committed symlink, and a Windows checkout without `core.symlinks` turns it into a text file;
  - BOM: PowerShell 5.1 `Out-File` writes one;
  - JSON: the configuration and fixtures;
  - permalinks: the issue and research citations;
  - submodules: the repository has none.
  
  Also note that `destroyed-symlinks` reads `git status`, so in CI it passes unread. Its coverage is the commit hook.
- [ ] **Step 7:** Rerun Step 4's command. Expected: PASS. Then run `mise run check`. Expected: PASS.
- [ ] **Step 8:** Write the README `outcome`, then commit `prek.toml`, the ADR, both tests and the README as `build(hooks): add symlink, BOM, JSON, permalink and submodule built-ins (#462)`.

### Task 4: Submit

- [ ] **Step 1:** Run `gh stack submit --auto`, then `gh stack view --json`. Expected: three draft PRs, bottom to top. Write each body with the `pr` skill. Layer 3's body closes #462.
- [ ] **Step 2:** Merge the stack together with `gh stack merge <layer-3 PR> --yes`. Merging layer 1 alone would fail commits that touch the three unfixed files until layer 2 lands.
