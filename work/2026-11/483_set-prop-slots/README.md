---
title: "Close .SET prop record field map on remaining 427/2,032 corpus records ([BK-SET-04])"
started: 2026-11-17
issue: 483
outcome: ""
---

# Close .SET prop record field map on remaining 427/2,032 corpus records ([BK-SET-04])

## Question

Why does the `.SET` prop field map in [`set.md` § 3.1](../../../research/formats/auxiliary/set.md) not close on 427 of 2032 corpus records, and which of the 64 bytes are explained?

## Handoff

- **Done (cloud, 36 retail sets, 715 records):** the leading word is the 0-based prop slot, stored only for occupied slots; the trailing word copies the next slot's flags; `+0x1A` and `+0x1C` are slot references; § 3.1 now names or marks unknown every byte with a coverage count. [`journal.md`](journal.md) holds the run. `verify_schemas_corpus.py` gained a `set` probe for the slot rules, tested offline in `tests/test_set_schema.py`.
- **Left, filed as #683 (needs the full `corpus/siarchive`, so local-windows):** run `mise run verify-corpus -- --schema set --strict` over the 93 community sets, which hold 290 of the 427 mismatches, and list any set that breaks a rule; read the 22 printed dumps in `corpus/siarchive/Misc/Sets/` against the `unknown_*` bytes.
