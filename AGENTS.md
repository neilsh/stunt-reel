# AGENTS.md — Stunt Reel AI Developer Guide

`stunt-reel` is a format analysis, documentation, modern reconstruction, and tooling environment for ***Stunt Island*** (1992, Walt Disney Computer Software / The Assembly Line).

---

## 1. Non-Negotiable Directives

1. **Asset isolation**: **NEVER** commit proprietary assets, executables, or original binary disks into Git (`corpus/` is strictly gitignored). All tests must run 100% offline using synthetic fixtures in [`tests/fixtures/`](tests/fixtures/README.md). Two small game-derived tables, and illustrative comparison images (a captured frame beside our render, cited by a research note), are documented exceptions under the rules in [`NOTICE.md`](NOTICE.md).
2. **Quality Gate Requirement**: Before concluding any task or presenting code, **always verify that `mise run check` passes**. It runs format, lint, typecheck and tests for the halves your branch touches, and everything on `mise run check -- --full`; CI runs everything on every pull request ([ADR 0038](docs/adr/0038-the-local-gate-runs-what-a-change-touches.md)). See [`docs/development.md`](docs/development.md#development--quality-assurance) and [`mise.toml`](mise.toml).
3. **Architectural Invariants**: All code conforms to `[I1]` coordinates, `[I2]` flat arena, `[I3]` VGA palette indices, `[I4]` 50 Hz ticks, `[I5]` coplanar decals, `[I6]` parity thresholds, `[I7]` asset isolation and a pure `stunt-core`, `[I8]` 8.3 paths, defined in [`docs/SPEC.md` § 2](docs/SPEC.md#2-system-architectural-invariants--guardrails) and summarized in [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs).
4. **Findings live in `research/`**: every new format, rendering or render-residual finding, ruled-out hypotheses included, lands in the note that owns it by [`research/README.md`](research/README.md), in the same commit as the code that relies on it. Read the [`recording-findings`](.agents/skills/recording-findings/SKILL.md) skill first.

---

## 2. Documentation Directory & Single Sources of Truth

Refer directly to authoritative documents rather than duplicating definitions:

| Domain | Source of Truth | Summary |
|---|---|---|
| **Domain Glossary** | [`GLOSSARY.md`](GLOSSARY.md) | Canonical project vocabulary. |
| **System Specification** | [`docs/SPEC.md`](docs/SPEC.md) | Goals, invariants, evidentiary tiers, verification matrix; no binary-analysis findings. |
| **Architecture & 1-Hop Routing** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code path → governing anchors and research notes. |
| **Anchor Registry** | [`python/stunt_reel/doc_anchors.py`](python/stunt_reel/doc_anchors.py) | Where each `[I*]`, `[FMT-*]` and `[MEM-*]` anchor is defined. |
| **Runtime Memory Map** | [`research/playone-exe/memory-map.md`](research/playone-exe/memory-map.md) | `DGROUP` offsets and `[MEM-*]` anchors. |
| **Seam Contracts** | [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs) | Seams 1–4: VFS, trajectory, shape, capture and compare. |
| **Project Setup & Tasks** | [`README.md`](README.md), [`docs/development.md`](docs/development.md) & [`mise.toml`](mise.toml) | Prerequisites and every task; `mise tasks` is the live list. |
| **Reference Corpus** | [`corpus/README.md`](corpus/README.md) | Demo archive and community packages. |
| **Binary Disassembly** | [`research/playone-exe/`](research/playone-exe/) | Evidence for `PLAYONE.EXE`, routed by [`research/README.md`](research/README.md). |
| **Format Specs & Byte Layouts** | [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog; byte layouts live only in `.ksy` schemas. |
| **Parity** | [`research/parity/`](research/parity/) | Method, dated log, attribution and render-model notes. |
| **Issues & skill configuration** | [`docs/agents/`](docs/agents/) | GitHub Issues via `gh`, triage labels, domain docs; review threads: `mise run pr-threads -- <number>` lists them, `--reply`/`--resolve` answer them, `--all` adds outside-diff findings. |
| **Decisions (ADRs)** | [`docs/adr/`](docs/adr/) | Accepted design decisions. |
| **Coding & Format Rules** | [`Cargo.toml`](Cargo.toml), [`pyproject.toml`](pyproject.toml), [`.editorconfig`](.editorconfig) | Clippy, Ruff and Mypy settings; LF, 4-space indent. |
| **Agents & Harnesses** | [`docs/harness.md`](docs/harness.md) | Agent policy and per-harness notes. |
| **Harness Setup** | [`docs/harness-setup.md`](docs/harness-setup.md) | Machine-local setup and the data root. |

Process documents, **not** sources of truth: [`docs/process/TEAM_SHEET.md`](docs/process/TEAM_SHEET.md) (roles, file blast radii, ticket status), under [`docs/process/`](docs/process/). Never cite them for a fact about the system.

---

## 3. Working Rules

### Committing

1. Run `git status` before staging: stage the paths you changed by name, never `git add -A` or `git commit -a`, and never any file from `corpus/`. If the index holds another session's work, stop and ask.
2. Run `mise run check` and see it pass with zero warnings or errors.
3. Commit with a Conventional Commit subject, e.g. `feat(core): add a parser`. The commit-msg hook (`mise run commit-msg-check`) checks the subject, and holds the closing gate line to a passing run on the staged tree ([how](docs/development.md#the-gate-line-is-checked)). Write the body whenever a reviewer would have to ask "why this way?": what forced the change, the cause with the offset, measurement or log row that proves it, and what you rejected. One paragraph, then a bullet per file when several move together; never retell the diff. Renames, formatting and generated files need none. Longer reasoning belongs in the owning note or an ADR, cited from the body. Close with the gate line a passing `mise run check` prints last, such as `mise run check passes.` or `mise run check-docs passes; check-rust not run; check-py not run.`
4. Write the handoff into the plan or `research/` note that owns the work item, never only in agent memory, which another worktree never sees. Shared append-only files such as [`research/parity/log.md`](research/parity/log.md) take rows at the end only.
5. A PR that changes rendered output carries a capture-beside-render picture, before and after: [Evidence for a rendering PR](.agents/skills/improving-render-parity/SKILL.md#evidence-for-a-rendering-pr).
6. A finding that needs a code fix is recorded on the fix's branch, cut from `main`, after checking the open PRs that touch the same note; a verification branch keeps only its log row, and a row that links a note the fix adds waits until the fix is merged, or stacks on the fix branch, so the docs link check finds the note.
7. Before a push that changes `research/` or `NOTICE.md`, a fresh reviewer (a subagent in an agent session, another person otherwise) reads the diff and the notes it cites and reports any claim broader than its evidence (`only`, `all`, `noise`, `within`, `equivalent`).
8. Answer a review round with one push: address every comment it raised (fix it, or reply with why not), run the gate once, then push.
6. Work that ships as two or more dependent PRs is a `gh stack` from its first branch: `gh stack init <bottom> <next>…`, then `gh stack submit --auto`.
7. A commit taken from another session's branch (a cloud session's) keeps that session's author, which the pre-push hook rejects: in a clean checkout (`git status --porcelain` prints nothing, since the gate tests untracked and unstaged files too), `git cherry-pick --no-commit <sha>`, run `mise run check -- --full` on the picked tree, then `git commit -F <message>` (the author is you: `--no-commit` carries no author over) with `<sha>`'s message, its gate line replaced by the one the gate printed, so the commit hooks check the picked changes and the gate line states this run.

### Working economically

Each turn re-sends the whole conversation, so cost is roughly turns times context size.

1. **Fewer, fuller turns.** Batch independent reads and commands into one turn. Find the file through [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before grepping, and read line ranges of files over about 20 KB.
2. **Scoped checks while iterating.** For Python, `mise run fix`, then `mise run lint-py` and `mise run typecheck`, then `mise run test-py -- <test file>`. For Rust, `mise run check-rust`. Run `mise run check` once, before you commit, hand off or call the task done, and the `check-py`, `check-rust` or `check-docs` it names to re-run a half that failed.
3. **Scripts before subagents.** Mechanical checks belong in a script. Delegate only real chunks of work, at most about 8 subagents per task, each with a whole brief: goal, paths, output shape, stopping condition.
4. **Drive everything through `mise run`.** `mise run *` is the one command shape the harness pre-approves and `mise tasks` the one list of what exists; a task name not there does not exist. For a one-off, `mise exec -- uv run …` runs the pinned uv (expect an approval prompt); a command needed twice earns a task.

### Docstrings

Writing or editing a docstring or `///` comment: state the caller's contract in the fewest words, by [Docstrings and doc comments](docs/development.md#docstrings-and-doc-comments).

### Skills

Before work one covers, read its skill:

- **Seam contracts**: a type, field or parser under `crates/stunt-core/src/contracts/`, or its fixtures: [`changing-seam-contracts`](.agents/skills/changing-seam-contracts/SKILL.md).
- **Worktrees and the data root**: making, removing or reaping a worktree, or finding the corpus or a capture: [`managing-worktrees`](.agents/skills/managing-worktrees/SKILL.md).
- **Render parity**: parity, SSIM, IoU, capture, probe or sweep work: [`improving-render-parity`](.agents/skills/improving-render-parity/SKILL.md).

### Worktrees

1. One writer per checkout path, one branch per worktree, made inside the primary checkout under `.claude/worktrees/` or `.agents/worktrees/` (Orca workspaces excepted). A read-only scout may share a path; two writers must not. Never work on a branch another worktree holds.
2. Remove a worktree an older `mise run init` linked only with `mise run reap -- --yes` from the primary checkout, never `git worktree remove`: git has deleted shared data through its junctions ([ADR 0018](docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).
