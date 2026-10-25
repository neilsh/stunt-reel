# Architecture Deepening Programme (Milestone 4)

Status: implementation in progress. The programme turns six deepening candidates from the architecture review into four design units, worked in order. Every brief is agreed; unit A landing 1 is merged and the handoff below governs the remaining landings.

## 1. Settled programme decisions

1. **Design first, implement later.** All units are designed to shared understanding - interface, what sits behind the seam, migration, surviving tests, kill criteria - before any unit is implemented.
2. **Scope.** The six review candidates plus two riders: the report-aggregation rider with unit A, the transport-at-operation-altitude rider with unit D. The four stand-alone parked items stay out of the programme.
3. **Units and order.** A render artifact, B decoded shape seam (cards 2, 3 and 4 as one interface), C renderer entry point, D capture session.
4. **Design-it-twice.** Every unit gets two blind interface variants in parallel, each under a different design constraint, compared in one round on depth, locality, seam placement, migration cost and the deletion test.
5. **Regression bar.** `mise run check` stays green, and no unit changes the local parity baseline: report fields identical and sampled `.idx`/`.layer` planes identical. New interfaces are pinned by offline fixtures.
6. **Records.** One brief per unit lives in this directory; `TEAM_SHEET.md` carries one milestone-4 row per unit linking its brief. ADRs are written only for hard-to-reverse decisions.
7. **Kill rule.** A unit is abandoned, not watered down, when its design fails the kill criteria recorded in its brief.

## 2. Units

| Unit | Scope | Design state | Brief |
|---|---|---|---|
| A | Render artifact seam plus the report-aggregation rider | Landings 1-3 merged; landing 4 pending | [A-render-artifact.md](A-render-artifact.md) |
| B | Decoded shape seam: one stop decision, a shape IR that owns its invariants, partial SOD as a value | Done (merged 58745f8) | [B-decoded-shape.md](B-decoded-shape.md) |
| C | Renderer entry point for headless and window | Stages 1-2 merged; deletion stage pending | [C-renderer-entry.md](C-renderer-entry.md) |
| D | Capture session with an injectable transport; transport at operation altitude | Merged (e17c9bc); live capture unverified | [D-capture-session.md](D-capture-session.md) |

## 3. Why this order

- **A first** because it is independent of core decoding, sets the artifact vocabulary and plane records that C consumes, and gives later units a baseline comparison to lean on.
- **B next** because it is the largest unit and unblocks the open fidelity ticket for the next blocking opcode.
- **C after A** because its renderer interface consumes A's plane records rather than inventing a second plane form.
- **D last** because it is Python-only and independent of the Rust units; it can be reordered without touching the others.

## 4. Design brief checklist

Each brief settles, and is only accepted when it settles:

1. the interface - types and methods, invariants, ordering, error modes, anything a caller must know;
2. the seam placement, and what sits behind it;
3. compatibility and migration - old artifacts, serde defaults, phased landings;
4. test survival - which tests stand unchanged, which move, what dies, what new tests cross the interface;
5. deletions under the deletion test, and what shrinks instead;
6. kill criteria - what evidence would abandon the design.

## 5. Regression bar

- Offline gate: `mise run check` (format, lint, typecheck, Rust and Python tests, rustdoc, no-default-features matrix).
- Local baseline: `build/parity/reference` and `build/parity/report` for CTRY and INTRO. Before a unit, keep the current render directories and `report.json`; after it, every report field must match and sampled `.idx`/`.layer` planes must be byte-identical.
- The local baseline lives under `build/` and is gitignored, so it is a working-session bar, not a CI guarantee. Committed tests stay offline and use synthetic fixtures only.
- New interfaces are pinned by committed fixtures under `tests/fixtures/`.

## 6. References

- [AGENTS.md](../../../../AGENTS.md): standards, SOPs and the quality gate.
- [docs/SPEC.md](../../../SPEC.md): invariants and the master verification matrix.
- [docs/ARCHITECTURE.md](../../../ARCHITECTURE.md): code path to governing documents.
- [GLOSSARY.md](../../../../GLOSSARY.md): canonical domain vocabulary.
- [ADR 0004](../../../adr/0004-i6-gate-is-reported-not-enforced.md), [ADR 0005](../../../adr/0005-parity-requires-the-render-sidecar.md), [ADR 0007](../../../adr/0007-evidence-backed-parity-changes-adopt-on-correctness.md), [ADR 0010](../../../adr/0010-python-scripts-may-take-well-established-dependencies.md).
- [TEAM_SHEET.md](../../TEAM_SHEET.md): ticket status.

## 7. Implementation handoff

All four briefs are agreed; implementation has not started. Land one PR per checklist item in order A, B, C, D. Every landing is independently green.

- **Entry bar for any landing:** %BT%mise run check%BT% green, and the local parity baseline unchanged wherever the landing can affect rendering or scoring (report fields identical, sampled %BT%.idx%BT%/%BT%.layer%BT% byte-identical).
- **Pre-flight once, before unit A:** snapshot %BT%build/parity/ours%BT% and %BT%build/parity/report%BT% for CTRY and INTRO; they are the reference for every later comparison. They live under the gitignored %BT%build/%BT% directory, so this is a local bar, not a CI guarantee.
- **PR policy:** one PR per landing in the brief's migration section; no umbrella branch; stage changed paths by name; Conventional Commit with a body that answers why; update the TEAM_SHEET row when a unit's first landing merges.
- **Deviations:** record them in the owning brief, not only in the PR description.
- **ADRs to write while landing:** the artifact port's source-of-truth and versioning rule, with an implementation note on ADR 0005, in unit A PR1; partial SOD as a value owned by the decode record, in unit B PR2.
- **Completion:** each unit is complete when its brief's tests survive at the interface, its deletions are done, and the baseline check passes. The programme closes when A-D are complete and the six review candidates no longer reproduce their friction.

