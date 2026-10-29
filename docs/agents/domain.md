# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase. This is a single-context repo.

_Source: adapted from the `setup-matt-pocock-skills` template in [mattpocock/skills](https://github.com/mattpocock/skills), trimmed to this repo (real ADR example, no multi-context layout). Re-running the setup skill overwrites it._

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root: the canonical project vocabulary (film, slice, tick, trajectory record, epilogue, shape, slot, partial SOD).
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If either doesn't exist, **proceed silently**. Don't flag its absence; don't suggest creating it upfront. The `/domain-modeling` skill creates and edits them lazily when terms or decisions actually get resolved.

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms listed under _Avoid_.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR 0001 (SOD TAP anchor table), but worth reopening because…_
