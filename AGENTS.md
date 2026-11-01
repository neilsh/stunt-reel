# AGENTS.md — Stunt Reel AI Developer Guide

`stunt-reel` is a format analysis, documentation, modern reconstruction, and tooling environment for ***Stunt Island*** (1992, Walt Disney Computer Software / The Assembly Line).

---

## 1. Non-Negotiable Directives

1. **Asset isolation**: **NEVER** commit proprietary assets, executables, or original binary disks into Git (`corpus/` is strictly gitignored). All tests must run 100% offline using synthetic fixtures in [`tests/fixtures/`](tests/fixtures/README.md). Two small game-derived tables, and illustrative comparison images (a captured frame beside our render, cited by a research note), are documented exceptions under the rules in [`NOTICE.md`](NOTICE.md).
2. **Quality Gate Requirement**: Before concluding any task or presenting code, **always verify that `mise run check` passes** (format check, lint, typecheck, test across both Rust and Python). See [`docs/development.md`](docs/development.md#development--quality-assurance) and [`mise.toml`](mise.toml).
3. **Architectural Invariants**: All code must conform to system invariants `[I1]`–`[I8]` defined in [`docs/SPEC.md` § 2](docs/SPEC.md#2-system-architectural-invariants--guardrails) (summarized in [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs)):
   - `[I1]` Right-handed metric coordinates (`+X` Right, `+Y` Up, `+Z` Backward, `-Z` Forward).
   - `[I2]` Flat arena allocation (`Vec<SodNode>` indexed by `NodeId(u32)`; no `Rc<RefCell<T>>`).
   - `[I3]` Authentic 8-bit VGA Mode 13h palette index color mapping (`0..=255`).
   - `[I4]` Discrete 50 Hz authored simulation ticks with sub-tick interpolation.
   - `[I5]` Coplanar decal identification and normal displacement nudging.
   - `[I6]` Visual parity thresholds (SSIM $\ge 0.88$ initial / $\ge 0.90$ sign-off).
   - `[I7]` Asset isolation (with the documented palette/scale-table exception) and a `stunt-core` limited to small, pure-Rust dependencies (no I/O, windowing, GPU, audio, or emulator).
   - `[I8]` DOS 8.3 uppercase path normalization in virtual filesystems.

---

## 2. Documentation Directory & Single Sources of Truth

Refer directly to authoritative documents rather than duplicating definitions:

| Domain | Source of Truth | Summary |
|---|---|---|
|**Domain Glossary**|[`GLOSSARY.md`](GLOSSARY.md)|Canonical project vocabulary: film, slice, tick, trajectory record, epilogue, shape, slot, partial SOD.|
|**System Specification**|[`docs/SPEC.md`](docs/SPEC.md)|Goals, scope, mathematical invariants (`[I1]`–`[I8]`), evidentiary tiers, and the master verification matrix. No binary-analysis findings.|
| **Architecture & 1-Hop Routing** | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Code path → governing anchors and research notes, with real links. |
| **Anchor Registry** | [`python/stunt_reel/doc_anchors.py`](python/stunt_reel/doc_anchors.py) | Every `[I*]`, `# [FMT-*]` and `# [MEM-*]` token and the one heading that defines it; `tests/test_doc_invariants.py` checks both directions. |
| **Runtime Memory Map** | [`research/playone-exe/memory-map.md`](research/playone-exe/memory-map.md) | `DGROUP` (`0x0D51`) offset reference tables, real-mode linear translation, and memory anchors (`# [MEM-*]`). |
| **Seam Contracts** | [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs) | Contract boundaries: [`vfs`](crates/stunt-core/src/contracts/vfs.rs) (Seam 1), [`trajectory`](crates/stunt-core/src/contracts/trajectory.rs) (Seam 2), [`shape`](crates/stunt-core/src/contracts/shape.rs) (Seam 3), and Seam 4, capture and compare: [`palette`](crates/stunt-core/src/contracts/palette.rs), frames from `stunt-render`, and the `stuntreel parity` subcommand in [`crates/stunt-cli/src/parity/`](crates/stunt-cli/src/parity/). |
| **Project Setup & Tasks** | [`README.md`](README.md), [`docs/development.md`](docs/development.md) & [`mise.toml`](mise.toml) | Environment prerequisites, and every task with its command — run `mise tasks` for the live list. The gate is `mise run check` ([gate.py](python/scripts/gate.py), [ADR 0014](docs/adr/0014-the-gate-is-one-ordered-script.md), [ADR 0016](docs/adr/0016-the-gate-runs-independent-lanes.md)): one line per step over concurrent lanes, PASS/FAIL, log in `target/check.log`. |
| **Repository Layout** | [`docs/development.md`](docs/development.md#project-structure) | Workspace crate locations, tooling directories, and asset storage rules. |
| **Synthetic Fixtures** | [`tests/fixtures/README.md`](tests/fixtures/README.md) | Synthetic mock files (`.res`, `.flm`, `.json`) and binary specifications. |
| **Reference Corpus** | [`corpus/README.md`](corpus/README.md) | Upstream demo archive and community developer package structure (`stisldem/`, `siarchive/`). |
| **Binary Disassembly (Lab Notebook)** | [`research/playone-exe/`](research/playone-exe/) | Evidence for `PLAYONE.EXE`: [`startup.md`](research/playone-exe/startup.md) (image, entry, gates), [`navigation.md`](research/playone-exe/navigation.md) (dialog, input), [`memory.md`](research/playone-exe/memory.md) (offset evidence; tables are in [`memory-map.md`](research/playone-exe/memory-map.md)), [`capture.md`](research/playone-exe/capture.md) (retired DOSBox-X harness; the current one is [`capture-dosbox-automation.md`](research/playone-exe/capture-dosbox-automation.md)), [`dosbox-x-legacy.md`](research/playone-exe/dosbox-x-legacy.md) (what the DOSBox-X harness established), [`patch3.md`](research/playone-exe/patch3.md) (Patch #3 builds and their offsets), [`sod-vm.md`](research/playone-exe/sod-vm.md) (display-list VM, `OP_TAP`), [`sod-animate.md`](research/playone-exe/sod-animate.md) (`OP_ANIMATE`), [`terrain-shade.md`](research/playone-exe/terrain-shade.md) and [`world-scene.md`](research/playone-exe/world-scene.md) (ground shading and the world display list), [`lod.md`](research/playone-exe/lod.md) (level of detail, lens), [`palette-fade.md`](research/playone-exe/palette-fade.md), [`static-tooling.md`](research/playone-exe/static-tooling.md). |
| **Format Specs & Byte Layouts** | [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog; byte layouts are defined only by the `.ksy` schemas beside each spec. |
| **Research Routing** | [`research/README.md`](research/README.md) | Where each kind of finding goes, note shape, size guideline. |
| **Parity** | [`research/parity/`](research/parity/) | [`method.md`](research/parity/method.md) (loop, scoring), [`log.md`](research/parity/log.md) (dated results), [`attribution.md`](research/parity/attribution.md), [`framing-and-actors.md`](research/parity/framing-and-actors.md), [`film-segments.md`](research/parity/film-segments.md) (where the render differs), [`batch.md`](research/parity/batch.md) (all-films survey: `mise run batch-parity`). |
| **Agent Skills** | [`.agents/skills/`](.agents/skills/) | Shared task workflows, e.g. [`improving-render-parity`](.agents/skills/improving-render-parity/SKILL.md); `.claude/skills/` holds stubs that point here. |
| **Skill Configuration** | [`docs/agents/`](docs/agents/) | Per-repo settings the engineering skills read: [`issue-tracker.md`](docs/agents/issue-tracker.md) (GitHub Issues via `gh`), [`triage-labels.md`](docs/agents/triage-labels.md) (label vocabulary), [`domain.md`](docs/agents/domain.md) (where the glossary and ADRs live). |
| **Decisions (ADRs)** | [`docs/adr/`](docs/adr/) | One file per accepted design decision, e.g. [`0001-sod-tap-anchor-table.md`](docs/adr/0001-sod-tap-anchor-table.md). |
| **Coding & Format Rules** | [`Cargo.toml`](Cargo.toml), [`pyproject.toml`](pyproject.toml), [`.editorconfig`](.editorconfig) | Clippy workspace lints, Ruff & Mypy configurations, LF line endings, and 4-space indentation. |
| **Agents & Harnesses** | [`docs/harness.md`](docs/harness.md) | Policy every agent follows, then per-harness capability notes: sandbox modes, temp-directory and shell gotchas, what needs escalation, approvals, timeouts, subagent delegation, and where each harness keeps its settings. |
| **Harness Setup** | [`docs/harness-setup.md`](docs/harness-setup.md) | Machine-local setup a checkout cannot ship: tool installs, mise global config and trust, permission presets, data-root environment, worktree placement. |

Process documents, **not** sources of truth: [`docs/process/TEAM_SHEET.md`](docs/process/TEAM_SHEET.md) (roles, file blast radii, ticket status), under [`docs/process/`](docs/process/). Never cite them for a fact about the system.

---

## 3. Standard Operating Procedures (SOPs)

### SOP 1: Adding or Modifying File Parsers / Contracts
1. Implement or modify types in [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/) and re-export in [`contracts/mod.rs`](crates/stunt-core/src/contracts/mod.rs).
2. Synthesize synthetic test bytes in [`tests/fixtures/`](tests/fixtures/) and document in [`tests/fixtures/README.md`](tests/fixtures/README.md).
3. Add unit and roundtrip tests in `crates/stunt-core/tests/` (verifying with `--all-features`).
4. Run `mise run check` to verify formatting, linter, typechecker, and test pass.

### SOP 2: Documenting Binary Analysis
1. Put each finding in the note for its subject, by the routing rule in [`research/README.md`](research/README.md); follow the structure of [`research/playone-exe/startup.md`](research/playone-exe/startup.md).
2. Document segment:offset addresses, register states, Mermaid flowcharts, and DGROUP tables.
3. End the note with **Ruled out** and **Open questions**; keep evidentiary tiers out of headings.

### SOP 3: Verification & Handoff
1. Run `git status` before staging: stage the paths you changed by name, never `git add -A` or `git commit -a`, and never any file from `corpus/`. If the index holds another session's work, stop and ask.
2. Run `mise run check` to ensure all checks pass with zero warnings or errors.
3. Link modified code symbols and files using markdown links.
4. Commit with a Conventional Commit subject, e.g. `feat(core): add a parser`, and a body that answers why.
5. Write the handoff into the plan or `research/` note that owns the work item.

### Commit Messages
Write the body whenever a reviewer would have to ask "why this way?": what forced the change, the cause with the offset, measurement or log row that proves it, and what you rejected. One paragraph, then a bullet per file when several move together; never retell the diff. Renames, formatting and generated files need none. Longer reasoning belongs in the owning note or an ADR, cited from the body. Close with `mise run check passes.` when the whole gate ran, naming any part that did not.

### SOP 4: Living Specification Updates & Evidentiary Promotion
1. When analysis uncovers new runtime offsets, opcodes, or binary realities:
   - Update [`research/playone-exe/memory-map.md`](research/playone-exe/memory-map.md) (offsets) or the `research/` note that owns the finding immediately with verified discoveries; touch [`docs/SPEC.md`](docs/SPEC.md) only for goals, invariants or gates.
   - Promote evidentiary tiers (`[Unknown]` $\rightarrow$ `[Hypothesis]` $\rightarrow$ `[Bounded Observation]` $\rightarrow$ `[Supported Inference]` $\rightarrow$ `[Established]`; the enum is owned by `EVIDENTIARY_TIERS` in [`python/scripts/verify_formats_docs.py`](python/scripts/verify_formats_docs.py)) and cite the linear address or research note.
2. If extending Seam contracts in [`crates/stunt-core/src/contracts/`](crates/stunt-core/src/contracts/):
   - Add fields using backward-compatible defaults (`#[cfg_attr(feature = "serde", serde(default))]`).
   - Update synthetic test fixtures in [`tests/fixtures/`](tests/fixtures/) and contract unit tests.
   - Verify `mise run check` exits code `0` before marking any ticket complete.

### SOP 5: Working Economically
Each turn re-sends the whole conversation, so cost is roughly turns times context size.
1. **Fewer, fuller turns.** Batch independent reads and commands into one turn. Find the file through [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) before grepping, and read line ranges of files over about 20 KB rather than the whole file. Reach a file with `read` and a string with `grep`/`glob`; `Get-ChildItem` and `Get-Content` through a shell cost a turn and return a formatted table.
2. **Scoped checks while iterating.** Use `mise run check-rust` or `mise run check-py` (one line per step, failures only); run the full `mise run check` once, before a commit or hand-off (Directive 2).
3. **Scripts before subagents.** Mechanical checks (link, anchor, table or mapping audits) belong in a script. Delegate only real chunks of work: at most about 8 subagents per task, since each one starts cold. Write the brief as the whole instruction — goal, paths it may read, output shape, stopping condition — because `send_message` does not reach it ([`docs/harness.md`](docs/harness.md)).
4. **Parity work** follows the [`improving-render-parity`](.agents/skills/improving-render-parity/SKILL.md) skill, which holds its own cost rules (build once, batched sweeps, scratch paths, image budget).
5. **Drive everything through `mise run`.** Every agent-facing script has a task, so `mise run *` is the one command shape the harness pre-approves ([`docs/harness.md`](docs/harness.md)) and `mise tasks` is the one list of what exists. A task name you cannot find there does not exist — do not guess one. Where no task covers a one-off, `mise exec -- uv run …` runs the pinned uv but is not pre-approved — expect an approval prompt, and a command needed twice earns a task. A bare `uv` can be a different version than [`mise.toml`](mise.toml) pins; `required-version` in [`pyproject.toml`](pyproject.toml) refuses one older than the pin but lets a newer one run, so only `mise exec` gives the pinned version.

### SOP 6: Working in a Worktree

1. One **writer** per checkout path at any moment, one branch per worktree. A *writer* is a session that mutates the checkout during a turn; a read-only scout is not a writer. The Lead is the default writer in a shared checkout; teammates are read-only unless the Lead assigns each a worktree from its current `HEAD`, in which case each writer commits only on its own branch and the Lead integrates ([harness policy](docs/harness.md#teammates)). Where it lives is the tool's choice (`<repo>.wt/<slug>`, `.claude/worktrees/`, `.agents/worktrees/`), but one inside the checkout must sit under a directory that `.gitignore` and ruff's `exclude` both cover ([`tests/test_worktree_layout.py`](tests/test_worktree_layout.py) fails the gate otherwise). A read-only scout may share the path; two writers must not. Never work on a branch another worktree holds.
2. `mise run init` once per worktree links the shared data root and the shared tool cache, parks the worktree's virtualenv inside that cache ([ADR 0019](docs/adr/0019-a-worktrees-virtualenv-lives-in-the-shared-cache.md)), and then runs `uv sync`. `capture-ref`, `parity` and `sweep` repair a missing link when they start, so a checkout made by another tool still reads the corpus; `mise run check` stays corpus-free. In a sandboxed session (`workspace-write`) that one run needs wider file access, because the junction targets are outside the workspace; see [`docs/harness-setup.md`](docs/harness-setup.md).
3. The shared data root (`<parent-of-primary>/<repo-name>.data`, or `STUNT_DATA_ROOT`) holds the game files and the captures. Nothing writes `corpus/`; a capture adds a new directory under `captures/` and never changes one, and a generated `.ALL` is stored the same way, as `captures/<film>/frames/<run>` and `captures/<film>/archives/<run>` ([ADR 0022](docs/adr/0022-captures-are-add-only-beside-a-read-only-corpus.md), [ADR 0023](docs/adr/0023-make-all-generates-archives-with-makeone.md), [ADR 0024](docs/adr/0024-captures-are-filed-by-film-then-kind.md)), and which capture parity scores against is named in [`research/parity/references.toml`](research/parity/references.toml), changed only by a reviewed commit. Captures do not serialise: each session binds its own control port ([ADR 0021](docs/adr/0021-capture-chooses-its-control-port.md)).
4. Plans and handoffs go in the repo note, plan or ADR that owns them, never only in agent memory: memory is keyed by checkout path, so a session in another worktree never sees it. Shared append-only files such as [`research/parity/log.md`](research/parity/log.md) take rows at the end only; `.gitattributes` union-merges them.
5. Reap with `mise run reap -- --yes` from the primary checkout: it unlinks the data-root links, proves none remain, and only then runs `git worktree remove` and deletes the branch. Add `--cherry` for branches whose patches `main` already holds, `--prune` for pool leftovers and branches without a worktree, and `--stash-dirty`/`--discard-untracked` to allow work at risk. Never call `git worktree remove` yourself on a worktree `mise run init` has linked: git's worktree removal has deleted through Windows junctions on one build and left their skeletons on another ([ADR 0018](docs/adr/0018-reaping-unlinks-the-data-root-links-first.md)). `mise run clean -- --yes` only clears a checkout you are keeping. See [ADR 0008](docs/adr/0008-worktrees-share-one-read-only-data-root.md).

---

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `neilsh/stunt-reel`, via the `gh` CLI. See [`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md).

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See [`docs/agents/triage-labels.md`](docs/agents/triage-labels.md).

### Domain docs

Single-context; the glossary is [`GLOSSARY.md`](GLOSSARY.md), ADRs are in [`docs/adr/`](docs/adr/). See [`docs/agents/domain.md`](docs/agents/domain.md).
