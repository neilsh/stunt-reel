# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

This is a single-context repo. The domain glossary is [`GLOSSARY.md`](../../GLOSSARY.md) at the repo root; it plays the role other repos give a `CONTEXT.md`. Wherever a skill says `CONTEXT.md`, read and edit `GLOSSARY.md` instead, and do not create a `CONTEXT.md`.

## Before exploring, read these

- **`GLOSSARY.md`** at the repo root: the canonical project vocabulary (film, slice, tick, trajectory record, epilogue, shape, slot, partial SOD).
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill creates and edits them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── GLOSSARY.md
├── docs/adr/
│   ├── 0001-sod-tap-anchor-table.md
│   └── 0002-stunt-core-may-take-small-dependencies.md
└── crates/ python/ research/ ...
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `GLOSSARY.md`. Don't drift to synonyms the glossary lists under _Avoid_.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (SOD TAP anchor table), but worth reopening because…_
