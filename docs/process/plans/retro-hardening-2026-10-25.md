# Retro hardening plan (2026-10-25)

Status: implementation complete on branch `wt-202610252029-retro-hardening` (based on `c6fabf5`; not merged at the time of writing). Source: the retrospective of the architecture-deepening session, grilled and agreed on 2026-10-25. Work items are `T16`-`T20` in [TEAM_SHEET.md](../TEAM_SHEET.md); this note is the decision record and landing log.

## 1. Decisions

- **Writer policy.** A *writer* is a session that mutates the checkout during a turn; a read-only scout is not a writer. **One writer per checkout path at any moment.** The Lead is the default writer; teammates are read-only scouts, designers or reviewers, and never write in the shared checkout. A worktree-per-writer mode is opt-in for **at least two genuinely independent tickets** — disjoint files, separately verifiable, no shared file. The mode's gates: writers branch from the Lead's current `HEAD`, at most two writers plus the Lead, integration in the same session in dependency order, and scoped checks per merge with the full gate at the tip. A writer commits **only on its own worktree branch**; the Lead reviews and integrates it, preserving the writer's authorship and rationale. Teammates never push and never commit in the shared checkout.
- **build-at.** `mise run build-at -- <rev> <out>` builds a detached worktree for one revision with an isolated `target/build-at` directory, copies the `stuntreel` binary to `<out>`, and removes the worktree on both success and failure. Revision only: no dirty-tree snapshot, because that was the stash/`Cargo.lock` conflict the task removes. Release profile; `<out>` is a binary path.
- **Commit references.** Durable documents cite commit **subjects and dates**, not hashes; exact hashes remain in commit messages and in the salvage note's historical mapping. The history was rewritten to the noreply identity on 2026-10-25, so pre-rewrite hashes no longer resolve on `main`.
- **Roles.** Add a `tooling-worker` persona for repository tooling and harness policy; `sentinel` keeps the process and routing-doc edits.
- **Record place.** This plan note owns the decisions; no ADR (the writer policy is environment policy, cheap to revise, and [harness.md](../../harness.md) is its natural owner) and no GLOSSARY change (agent-process terms are not Stunt Island domain language).

## 2. Tickets

| Ticket | Title | Owner | Status | Evidence |
|---|---|---|---|---|
| `T16` | Verify the fresh-worktree `pytest` cache assumption | `tooling-worker` | **Done (no change needed)** | reproduction on 2026-10-25 passed in a fresh worktree; [salvage note](review-dsh-friction-salvage.md) corrected |
| `T17` | Tier checker ignores nested bracket expressions | `tooling-worker` | **Done** | [`verify_formats_docs.py`](../../../python/scripts/verify_formats_docs.py), [`test_formats_catalog.py`](../../../tests/test_formats_catalog.py) |
| `T18` | Writer policy for Agent Teams | `tooling-worker` | **Done** | [harness.md](../../harness.md), [AGENTS.md](../../../AGENTS.md#sop-6-working-in-a-worktree) |
| `T19` | `mise run build-at` for a previous revision | `tooling-worker` | **Done** | [build_at.py](../../../python/scripts/build_at.py), [mise.toml](../../../mise.toml) |
| `T20` | Commit-reference convention and programme pointer | `sentinel` | **Done** | [architecture-deepening README](architecture-deepening/README.md), [ARCHITECTURE.md](../../ARCHITECTURE.md) |

`T16` closed without code: a fresh worktree's first `pytest` run passed, and `pytest` created `.pytest_cache` itself before using the configured basetemp. The salvage note's environment bullet is corrected rather than adding an unnecessary `mkdir`.

## 3. Verification

One branch and one PR; one commit per ticket; scoped checks while iterating; the full `mise run check` once at the tip. No parity, capture or render run: the batch touches tests, tooling and docs only.

The full gate passes 9/9. On this host the link step returns `LNK1104` when `TMP`/`TEMP` point at the user temp directory inside a worktree, so the gate was run with both redirected to `build/tmp`; `build-at` isolates them for the same reason.

## 4. Deferred and rejected

- **Deferred:** a scoped `check-docs` task (the format-catalog verification already runs inside `test-py`) and the shell/commit-message notes for [harness.md](../../harness.md) (documentation-only convenience).
- **Rejected:** a CI author-identity check. The repository config and the user's noreply rule already cover the maintainer path; a PR check would reject legitimate forked commits from other addresses.

## 5. Landing log

1. **Plan and tickets.** This note, the `tooling-worker` row and the Milestone 5 rows; `T16` verified and closed.
2. **T17, tier checker.** The tier pattern ignores a bracket preceded by another bracket, and a regression test pins both the ignored `Callable[[Session], T]` form and the tags that must still be found. The scanner no longer rewrites legitimate signatures.
3. **T18, writer policy.** `docs/harness.md` defines a writer, keeps the Lead as the default single writer, and admits the worktree-per-writer mode for two or more independent tickets under a commit-on-own-branch / Lead-integrates contract; SOP 6 points at it.
4. **T19, build-at.** `mise run build-at -- <rev> <out>` builds a revision in a detached worktree with isolated target and temp directories, copies the binary and removes the worktree; the parity method points at it. Verification built a 7,836,160-byte `stuntreel.exe` from `HEAD`. (The first run exposed a linker `LNK1104` in the user temp directory; the isolated `TMP`/`TEMP` is part of the fix.)
5. **T20, references.** Durable records cite commit subjects and dates; the closure note points at the salvage hash mapping and `ARCHITECTURE.md` gains a history pointer to the closed programme.
