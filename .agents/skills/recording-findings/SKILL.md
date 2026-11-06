---
name: recording-findings
description: "Use when disassembly, a debugger session, a capture or a parity experiment turns up a fact worth keeping in `research/`: an offset, opcode, DGROUP field or format behaviour of PLAYONE.EXE, MAKEONE.EXE, STUNT.EXE or a game file, how the original draws or behaves, why our render differs from it, or a ruled-out hypothesis; or when promoting a finding's evidentiary tier."
---

# Recording findings

A *finding* is a fact about how the original stores data (format), how it draws or behaves (rendering and runtime), or why our render differs from it (residual). Each lives in exactly one research note, its offsets in one table and its anchors in one registry, so the next session can find it and the checks can verify it.

## Steps

1. **Owning note.** Route the finding, and each ruled-out hypothesis, by the [routing rule](../../../research/README.md#routing-rule): a fact about the original goes to the note for its subject, a residual to its `parity/` note, and a parity experiment also leaves one row at the end of `parity/log.md`. A new format fact goes under [`research/formats/`](../../../research/formats/INDEX.md): a byte layout in the format's `.ksy` where that schema covers it, else in the spec as `INDEX.md` lists, and its meaning in the spec. Done when the finding sits in the note for its subject.
2. **Offsets and anchors.** Add every new `PLAYONE.EXE` offset to [`research/playone-exe/memory-map.md`](../../../research/playone-exe/memory-map.md), and register every new `# [MEM-*]` or `# [FMT-*]` anchor in [`doc_anchors.py`](../../../python/stunt_reel/doc_anchors.py). Done when every offset has a row and every new anchor a registry entry.
3. **Tier.** Tag the finding with its evidentiary tier; the ladder is `EVIDENTIARY_TIERS` in [`verify_formats_docs.py`](../../../python/scripts/verify_formats_docs.py). Each step up cites the linear address or the note that proves it. Keep tiers out of headings. Done when the tier tag names its evidence.
4. **Spec.** Change [`docs/SPEC.md`](../../../docs/SPEC.md) only if the finding changes a goal, invariant or gate.
5. **Close the note.** End it with **Ruled out** (hypotheses tested and rejected, one or two lines each) and **Open questions** (open work in priority order). Done when both sections exist, even if one says "none yet".
6. **Commit with the code.** Commit the note with the code that relies on the finding; a finding no code uses yet lands before the session ends. The commit body and the code link the note or its anchor rather than restating it.

Done when the note ends with **Ruled out** and **Open questions**, every offset and anchor it introduces is registered, and it is committed with the code that uses it.

## Quick reference

| Need | Where |
|---|---|
| Which note | `research/README.md` § Routing rule |
| Offset tables | `research/playone-exe/memory-map.md` |
| Anchor registry | `python/stunt_reel/doc_anchors.py` |
| Tier ladder | `EVIDENTIARY_TIERS`, `python/scripts/verify_formats_docs.py` |
| Check it all | `mise run verify-docs`, then `mise run check` |

## Common mistakes

- **No Ruled out section.** Every baseline plan put leftovers under "Open questions" but never recorded what was tested and rejected; the next session re-tests it.
