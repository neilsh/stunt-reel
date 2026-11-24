# Journal

## 2026-11-24: TYPESET byte flips on four BOMBING.SET prop records

**Question.** Which printed field, if any, reads each prop-record byte and bit that [`set.md`](../../../research/formats/auxiliary/set.md) § 3.1 still calls unknown (`[BK-SET-02]`): `+0x18`–`+0x19`, `+0x22`–`+0x27`, `+0x2C`–`+0x2F`, `+0x31`–`+0x33`, `+0x35`–`+0x3D`, bit 0 of `+0x02`, bits 1, 3 and 4 of `+0x03`, and bit 7 of `+0x34`?

**Method.** Local Windows, full data root, on `46e5b20c`.
`TYPESET.EXE` from the data root's `builds/patch3/` (28,411 bytes, MD5 `40a0c4817f7529ff078f66996eddb125`; the `unpatched`, `patched` and `corpus/stuntisl` copies have the same MD5), under DOSBox-X 2026.10.01 (the SDL1 `bin/x64/Release` build mise pins), on `corpus/siarchive/Misc/Sets/BOMBING.SET` (663 bytes, MD5 `197fd3ce70e51d8d5533d5012cb31093`).
`mise run typeset-flip` (new, [`typeset_flip.py`](../../../python/scripts/typeset_flip.py)) writes one copy of the set per variant, prints all of them with `TYPESET` in one `dosbox-x -silent` session, and diffs each dump against the unflipped set's dump, ignoring the `File Name` and `Printed at` lines.
For each byte the variants are its eight single-bit flips and the fills `0x00` and `0xFF`, skipping any equal to the stored byte, so a byte gets 9 or 10; each listed bit is flipped alone.
Round 1, `mise run typeset-flip` with its defaults: slots 1 (Spot, printed `Prop #2`), 3 (Free, a recording slot, `Prop #4`) and 10 (Free, `Prop #11`), every listed byte and bit: 681 variants.
Round 2, `mise run typeset-flip -- --slots 0 --bits 0x02:0,0x02:4,0x02:6,0x02:7,0x03:0,0x03:1,0x03:3,0x03:4,0x03:5,0x03:6,0x03:7,0x34:7 --out build/typeset-flip-r2`: slot 0 (Face, `Prop #1`), the same bytes, and every bit of `+0x02` and `+0x03` that is unknown or never set, plus `+0x03` bit 0: 234 variants.
The raw per-variant results, with each changed printed value and no dump text, are [`typeset-flip-round1.csv`](typeset-flip-round1.csv) and [`typeset-flip-round2.csv`](typeset-flip-round2.csv).

**Result.**

- **Timing.** Round 1, 682 dumps including the base, took about 7 s wall clock for the whole command with `-silent`, under the script's own conf (`output = surface`, `core = dynamic`, `cycles = max`, `memsize = 16`), the stage directory ending at 1,367 files (about 685 when DOSBox-X started); a single dump, `dosbox-x -silent -conf tools/dosbox/dosbox-utils.conf` running one `typeset` line, took about 1 s. Both are whole seconds from `date`, with no kept log. Each launch returned only after the guest had written its dumps.
  Every one of the 915 variants produced a dump file; the script reads no guest exit code, so whether `TYPESET` ended cleanly on each is not checked.
- **Anim words are 16-bit**: on each prop that prints the field, every variant of a byte pair changed exactly one printed value, except a low byte of `0x01`, which prints 0 (15 variants); every printed value is within 1 of the scale below:
  - `+0x22`–`+0x23` changes Roll Anim, `+0x24`–`+0x25` Pitch Anim and `+0x26`–`+0x27` Yawing Anim, on slot 0 (Face) and slot 10 (Free).
  - `+0x2C`–`+0x2D` changes Heading Pitch Anim on slots 3 and 10 (Free) and Offset Pitch Anim on slot 1 (Spot); `+0x2E`–`+0x2F` changes Heading Yaw Anim or Offset Yaw Anim on the same props.
  - The printed value is within 1 of the signed word × 360 / 65536 × 50, as a BAM-per-tick rate would print in degrees per second at 50 Hz (a reading, not a measured motion): `0x0080` prints 35, `0x0100` 70, `0x4000` 4500, `0x8000` −9000 and `0xFF00` −70, and `0x0001` prints 0 (0.27 rounded).
    The yaw anims print negated (`0x4000` prints −4500, `0x8000` prints 9000); roll and pitch anims do not.
  - On slot 1 (Spot) and slot 3 (Free, recording slot) `+0x22`–`+0x27` printed no change in 59 of 59 and 54 of 54 variants: neither prop's dump prints Roll, Pitch or Yaw lines. On slot 0 (Face) `+0x2C`–`+0x2F` printed no change in 36 of 36: a Face prop prints no heading lines.
- **`+0x32`–`+0x33` is a 16-bit word**: Acceleration on slots 3 and 10 (Free), Distance Anim on slot 1 (Spot).
  `0x0080` prints 33, `0x0100` 67, `0x4000` 4261, `0x8000` −8523 and `0xFF00` −67, so the printed value is about 0.2601 × the word; `0x4000` → 4261 is § 3.5's printed scale for the `change acceleration` operand.
  On slot 0 (Face) it printed no change in 18 of 18: a Face prop prints no Acceleration.
- **`+0x31` is read with `+0x30` as one method word.**
  On all four props every value of `+0x31` except `0x40` on the Spot prop changed the printed dump (35 of 36 variants).
  On the Spot prop `0x01` changed only the method name, to empty, and `0x02` to `0x20` only the name, to `(null)`; `0x80` and `0xFF` changed which lines it prints.
  On the Face and Free props every value changed which lines print; the CSVs record those as `layout`, and the dumps are not kept, so which lines changed is not recorded here.
- **`+0x34` bit 7 is Locked**: on all four props it turns `Locked :Off` into `Locked :On` and nothing else.
- **`+0x03` bit 0 is Placed**, on the one prop flipped: on slot 0 clearing it turns `Placed :On` into `Placed :Off` and nothing else.
- **No printed change**, in every variant tried:
  - `+0x18` and `+0x19`: 9 variants each on each of the four props (72).
  - `+0x35` to `+0x3D`: 9 or 10 variants each on each prop (343). The stored bytes there are `19 B8 09 00 00 CD 0C 00 C0` on slots 0 and 10, `8B AC 09 78 08 88 EE 02 F6` on slot 1 and zero on slot 3.
  - `+0x02` bit 0 on all four props; bits 4, 6 and 7 on slot 0.
  - `+0x03` bits 1, 3 and 4 on all four props; bits 5, 6 and 7 on slot 0.

**Verdict.** Adopted: `+0x22`, `+0x24`, `+0x26`, `+0x2C`, `+0x2E` and `+0x32` are 16-bit words that `TYPESET` prints as the Roll, Pitch and Yawing Anim, the heading (or offset) pitch and yaw anims and the Acceleration (or Distance Anim); `+0x31` is the high byte of a 16-bit method word; bit 7 of `+0x34` is Locked on the four props and bit 0 of `+0x03` is Placed on slot 0.
`+0x18`–`+0x19`, `+0x35`–`+0x3D`, bit 0 of `+0x02` and bits 1, 3 and 4 of `+0x03` stay unknown, recorded as flipped with no printed change; `TYPESET` does not read them into any line it prints, which says nothing about whether `STUNT.EXE` or `PLAYONE.EXE` reads them.
One set, one `TYPESET` build, four props: `[Bounded Observation]`.
The slowness [`sets.md`](../../../research/stunt-exe/sets.md) § 6 measured did not occur with `-silent` under the script's conf, though the stage directory ended at twice that run's 675 entries; no run without `-silent` was repeated, and the earlier runs' build and conf are not recorded, so `-silent` is the likely cause but not an isolated one.

**Lives in.** [`set.md` § 3.1–3.4](../../../research/formats/auxiliary/set.md#31-prop-record-table-exact-64-byte-stride-0x40) and [`sets.md` § 6](../../../research/stunt-exe/sets.md#6-running-the-retail-utilities).
