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

## 2026-11-20: prop slot rules and columns on all 129 sets

**Question.** Do the slot rules the retail sets gave hold on the 93 community sets under `corpus/siarchive`, and what does § 3.1's *Observed* column read over all 2,032 records?

**Method.** Local Windows, full data root, on `3a09d4c0`. `mise run verify-corpus -- --schema set --strict`, first as merged and again after adding a first-slot-is-0 rule to the `set` probe. Then a one-off script cut each of the 129 sets at `0x54 + 67 × num_events` into 64-byte records and repeated the previous entry's counts, split retail (36 sets, 715 records) against community (93 sets, 1,317 records); it reproduces every retail figure of the previous entry.

**Result.**

- The sweep parses 129 of 129 with 0 anomalies, before and after the first-slot rule.
- The slot word strictly increases, stays in 0..39 and starts at 0 in 129 of 129 sets; its high byte is 0 in 2,032 of 2,032. 114 sets skip at least one slot; the 15 that do not are all community sets. 427 words are at or above their set's record count (137 retail, 290 community) and 1,262 differ from their record index (503, 759), so 770 equal it. Every one of the 427 and the 1,262 sits in a set that skips a slot, each of the 114 such sets holds at least one of the 427, and the 15 sets that skip none hold no mismatch.
- Slots 0–7 hold 642 records and slots 8–39 hold 1,390.
- The trailing word equals the next slot's `+0x02`–`+0x03` in 1,725 of 1,725 records whose next slot is present (1,099 of 1,099 community). Of the 307 records whose next slot is absent (129 last in their set), the high byte is `0x00` in 256.
- Positive `+0x1A` values name a slot present in the same set in 126 of 130 records, positive `+0x1C` values in 313 of 319; neither names its own slot. The 10 values that name an absent slot sit in 9 records of 6 sets (`BRNTRICK`, `COLISEUM`, `TOPGUN20`, `TOPGUN23`, `TOPGUN24` and retail `CASTLE`), 3 of those records with the watch bit set. Non-positive values: `+0x1A` 0 in 1,596 and −1 in 306; `+0x1C` 0 in 1,686 and −1 in 27.
- `+0x01`, `+0x18`, `+0x19` and `+0x31` are zero in 2,032 of 2,032.
- Three retail-only observations fail on community sets. In slots 8–39, `+0x20`–`+0x25` are `00 20 00 00 00 00` in 1,354 of 1,390 (the 36 others in `TAJMHALL`, `TOPGUN14`, `TOPGN12A` and `TOPGUN24`), and `+0x2E`–`+0x2F` are zero in 1,358 of 1,390 (the 32 others in `TAJMHALL`, `BEARS` and `TANK`). Bits 1 or 2 of `+0x02` are set in 362 records, 40 of them in slots 8–39 across 9 sets.
- `+0x02` per bit 0–7: 2,028, 353, 86, 780, 0, 91, 0, 0 records; the 4 with bit 0 clear are all in `TOPGUN12`. `+0x03` per bit: 2,030, 1,991, 381, 882, 1,810, 0, 0, 0; the 2 with bit 0 clear are in `AQUA_JET` and `GRISWLD1`.
- `+0x30` is 0 in 272, 1 in 1,240, 2 in 11, 3 in 266, 4 in 57 and 5 in 186.
- `+0x26`–`+0x2F` are nonzero in 660; `+0x32`–`+0x33` are zero in 2,009. By the field split of the next entry: the `u16` at `+0x20` is `0x2000` in 1,390 of 1,390 records of slots 8–39 and differs from it in 169 of 642 of slots 0–7; `+0x22`–`+0x27` are nonzero in 103 (50 in slots 0–7, 53 in 8–39); the words at `+0x28` and `+0x2A` are nonzero in 406 and 485; `+0x2C`–`+0x2F` are nonzero in 50 (14, 36).
- `+0x34` is `0x00`, `0x40`, `0x80` or `0xC0` in 2,029 of 2,032; bit 6 is set in 977 and bit 7 in 103; bits 2 or 3 are set in the same 2 retail records as before.
- `+0x35`–`+0x3D` are nonzero in 607 (229 of 642 in slots 0–7, 378 of 1,390 in 8–39).
- Read as 16.16, `x` and `z` each span −10030.0 to 10000.0, and `y` spans −4107.3 to 0.0; the 8 records below the retail minimum of −2009.1 are all in `TOPGUN27`.

**Verdict.** Adopted: the slot reading and the trailing-word rule hold on all 129 sets, so nothing goes into `KNOWN_ANOMALIES` and the probe now also requires slot 0, as `STUNT.EXE`'s `Prop 1 needs to be placed` does. Rejected: "set only for recording slots" for `+0x20`–`+0x25`, `+0x2E`–`+0x2F` and `+0x02` bits 1–2, which community sets break.

**Lives in.** [`set.md` § 3.1](../../../research/formats/auxiliary/set.md#31-prop-record-table-exact-64-byte-stride-0x40).

## 2026-11-20: printed set dumps against the prop bytes

**Question.** Which prop bytes do `TYPESET`'s printed set dumps name?

**Method.** Same commit and data root. Of the 22 `.TXT` files under `corpus/siarchive/Misc/Sets/` (one of them the `Christmas_2025` README), four print set dumps: `BOMBING.TXT` (`BOMBING`, `BOMBING2`), `DRIVING.TXT`, `FIND&HIT.TXT` (`FIND&HIT`, `FIND&HT2`) and `REALISM.TXT`; the other 18 print no set. The issue's and § 5's "22 printed dumps" counts files, not dumps. The revised handbook `Docs/Disney_Support/SIUPDATE.TXT` prints 15 dumps: those six again, `REMOTE.SET`, and eight sets the corpus does not hold (`HELICOPT`, `MIG291`, `MIG292`, `INVPOWER`, `SMOKE`, `HEATSEEK`, `SPINPAN`, `TEMP`). That gives seven sets and 80 props to match. A one-off script parsed each dump's `Prop #N` blocks, matched each to the record whose slot word is `N − 1`, and tested every printed field against each byte, bit, `i16` and `i32` of the record. Every count below is the same whether the six repeated sets are read from `Misc/Sets/` or from `SIUPDATE.TXT`.

**Result.**

- The printed props are exactly the stored slots, `Prop #N` for slot word `N − 1`, in 7 of 7 sets and 80 of 80 props.
- Each On/Off field matches exactly one bit, in every printed prop: Watch is `+0x02` bit 1 (80 props, 28 On), Autozoom bit 2 (34, 3 On), Collision bit 3 (80, 26 On), Explosion bit 5 (80, 4 On), Shadow `+0x03` bit 2 (80, 12 On), and Visible is `+0x34` bit 6 clear (80, 41 On). Placed is On and Locked Off in all 80, so no bit is tested for either.
- Method is `+0x30`, one-to-one over 80 props: Face 0, Free 1, Seek 2, Spot 3, Follow 4, Attach 5, the order in which the handbook lists them (*handbook* p.68, `SIManual.txt:4058`). The one Seek prop is `REMOTE.SET`'s slot 2.
- Watch Object is `+0x1A` + 1 in 80 of 80 (3 distinct values) and Method Object is `+0x1C` + 1 in 14 of 14 (4 distinct), so 0 is slot 0, not "none". In the corpus, −1 at `+0x1A` comes only with the watch bit clear (306 of 306).
- Angles, in BAM: Yaw is the negated `+0x16` (52 of 52, 9 distinct); Heading Yaw (59 of 59, 6 distinct) and Offset Yaw (13 of 13, 6 distinct) are the negated `+0x2A`; Offset Pitch is `+0x28` (13 of 13, 6 distinct), and Heading Pitch, printed 0 in all 59, reads 0 there too. Pitch and Roll print 0 in all 52, so their scale is untested.
- `+0x1E` holds Speed as `round(raw / 12.01)` in Free, Face and Seek props (67 of 67, 6 distinct), and Distance as `round(raw / 51.2)` in Spot, Attach and Follow props (13 of 13, 8 distinct). § 3.5's `change speed` operand `0x4000` printing `1364` is the same scale (16384 / 1364 = 12.01).
- Zoom is the `u16` at `+0x20` over 8192 (34 of 34, 2 distinct: 1 and 1.58), printed for the 34 props in slots 0–7 and for no other. In the corpus it is `0x2000` in 1,863 of 2,032 and spans 0.20 to 7.99. § 3.5's `change zoom` operand prints `0x4000` as 2.5, not 2.0, so the event operand and the record use different zoom scales.
- E/W and N/S match the 16.16 `x` and `z` under § 3.1's formula (67 of 67; 57 and 44 distinct), and Altitude is −10 × `y` (67 of 67, 28 distinct): the stored `y` is negated.
- `REMOTE.SET` stores `num_events` 1, an all-zero 67-byte record, and its dump prints no event; the other six agree with § 2.1.
- Every Anim field, Acceleration and Distance Anim print 0 in the seven matched dumps (one nonzero Anim, in `SPINPAN`, has no file), so the dumps cannot name `+0x22`–`+0x27`, `+0x2C`–`+0x2F`, `+0x32`–`+0x33` or `+0x35`–`+0x3D`.

**Verdict.** Adopted: the field names above. Rejected: § 3.2's visibility bit at `+0x02` bit 6, which is never set in 2,032 records, while Visible follows `+0x34` bit 6; and 0 at `+0x1A` or `+0x1C` as "no slot", which prints as object 1.

**Lives in.** [`set.md` § 3.1–3.4](../../../research/formats/auxiliary/set.md#31-prop-record-table-exact-64-byte-stride-0x40); the dump count in [`sets.md` § 5](../../../research/stunt-exe/sets.md#5-the-retail-install-and-typesetexe).
