---
name: recording-findings
description: "Use when disassembly, a debugger session, a capture or a parity experiment turns up a fact worth keeping in `research/`: an offset, opcode, DGROUP field or format behaviour of PLAYONE.EXE, MAKEONE.EXE, STUNT.EXE or a game file, how the original draws or behaves, why our render differs from it, or a ruled-out hypothesis; or when promoting a finding's evidentiary tier."
---

# Recording findings

A *finding* is a fact about how the original stores data (format), how it draws or behaves (rendering and runtime), or why our render differs from it (residual). Each lives in exactly one research note, its offsets in one table and its anchors in one registry, where the next session and the checks find it.

## Steps

1. **Owning note and journal entry.** Route the finding, and each ruled-out hypothesis, by the [routing rule](../../../research/README.md#routing-rule); a format fact goes under [`research/formats/`](../../../research/formats/INDEX.md), its byte layout in the `.ksy` where that schema covers it, else in the spec, and its meaning in the spec. The experiment is a [journal entry](../../../work/README.md#journal-entries) in its work folder. End the finding with an inline provenance line to the entry's heading (the check rejects a reference-style one):

   ```markdown
   _Source: [<entry title>](<path>/journal.md#<heading>)._
   ```

   Done when the finding sits in its note and links its entry.
2. **Offsets and anchors.** Add every new `PLAYONE.EXE` offset to [`research/playone-exe/memory-map.md`](../../../research/playone-exe/memory-map.md), and register every new `# [MEM-*]` or `# [FMT-*]` anchor in [`doc_anchors.py`](../../../python/stunt_reel/doc_anchors.py). Done when every offset has a row and every new anchor a registry entry.
3. **Tier.** Tag the finding with its evidentiary tier; the ladder is `EVIDENTIARY_TIERS` in [`verify_formats_docs.py`](../../../python/scripts/verify_formats_docs.py). Each step up cites the linear address or the note that proves it. Keep tiers out of headings. Done when the tier tag names its evidence.
4. **Spec.** Change [`docs/SPEC.md`](../../../docs/SPEC.md) only if the finding changes a goal, invariant or gate.
5. **Close the note.** Add or update its `summary:`, then end it with a `## Ruled out` heading (each rejected hypothesis in one line with its journal link) and a `## Open questions` heading (open work in priority order). Done when the summary is current and both headings exist, even if one says "none yet".
6. **Commit with the code.** Commit the note with the code that relies on the finding, or by the session's end if no code does yet. The commit body and the code link the note or its anchor rather than restating it.

Done when the note has a current `summary:` and ends with `## Ruled out` and `## Open questions`, every offset and anchor it introduces is registered, and it is committed with its code.

## Quick reference

- **Which note:** `research/MAP.md`, then `research/README.md` § Routing rule.
- **Work folder:** `mise run work -- new <slug> (--issue N | --problem TEXT)`.
- **Check it all:** `mise run verify-docs`, then `mise run check`.

## Common mistakes

- **No Ruled out section.** Baseline plans put leftovers under "Open questions" and never recorded what was rejected, so the next session re-tests it.
