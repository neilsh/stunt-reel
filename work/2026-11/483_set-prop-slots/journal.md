# Journal

## 2026-11-17: prop slot words and per-offset columns on the retail sets

**Question.** Why do 427 of 2032 prop records carry a `prop_slot_id` at or above their set's record count, and which bytes of the 64-byte record vary at all?

**Method.** A cloud session, on `ce9fe79`, holding only the 36 retail sets under `corpus/stuntisl/SETS/` (715 records); the other 93 sets of the 2032-record sweep are not in the cloud archives. Each set was cut at `0x54 + 67 × num_events` into 64-byte records, and each record's leading word listed in file order. Per-offset value counts were taken over all 715 records, split by slot word 0–7 (214 records) against 8–39 (501). Then three targeted tests: whether bytes `+0x3E`–`+0x3F` equal some other record's bytes; whether the positive values of the `i16` at `+0x1A` and `+0x1C` name a slot present in the same set; and the range of the three `i32` positions read as 16.16.

**Result.**

- The leading word is a sparse slot number, not a record index. In 36 of 36 sets it strictly increases, never exceeds 39, and starts at 0; every set skips at least one slot, and 26 skip one of slots 0–7. A record is stored only for an occupied slot. Under that reading the retail sets' 137 words at or above the record count, and their 503 words that differ from the index, are expected rather than misread.
- `+0x3E`–`+0x3F` equal `+0x02`–`+0x03` of the record for the next slot number in 626 of 626 records whose next slot is present. In the 89 records whose next slot is absent (36 of them last in their set), the high byte is `0x00` in 82.
- The positive `+0x1A` values name a slot present in the same set in 37 of 38 records, the positive `+0x1C` values in 129 of 129, and neither ever names its own slot. The non-positive values are 0 and −1 only.
- Constant columns: `+0x01`, `+0x18`, `+0x19` and `+0x31` are zero in 715 of 715 records. In the 501 records of slots 8–39, `+0x20`–`+0x25` are `00 20 00 00 00 00` in 501 of 501 and `+0x2E`–`+0x2F` are zero in 501 of 501; slots 0–7 vary there.
- `+0x02` has bit 0 set in 715 of 715 records, and bits 1 or 2 set in 127 records, all of slots 0–7. `+0x03` has bit 0 set in 715 of 715.
- `+0x34` is `0x00`, `0x40`, `0x80` or `0xC0` in 712 of 715; bits 2 and 3, which § 3.4 named, are set in 2 records.
- `+0x35`–`+0x3D` are nonzero in 202 of 715 records (79 of 214 in slots 0–7, 123 of 501 in 8–39).
- Read as 16.16, `x` spans −9135.5 to 7738.0 and `z` −6779.5 to 7645.7; `y` is at most 0 in 715 of 715.

**Verdict.** Adopted: the leading word is the 0-based prop slot (handbook slot − 1), stored only for occupied slots, and the trailing word belongs to the next slot. The `velocity_vector`, `trajectory_state`, `reserved_prop` and § 3.4 readings are rejected by the constant and two-valued columns above. The new `set` probe in `verify_schemas_corpus.py` checks the slot order, the 0–39 range and the trailing word, and passes `--strict` on the 36 retail sets; the 93 community sets wait for a session with the full `corpus/siarchive`.

**Lives in.** [`set.md` § 3.1](../../../research/formats/auxiliary/set.md#31-prop-record-table-exact-64-byte-stride-0x40).
