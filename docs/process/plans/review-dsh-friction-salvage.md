# Salvage of `review-dsh-friction`

Status: in progress, 2026-10-25. Branch `wt-202610251243-salvage-review-dsh-friction`, rebased
onto `main` at `60922b7`.

The repository's history was rewritten on 2026-10-25 to put every commit on the GitHub noreply
identity, so the branch was cut from the pre-rewrite `main` (`6b0777f`, identical tree) and then
replayed onto the rewritten one. Hashes below are the current ones for `main`-line commits; the
two salvaged commits and the branch's fork point (`9e5591e`, `0892193`, `a2a12c0`) live on the
pre-rewrite lineage and are still reachable through `review-dsh-friction`. Two commit bodies still
cite the pre-rewrite `70e470d` and `96f0384` — rewording them needs a shell editor the sandbox
refuses — and they are `a0389df` and `e0a59f5` here.

The branch `review-dsh-friction` carried two commits (`0892193`, `9e5591e`) that were never
merged. It was cut from merge-base `a2a12c0`, and `main` gained 30 commits in the meantime, so
this is a salvage and not a merge: each piece was re-checked against `main` and only the parts
that are still true, still absent, and still the right shape are re-derived here.

## Inventory

Verdicts come from reading both sides at `60922b7`, not from the branch's own summary.

| Piece | Verdict | Why |
|---|---|---|
| `gate.py` one-line-per-step gate with a verdict and `target/check.log` | re-derived | `[tasks.check]` still runs a `depends` chain, and `quiet_check.py` still omits `doc` and `check-rust-matrix`, so the quiet halves are a shorter gate than `check` |
| `mise` tasks for scripts called by path | re-derived | six runnable scripts still had no task: `parity_probe.py`, `verify_formats_docs.py`, `unlzexe.py`, `flm_events.py`, `probe_playone_light.py`, `adversarial_formats_challenge.py`. `cli.py` is the shared options module those two parity scripts import, not a script, so it correctly gets none |
| whole-catalog schema contract test | re-derived | only `set.ksy` and `memory/actor_record.ksy` are compiled by any test, both skipping when `ksc` is absent; nothing compiles all eleven schemas |
| `docs/harness.md`, now multi-harness | re-derived, restructured | nothing on `main` documents the harness; the branch version was DSH-only and claimed the settings cannot ship, which is false for the committed `.claude/settings.json` |
| `parity_run.py` previous-render snapshot | landed as written | `main` still `rmtree`s `_current` in place, keeps no prior tree, and still exposes `--reuse`; the hunk context is byte-identical |
| `research/parity/method.md` steps 2 and 7 | landed as written | the file is untouched on `main` since the merge-base and still tells the reader to snapshot by hand |
| `parity_probe.py summary` | re-derived | `main` reads reports through the artifact port and dropped `import json`; the branch's hand-rolled reader would duplicate the schema ADR 0011 forbids, and its default path (`ctry_current`) is not main's (`ctry`) |
| `prune_renders.py` + `mise run prune` | re-derived as a `clean` mode | `mise run clean` already removes all of `build/`, so a second top-level remover would compete with it; pruning becomes `mise run clean -- --parity --keep N --yes` |
| `.pre-commit-config.yaml` deletion | re-derived | `main` never installs or runs it, `README` still advertises it as hooks that "mirror the gate", and it pins ruff `0.9.1` while the gate runs `0.17.1` |
| `brief.py` | dropped | a generated orientation page is one more artefact to keep honest; `mise tasks` plus `AGENTS.md` SOP 5 already carry what it would print, and the session measurement that motivated it cannot be re-taken |
| `AGENTS.md` turn-cost prose | dropped | `AGENTS.md` SOP 5.2 already states the fewer/fuller-turns and read-a-range rule |
| `verify_schemas_corpus.py` skip-memory/root-argument change | dropped | `a0389df` fixed the abort with the better shape (guard the missing extension, keep scanning); the branch's fix is a different shape for a problem that no longer exists |
| `docs/adr/0009-harness-…` | dropped | the harness posture is host-local and unenforceable by the repo, so it is a doc not an ADR; `main`'s `0009` is already taken. The one decision that *is* repo-enforced — the gate's shape — becomes ADR 0014 |
| the branch's AGENTS.md rewrite | partly refused | it deletes the SOP 3.5 handoff and re-adds "one work item per session", which `e0a59f5` deliberately dropped as a scheduling convention rather than a gate |

## Measurements the branch quoted

Observed in agent sessions on 2026-10-24 and not reproducible from the repository, so they are
recorded here rather than in the ADR or the harness page: 3.56 M output tokens and 2.4 k tool
calls across 43 sessions; 122 k characters read before a first edit; 58,087 bytes of gate
transcript per run, filtered by hand in 58 of 151 invocations; 143 calls to scripts by path;
409 shell listing calls; 12 calls to task names that never existed; a parity output tree of
19.7 GB in 332,723 files; 33 approval requests costing 40.5 minutes of blocked work, 17 of them
cancelled and the worst returning after 397 s as `deadline reached`.

## Commits

Oldest first, on top of `main` (`60922b7`):

1. `feat(cli)` — the gate and its task surface, with ADR 0014 in the same commit (the README
   points at the ADR, so splitting them dangles a link), plus `quiet_check.py` and
   `.pre-commit-config.yaml`: all three are one enforcement surface, and the hook is deleted for
   the same reason the duplicate gate is — it mirrored a gate it had drifted from.
2. `test(verify)` — the whole-catalog schema contract test.
3. `docs(agents)` — `docs/harness.md` as a multi-harness page, the `AGENTS.md` rows and SOP
   changes that point at it, and a `CLAUDE.md` stub so the other configured harness reads the
   same rules.
4. `feat(parity)` — previous-render snapshot, the vocabulary fix in `method.md`, the probe
   `summary` through the report port, and pruning as a `clean` mode.
5. `chore(agents)` — drop the unfollowable "Haiku first, Sonnet as fallback" line.
6. `docs(process)` — this note.
7. `fix(parity)` — protect named `_base` baselines from the rotation: reviewing the note found
   that the method tells a reader to keep a `_base` copy, and the rotation would have deleted it.
8. `docs(process)` — corrections to this note made while reviewing it: the six-not-seven task
   count (`cli.py` is a module), a broken emphasis, the missing `--yes`, the rewritten `main`
   hashes, and the two pre-rewrite hashes the commit bodies still cite.

## Environment notes

- `mise run ...` repairs its Rust toolchain under `%LOCALAPPDATA%\mise` on every invocation.
  Under `workspace-write` that write is denied and every task stops before its first step;
  `MISE_DISABLE_TOOLS=rust` with the installed toolchain's `bin` on `PATH` lets the gate run
  without escalation ([`docs/harness.md`](../../harness.md) records both routes).
- A freshly created worktree fails its first `pytest` run: `tests/conftest.py` points
  `--basetemp` at `<root>/.pytest_cache/basetemp`, and pytest creates it with
  `mkdir(parents=False)`, so it needs `.pytest_cache` to exist first. `mkdir .pytest_cache`
  once per worktree fixes it; making the fallback create the parent would fix it for good.

## Open questions

- Whether the parity `summary` should also print the `method.md` row for INTRO, or only the
  film it scored.
- Whether the harness page grows a third section before a second harness outgrows a screen.
