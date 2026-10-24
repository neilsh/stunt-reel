# Research Notes: Where Each Finding Goes

`research/` records what the original game does. What we build from it (goals, invariants, architecture, decisions) lives in [`docs/`](../docs/). Each finding has exactly one home, chosen by its **subject**, not by the activity that produced it.

## Layout

| Folder | Subject | Examples |
|---|---|---|
| [`playone-exe/`](playone-exe/) | Behaviour of `PLAYONE.EXE`: code, memory, runtime state, and the tools used to study it | [`terrain-shade.md`](playone-exe/terrain-shade.md), [`lod.md`](playone-exe/lod.md), [`memory-map.md`](playone-exe/memory-map.md) (offset tables), [`static-tooling.md`](playone-exe/static-tooling.md) |
| [`formats/`](formats/) | File formats and engine concepts shared across files; byte layouts only in the `.ksy` schemas | [`INDEX.md`](formats/INDEX.md), [`flm.md`](formats/flm.md), [`sod-opcodes.md`](formats/sod-opcodes.md), [`concepts/`](formats/concepts/) |
| [`parity/`](parity/) | How our render differs from the original's, and how we measure it | [`method.md`](parity/method.md), [`log.md`](parity/log.md) |

## Routing rule

1. **A fact about the original goes to the note for its subject.** "The player Gouraud-shades the ground index" belongs in `playone-exe/terrain-shade.md`; "the ground scene is stored in `CTRY.ALL`" belongs in `formats/all.md`. It does not stay in the log of the experiment that found it.
2. **A fact about our render's residual goes to `parity/`,** in the note for that residual (where the loss sits, framing and actors, mismatched film segments).
3. **Every experiment leaves one row in [`parity/log.md`](parity/log.md):** date, commit, score, adopted or not, and a link to where its finding now lives. The finding carries a provenance line pointing back at the row.
4. **Tooling lives with what it studies.** A tool or tool evaluation for `PLAYONE.EXE` goes in `playone-exe/static-tooling.md`.
5. **A handoff is not a file.** Open questions and next steps go under "Open questions" in the note that owns the work.
6. **Superseded content is replaced, not kept beside the new result.** Its history is the log row and git.

New offsets also update the tables in [`memory-map.md`](playone-exe/memory-map.md) (`# [MEM-*]` anchors); new format facts follow [`formats/INDEX.md`](formats/INDEX.md). Evidentiary tiers are defined in [`docs/SPEC.md` § 2.4](../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).

## Note shape

Follow [`playone-exe/startup.md`](playone-exe/startup.md) for structure (addresses, register states, flowcharts, tables), and end each subject note with:

- **Ruled out:** hypotheses tested and rejected, one or two lines each: what was tried, the score or observation, the verdict.
- **Open questions:** open work in priority order.

Headings carry no evidentiary tier tag, so links survive a tier promotion; state the tier in the section's first line. Anchor tokens (`# [FMT-*]`, `# [MEM-*]`) stay in headings.

## Size

Keep each note under about 20 KB so one read covers it. When a note grows past that, split it by subject (for example `sod.md` / `sod-opcodes.md`), not by date. Generated tables (`formats/sod-opcode-coverage.md`) and the append-only [`parity/log.md`](parity/log.md) are exempt.
