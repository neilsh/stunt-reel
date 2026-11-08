# AGENTS.md — Stunt Reel AI Developer Guide

`stunt-reel` analyses, documents and reconstructs ***Stunt Island*** (1992).

---

## 1. Non-Negotiable Directives

1. **Asset isolation**: **NEVER** commit proprietary assets, executables, or original binary disks (`corpus/` is gitignored). All tests run offline on synthetic fixtures in [`tests/fixtures/`](tests/fixtures/README.md). Documented exceptions follow [`NOTICE.md`](NOTICE.md).
2. **Quality gate**: Before concluding a task or presenting code, **verify that `mise run check` passes**: format, lint, typecheck and tests for the halves your branch touches; `-- --full` and CI run everything ([ADR 0038](docs/adr/0038-the-local-gate-runs-what-a-change-touches.md)).
3. **Architectural Invariants**: Code conforms to `[I1]`–`[I8]` (coordinates, flat arena, palette indices, 50 Hz ticks, coplanar decals, parity thresholds, a pure `stunt-core`, 8.3 paths), defined in [`docs/SPEC.md` § 2](docs/SPEC.md#2-system-architectural-invariants--guardrails).
4. **Evergreen or dated**: a current fact goes in `research/` or `docs/` and is rewritten in place; a dated record goes in [`work/`](work/README.md) and is frozen once its work lands. A new finding, ruled-out hypotheses included, lands in its note by [`research/README.md`](research/README.md), committed with the code that relies on it. Read [`recording-findings`](.agents/skills/recording-findings/SKILL.md) first.

---

## 2. Sources of Truth

Cite these; never restate them:

| Domain | Source of Truth | Summary |
|---|---|---|
| **Domain Glossary** | [`GLOSSARY.md`](GLOSSARY.md) | Project vocabulary. |
| **System Specification** | [`docs/SPEC.md`](docs/SPEC.md) | Goals, invariants, evidentiary tiers, verification matrix. |
| **Architecture & 1-Hop Routing** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code path → governing anchors and research notes. |
| **Anchor Registry** | [`python/stunt_reel/doc_anchors.py`](python/stunt_reel/doc_anchors.py) | Where each `[I*]`, `[FMT-*]`, `[MEM-*]` anchor is defined. |
| **Runtime Memory Map** | [`research/playone-exe/memory-map.md`](research/playone-exe/memory-map.md) | `DGROUP` offsets and `[MEM-*]` anchors. |
| **Seam Contracts** | [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs) | Seams 1–4: VFS, trajectory, shape, capture and compare. |
| **Project Setup & Tasks** | [`README.md`](README.md), [`docs/development.md`](docs/development.md) & [`mise.toml`](mise.toml) | Prerequisites and every task. |
| **Reference Corpus** | [`corpus/README.md`](corpus/README.md) | Demo archive and community packages. |
| **Knowledge Map** | [`research/MAP.md`](research/MAP.md) | Each research note's summary. |
| **Binary Disassembly** | [`research/playone-exe/`](research/playone-exe/) | Evidence for `PLAYONE.EXE`. |
| **Format Specs & Byte Layouts** | [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog; byte layouts live only in `.ksy` schemas. |
| **Parity** | [`research/parity/`](research/parity/) | Method, attribution and render-model notes. |
| **Work Items** | GitHub issues, [`work/README.md`](work/README.md) | Issue status; folder layout. |
| **How-to Guides** | `docs/howto/` | One task per file. |
| **Issues & skill configuration** | [`docs/agents/`](docs/agents/) | GitHub Issues via `gh`, triage labels, domain docs, review threads (`mise run pr-threads`). |
| **Decisions (ADRs)** | [`docs/adr/`](docs/adr/) | Accepted design decisions. |
| **Coding & Format Rules** | [`Cargo.toml`](Cargo.toml), [`pyproject.toml`](pyproject.toml), [`.editorconfig`](.editorconfig) | Clippy, Ruff and Mypy settings; LF, 4-space indent. |
| **Agents & Harnesses** | [`docs/harness.md`](docs/harness.md), [`docs/harness-setup.md`](docs/harness-setup.md) | Agent policy, per-harness notes, machine setup and the data root. |

Dated records (`work/<YYYY-MM>/`) are **not** a source of truth: never cite one for a fact about the system. Run `mise run work -- new` before `superpowers:brainstorming` or `writing-plans` writes a file, and write into the folder it makes. Search `work/` with `path: work/` or `rg --no-ignore-dot`.

---

## 3. Working Rules

### Committing

1. Run `git status` before staging: stage the paths you changed by name, never `git add -A` or `git commit -a`, and never any file from `corpus/`. If the index holds another session's work, stop and ask.
2. Run `mise run check`; it must pass with no warnings.
3. Commit with a Conventional Commit subject and, when a reviewer would ask "why this way?", a body that says why, closing with the gate line `mise run check` prints last: [Commit messages](docs/development.md#commit-messages). The commit-msg hook checks both.
4. Write the handoff into the work folder's README or on the issue, never only in agent memory; the finishing PR writes the README's `outcome`.
5. A PR that changes rendered output carries a capture-beside-render picture, before and after: [Evidence for a rendering PR](.agents/skills/improving-render-parity/pr-evidence.md).
6. A finding that needs a code fix is recorded on the fix's branch, cut from `main`, after checking the open PRs that touch the same note; a verification branch keeps only its journal entry, stacked on the fix branch when it links a note the fix adds.
7. Before a push that changes `research/` or `NOTICE.md`, a fresh reviewer (a subagent in an agent session, another person otherwise) reads the diff and the notes it cites and reports any claim broader than its evidence (`only`, `all`, `noise`, `within`, `equivalent`).
8. Work that ships as two or more dependent PRs is a `gh stack` from its first branch: `gh stack init <bottom> <next>…`, then `gh stack submit --auto`.
9. A commit from another session's branch keeps its author, which the pre-push hook rejects: [re-commit it](docs/development.md#a-commit-from-another-sessions-branch).

### Working economically

Each turn re-sends the conversation, so cost is roughly turns times context size.

1. **Fewer, fuller turns.** Batch independent reads and commands into one turn. Find the file through [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before grepping, and read line ranges of files over about 20 KB.
2. **Scoped checks while iterating.** Python: `mise run fix`, `lint-py`, `typecheck`, then `test-py -- <test file>`. Rust: `mise run check-rust`. Run `mise run check` once before you commit, hand off or call the task done, and re-run only the half it names as failed.
3. **Scripts before subagents.** Mechanical checks belong in a script. Delegate only real chunks of work, at most about 8 subagents per task, each with a whole brief: goal, paths, output shape, stopping condition.
4. **Drive everything through `mise run`.** `mise run *` is pre-approved and `mise tasks` lists what exists; a task not listed does not exist. A one-off runs as `mise exec -- uv run …` (expect a prompt); a command needed twice earns a task.

### Docstrings

A docstring or `///` comment states the caller's contract in the fewest words: [Docstrings and doc comments](docs/development.md#docstrings-and-doc-comments).

### Skills

Before work one covers, read its skill:

- **Seam contracts**: a type, field or parser under `crates/stunt-core/src/contracts/`, or its fixtures: [`changing-seam-contracts`](.agents/skills/changing-seam-contracts/SKILL.md).
- **Worktrees and the data root**: making, removing or reaping a worktree, or finding the corpus or a capture: [`managing-worktrees`](.agents/skills/managing-worktrees/SKILL.md).
- **Render parity**: parity, SSIM, IoU, capture, probe or sweep work: [`improving-render-parity`](.agents/skills/improving-render-parity/SKILL.md).

### Worktrees

1. One writer per checkout path, one branch per worktree, made inside the primary checkout under `.claude/worktrees/` or `.agents/worktrees/` (Orca workspaces excepted). A read-only scout may share a path. Never work on a branch another worktree holds.
2. Remove a worktree an older `mise run init` linked only with `mise run reap -- --yes` from the primary checkout, never `git worktree remove`: git has deleted shared data through its junctions ([ADR 0018](docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)).
