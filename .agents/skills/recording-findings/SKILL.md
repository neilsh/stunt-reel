---
name: recording-binary-findings
description: "Use when disassembly, a debugger session or a capture turns up an offset, opcode, DGROUP field or behaviour of PLAYONE.EXE, MAKEONE.EXE, STUNT.EXE or a game file format worth keeping in `research/`, or when promoting a finding's evidentiary tier."
---

# Recording binary findings

A finding lives in exactly one research note, its offsets in one table and its anchors in one registry, so the next session can find it and the checks can verify it.

## Steps

1. **Owning note.** Pick it by the [routing rule](../../../research/README.md#routing-rule); follow the shape of [`research/playone-exe/startup.md`](../../../research/playone-exe/startup.md): segment:offset addresses, register states, Mermaid flowcharts, DGROUP tables. Done when the finding sits in the note for its subject.
2. **Offsets and anchors.** Add every new `PLAYONE.EXE` offset to [`research/playone-exe/memory-map.md`](../../../research/playone-exe/memory-map.md), and register every new `# [MEM-*]` or `# [FMT-*]` anchor in [`doc_anchors.py`](../../../python/stunt_reel/doc_anchors.py). Done when every offset has a row and every new anchor a registry entry.
3. **Tier.** Tag the finding with its evidentiary tier; the ladder is `EVIDENTIARY_TIERS` in [`verify_formats_docs.py`](../../../python/scripts/verify_formats_docs.py). Each step up cites the linear address or the note that proves it. Keep tiers out of headings. Done when the tier tag names its evidence.
4. **Spec.** Change [`docs/SPEC.md`](../../../docs/SPEC.md) only if the finding changes a goal, invariant or gate.
5. **Close the note.** End it with **Ruled out** (hypotheses tested and rejected, one or two lines each) and **Open questions** (open work in priority order). Done when both sections exist, even if one says "none yet".

Done when the note ends with **Ruled out** and **Open questions**, and every offset and anchor it introduces is registered.

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
