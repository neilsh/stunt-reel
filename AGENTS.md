# AGENTS.md — Stunt Reel AI Developer Guide

`stunt-reel` is a format analysis, documentation, modern reconstruction, and tooling environment for ***Stunt Island*** (1992, Walt Disney Computer Software / The Assembly Line).

---

## 1. Non-Negotiable Directives

1. **Asset isolation**: **NEVER** commit proprietary assets, executables, or original binary disks into Git (`corpus/` is strictly gitignored). All tests must run 100% offline using synthetic fixtures in [`tests/fixtures/`](tests/fixtures/README.md). Two small game-derived tables, and illustrative comparison images (a captured frame beside our render, cited by a research note), are documented exceptions under the rules in [`NOTICE.md`](NOTICE.md).
2. **Quality Gate Requirement**: Before concluding any task or presenting code, **always verify that `mise run check` passes** (format check, lint, typecheck, test across both Rust and Python). See [`docs/development.md`](docs/development.md#development--quality-assurance) and [`mise.toml`](mise.toml).
3. **Architectural Invariants**: All code conforms to `[I1]` coordinates, `[I2]` flat arena, `[I3]` VGA palette indices, `[I4]` 50 Hz ticks, `[I5]` coplanar decals, `[I6]` parity thresholds, `[I7]` asset isolation and a pure `stunt-core`, `[I8]` 8.3 paths, defined in [`docs/SPEC.md` § 2](docs/SPEC.md#2-system-architectural-invariants--guardrails) and summarized in [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs).

---

## 2. Documentation Directory & Single Sources of Truth

Refer directly to authoritative documents rather than duplicating definitions:

| Domain | Source of Truth | Summary |
|---|---|---|
| **Domain Glossary** | [`GLOSSARY.md`](GLOSSARY.md) | Canonical project vocabulary. |
| **System Specification** | [`docs/SPEC.md`](docs/SPEC.md) | Goals, invariants, evidentiary tiers, verification matrix; no binary-analysis findings. |
| **Architecture & 1-Hop Routing** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code path → governing anchors and research notes. |
| **Anchor Registry** | [`python/stunt_reel/doc_anchors.py`](python/stunt_reel/doc_anchors.py) | Every `[I*]`, `# [FMT-*]` and `# [MEM-*]` token and the heading that defines it. |
| **Runtime Memory Map** | [`research/playone-exe/memory-map.md`](research/playone-exe/memory-map.md) | `DGROUP` offset tables and memory anchors (`# [MEM-*]`). |
| **Seam Contracts** | [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs) | Seams 1–4: VFS, trajectory, shape, capture and compare. |
| **Project Setup & Tasks** | [`README.md`](README.md), [`docs/development.md`](docs/development.md) & [`mise.toml`](mise.toml) | Prerequisites and every task; `mise tasks` is the live list. |
| **Repository Layout** | [`docs/development.md`](docs/development.md#project-structure) | Crates, tooling directories, asset storage rules. |
| **Synthetic Fixtures** | [`tests/fixtures/README.md`](tests/fixtures/README.md) | Synthetic mock files and their byte specs. |
| **Reference Corpus** | [`corpus/README.md`](corpus/README.md) | Upstream demo archive and community package layout. |
| **Binary Disassembly** | [`research/playone-exe/`](research/playone-exe/) | Evidence for `PLAYONE.EXE`, routed by [`research/README.md`](research/README.md). |
| **Format Specs & Byte Layouts** | [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog; byte layouts live only in the `.ksy` schemas. |
| **Research Routing** | [`research/README.md`](research/README.md) | Where each kind of finding goes, and note shape. |
| **Parity** | [`research/parity/`](research/parity/) | Method, dated log, attribution and render-model notes. |
| **Issues & skill configuration** | [`docs/agents/`](docs/agents/) | GitHub Issues via `gh`, triage labels, domain docs; review threads with `mise run pr-threads -- <number>`. |
| **Decisions (ADRs)** | [`docs/adr/`](docs/adr/) | One file per accepted design decision. |
| **Coding & Format Rules** | [`Cargo.toml`](Cargo.toml), [`pyproject.toml`](pyproject.toml), [`.editorconfig`](.editorconfig) | Clippy, Ruff and Mypy settings; LF, 4-space indent. |
| **Agents & Harnesses** | [`docs/harness.md`](docs/harness.md) | Agent policy, then per-harness sandbox, shell, approval and subagent notes. |
| **Harness Setup** | [`docs/harness-setup.md`](docs/harness-setup.md) | Machine-local setup: tools, mise trust, data root, worktree placement. |

Process documents, **not** sources of truth: [`docs/process/TEAM_SHEET.md`](docs/process/TEAM_SHEET.md) (roles, file blast radii, ticket status), under [`docs/process/`](docs/process/). Never cite them for a fact about the system.

---

## 3. Working Rules

### Committing

1. Run `git status` before staging: stage the paths you changed by name, never `git add -A` or `git commit -a`, and never any file from `corpus/`. If the index holds another session's work, stop and ask.
2. Run `mise run check` and see it pass with zero warnings or errors.
3. Commit with a Conventional Commit subject, e.g. `feat(core): add a parser`. The commit-msg hook (`mise run commit-msg-check`) checks the subject and the closing gate line. Write the body whenever a reviewer would have to ask "why this way?": what forced the change, the cause with the offset, measurement or log row that proves it, and what you rejected. One paragraph, then a bullet per file when several move together; never retell the diff. Renames, formatting and generated files need none. Longer reasoning belongs in the owning note or an ADR, cited from the body. Close with `mise run check passes.` when the whole gate ran, naming any part that did not.
4. Write the handoff into the plan or `research/` note that owns the work item, never only in agent memory, which another worktree never sees. Shared append-only files such as [`research/parity/log.md`](research/parity/log.md) take rows at the end only.
5. A PR that changes rendered output carries a capture-beside-render picture, before and after: [Evidence for a rendering PR](.agents/skills/improving-render-parity/SKILL.md#evidence-for-a-rendering-pr).

### Working economically

Each turn re-sends the whole conversation, so cost is roughly turns times context size.

1. **Fewer, fuller turns.** Batch independent reads and commands into one turn. Find the file through [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before grepping, and read line ranges of files over about 20 KB. Reach a file with `read` and a string with `grep`/`glob`, not a shell.
2. **Scoped checks while iterating.** For Python, `mise run fix`, then `mise run lint-py` and `mise run typecheck`, then `mise run test-py -- <test file>`. For Rust, `mise run check-rust`. Run the full `mise run check` once, before you commit, hand off or call the task done, and `check-py` or `check-rust` to re-run a half that failed.
3. **Scripts before subagents.** Mechanical checks belong in a script. Delegate only real chunks of work, at most about 8 subagents per task, each with a whole brief: goal, paths, output shape, stopping condition ([`docs/harness.md`](docs/harness.md)).
4. **Drive everything through `mise run`.** `mise run *` is the one command shape the harness pre-approves and `mise tasks` the one list of what exists; a task name not there does not exist. For a one-off, `mise exec -- uv run …` runs the pinned uv (expect an approval prompt); a command needed twice earns a task. A bare `uv` may not be the pinned version.

### Worktrees

1. One writer per checkout path, one branch per worktree, made inside the primary checkout under `.claude/worktrees/` or `.agents/worktrees/` (Orca workspaces excepted). A read-only scout may share a path; two writers must not. Never work on a branch another worktree holds.
2. A worktree the tool that made it cannot remove is reaped with `mise run reap -- --yes` from the primary checkout, which unlinks old data-root links first and waits for low disk space. Never call `git worktree remove` yourself on a worktree `mise run init` linked: it has deleted shared data through Windows junctions ([ADR 0018](docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).
