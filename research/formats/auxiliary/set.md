---
summary: "`.SET` stage ([FMT-SET-HEADER]): 84-byte header, 67-byte events from 0x54, one 64-byte record per occupied prop slot (0-39); `TYPESET.EXE` operators and printed prop fields; 129 sets close."
sidebar_label: ".SET scenery & world layout"
---
# Specification: .SET Scenery & World Layout Format

## 1. Overview & File Identification

The `.SET` format encapsulates complete world scenes, stage configurations, prop placements, environmental conditions, and scripted event triggers used throughout *Stunt Island*.
It is the primary scene definition format, written and read only by the Set Designer subsystem in `STUNT.EXE`; the string evidence is in [`research/stunt-exe/sets.md`](../../stunt-exe/sets.md).
Neither `makeone.img` nor `playone.img` contains the `.SET` string — both reference only `VAULT\*.TKE`, `VAULT\*.FLM`, `VAULT\SPOOL.$$$` and `VAULT\*.*` — so the film linker and the player reach a set through the `.ALL` archive rather than by opening the file.

- **File Extension:** `.SET`
- **Magic Bytes:** None in the initial header word.
  Instead, `.SET` files begin with an ASCII stunt name string (`0x00`–`0x1D`) and contain a structural magic constant `0x08` at byte offset `0x52`.
- **Typical Container / Storage:** Loose files in `SETS\` or `VAULT\` directories, or packed as raw byte stream resources inside custom `.RES` archives (e.g. `SETS.RES`).
- **Byte Endianness:** Little-endian (standard x86 16-bit real mode).
- **Engine Lifecycle Role:**
  1. *Staging & Environment Initialization:* Configures global stage parameters including time of day (which modulates palette lighting ramps via Mode 13h DAC lookup tables), initial camera view modes, default vehicle equipment (landing gear, flaps, wheel brakes), and weapon payloads.
  2. *Prop Entity Instantiation:* Allocates and positions both static scenery props (buildings, trees, runway lights) and dynamic actor entities (aircraft, ground vehicles, cameras) in world space.
  3. *Scripted Event Triggering:* Drives deterministic gameplay and cinematic triggers (timed explosions, dynamic camera cuts, audio cue playback, and vehicle autopilot takeover).

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization).
**Contract and code:** [`contracts/shape/mod.rs`](../../../crates/stunt-core/src/contracts/shape/mod.rs) and [`contracts/vfs.rs`](../../../crates/stunt-core/src/contracts/vfs.rs).
A synthetic scene ([`synthetic_minimal.set`](../../../tests/fixtures/README.md)) exercises the schema offline through [`tests/test_set_schema.py`](../../../tests/test_set_schema.py).

---

## 2. Header & Memory Layout

A `.SET` file begins with an 84-byte (`0x54`) global environment header containing mission metadata, vehicle configuration, and table count indicators.
[`set.ksy`](set.ksy) is the executable layout for the header, the event records and the prop stride; this section gives their meaning.

### 2.1 Global Environment Header (`0x0000`–`0x0053`) (`# [FMT-SET-HEADER]`)

Offsets and widths live in [`set.ksy`](set.ksy); the table gives each field's meaning and its evidence.

| Field | Meaning | Evidentiary Tier |
| :--- | :--- | :--- |
| `stunt_name` | ASCII stunt or mission title, space-padded or null-terminated | `[Established]` |
| `reserved1` | Header alignment padding (typically zeroed) | `[Bounded Observation]` |
| `recording_mode` | Film recording flag: `0x00` = Off, `0x01` = Auto, `0x02` = On; `0xFF` also occurs (see below) | `[Established]` |
| `first_take_bonus` | Cash award for completing stunt on the first take | `[Established]` |
| `crash_penalty` | Cost deducted from budget upon aircraft or prop destruction | `[Established]` |
| `vehicle_flags` | Initial player vehicle mechanical state bitmask (see § 2.2) | `[Established]` |
| `reserved2` | Structural alignment byte | `[Bounded Observation]` |
| `time_of_day` | Simulation time scalar (`0..65535`), modulating palette lighting ramp; encoding unconfirmed (§ 3.5) | `[Bounded Observation]` |
| `reserved3` | Internal engine padding | `[Bounded Observation]` |
| `default_camera` | Default active camera rig index (`cam_id - 1`) | `[Established]` |
| `weapon_type` | Primary player vehicle armament: `0` = None, `1` = Machine Gun, `2` = Missiles, `3` = Bombs | `[Established]` |
| `max_takes` | Maximum allowed filming retakes (default: `99`) | `[Established]` |
| `take_penalty` | Budget deduction per retake | `[Established]` |
| `reserved_settings` | Camera rig tuning and sensitivity parameters | `[Bounded Observation]` |
| `initial_view_mode` | Initial viewpoint mode index (see § 2.3) | `[Established]` |
| `reserved4` | Reserved alignment and internal runtime pointers | `[Bounded Observation]` |
| `magic` | Structural validation constant `0x08` | `[Established]` |
| `num_events` | Number of event records. Agrees with the printed event count of six of the seven sets that have a dump (1, 1, 8, 2, 2, 10); `REMOTE.SET` stores 1, an all-zero record, and its dump prints no event | `[Bounded Observation]` |

`num_events` is a single byte at `0x53`, so the encoding admits 255 events while the authoring tools expose 64: an **authored limit**, not a field bound ([`GLOSSARY.md`](../../../GLOSSARY.md)).
The prop count is not stored in a dedicated header byte at all — the seven dumped sets carry 3 to 39 props and no header byte matches them; [`set.ksy`](set.ksy) derives it from the remaining length.

The header is 84 bytes, ending at `0x53`.
The 12 bytes this table used to list at `0x54`–`0x5F` are the first event record's leading fields, not a table header; see § 3.5.

The recording byte is the authoring screen's Global-Rec setting: the handbook names the three values Off, Auto and On, and states that an event's `Start Rec` or `Stop Rec` overrides this byte and every other recording setting (*handbook* p.97).
It records authored policy rather than per-frame data; whether `PLAYONE.EXE` reads it is not established.
Two corpus sets that both print `Initial Recorder :On` store different bytes — `0x02` in `BOMBING.SET` and `0xFF` in `DRIVING.SET` — so `0xFF` is not reliably an unset sentinel and its meaning is open.

### 2.2 Vehicle Mechanical State Bitmask (`vehicle_flags`, Offset `0x2C`)

The vehicle state byte configures control surfaces and landing gear upon world load:

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | Reserved (0)  | B | F | G |
     +---+---+---+---+---+---+---+---+
                       |   |   +-- Gear State: 0 = Down, 1 = Up
                       |   +------ Flaps State: 0 = Up, 1 = Down
                       +---------- Brakes State: 0 = Off, 1 = On
```

### 2.3 Viewpoint Modes (`initial_view_mode`, Offset `0x3E`)

The viewpoint mode selects the initial camera tracking perspective:
- `0x00`: Pilot Cockpit (with virtual instrument panel)
- `0x01`: Pilot Forward View (no cockpit overlay)
- `0x02`: Left Side Chase View
- `0x03`: Right Side Chase View
- `0x04`: Rear Chase View
- `0x05`: Bomb Bay / Downward View
- `0x06`: Spotter Plane Observation View

---

## 3. Data Structures & Opcode Table

### 3.1 Prop Record Table (Exact 64-Byte Stride `0x40`)

Prop records begin where the events end, at `0x54 + 67 × num_events`, and run to end of file in 64-byte strides (§ 3.5).
[`set.ksy`](set.ksy) owns that stride and leaves each record's fields raw.

**A record is stored only for an occupied prop slot.**
Its leading word is the slot number, 0-based, so the handbook's prop slot 1, the stunt aircraft, is word 0: the authoring tools offer 40 slots, of which slots 1 to 8 record film (*handbook* p.62; [`GLOSSARY.md`](../../../GLOSSARY.md)).
On all 129 corpus sets (2,032 records) the word strictly increases through each file, never exceeds 39 and starts at 0, matching `STUNT.EXE`'s `Prop 1 needs to be placed` ([`sets.md` § 2](../../stunt-exe/sets.md#2-stuntexe-alone-reads-and-writes-set)).
`TYPESET` prints a set's props as `Prop #N` for exactly the stored words `N − 1`, in the 80 props of the 7 printed sets the corpus holds.
114 of the 129 sets skip at least one slot, so the word equals its record index only up to the first empty slot.
This explains the sweep's 427 words at or above their set's record count and its 1,262 words that differ from their index.
`[Supported Inference]`: the handbook names the 40 slots, the printed dumps number them, and the bytes keep to them in every set.
`mise run verify-corpus -- --schema set --strict` checks the start, the order, the range and the trailing word below, and passes on all 129 sets.

**The trailing word belongs to the next slot.**
Bytes `+0x3E`–`+0x3F` equal bytes `+0x02`–`+0x03` of the record for the next slot number in 1,725 of 1,725 records whose next slot is present, which reads as the editor writing 62 bytes from a table of 60-byte entries.
`[Supported Inference]` for the equality; the write itself has not been read in `STUNT.EXE`.

_Source: [prop slot words and per-offset columns on the retail sets](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-17-prop-slot-words-and-per-offset-columns-on-the-retail-sets)._
_Source: [prop slot rules and columns on all 129 sets](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-20-prop-slot-rules-and-columns-on-all-129-sets)._

> **Historical Stride Correction:** Early community analysis notes (Neil Halelamien, 2004) asserted that "Every prop takes (16*5=80 bytes)".
> Empirical analysis of record deltas ($0xD6 - 0x97 + 1 = 0x40 = 64\text{ bytes}$) disproves this typo: each record is strictly **64 bytes (0x40)**, perfectly aligning with four 16-byte paragraph blocks in real-mode x86 memory.

**The printed dumps name most fields.**
`TYPESET` prints each prop's settings by name, and a field below that cites a printed name matches it in every dumped prop that prints it, over the 7 printed sets the corpus holds; the counts are in the journal entry.
The method decides what some fields hold: a Seek, Spot, Follow or Attach prop acts on its method object, and Spot, Follow and Attach props store a distance and an offset from it where Face, Free and Seek props store a speed and a heading (*handbook* p.68).
`TYPESET` prints an angle at `+0x16` or `+0x2A` as the negated BAM value: a stored `0xC000` (−90°) prints as yaw 90.

_Source: [printed set dumps against the prop bytes](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-20-printed-set-dumps-against-the-prop-bytes)._

The *Observed* column counts the 2,032 records of the 129 sets, split where it matters into slots 0–7 (642 records, the recording slots) and 8–39 (1,390).
A field named *unknown* has no reading yet.

| Relative Offset | Size | Type | Field Name | Description | Observed | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | 2 | `u16` (LE) | `prop_slot_id` | Prop slot, 0-based (handbook slot − 1, printed `Prop #`); stored slots only, ascending | 0–39, ascending from 0 in 129 of 129 sets; high byte 0 in 2,032 | `[Supported Inference]` |
| `+0x02` | 1 | `u8` | `behavior_flags` | Behavior and interaction bitfield (see § 3.2) | bit 0 set in 2,028; bits 1–2 set in 362, 40 of them in slots 8–39 | `[Supported Inference]` |
| `+0x03` | 1 | `u8` | `placement_flags` | World placement and shadow bitfield (see § 3.3) | bit 0 set in 2,030 | `[Bounded Observation]` |
| `+0x04` | 2 | `u16` (LE) | `object_model_id` | Catalog ID mapping `.SOD` geometry: `(res_index << 8) \| item_index` | varies | `[Established]` |
| `+0x06` | 4 | `i32` (LE) | `coord_x_fixed` | East/West position in 16.16 fixed point: $X = (x_{\text{editor}} - 100000) / 10$; printed E/W | −10030.0 to 10000.0 | `[Established]` |
| `+0x0A` | 4 | `i32` (LE) | `coord_y_fixed` | Altitude in 16.16 fixed point, negated: $y = -\text{altitude}_{\text{editor}} / 10$, so up is negative | −4107.3 to 0.0 | `[Supported Inference]` |
| `+0x0E` | 4 | `i32` (LE) | `coord_z_fixed` | North/South position in 16.16 fixed point: $Z = (z_{\text{editor}} - 100000) / 10$; printed N/S | −10030.0 to 10000.0 | `[Established]` |
| `+0x12` | 2 | `i16` (LE) | `roll_bam` | Roll orientation angle in 16-bit BAM ($0..65535 \equiv 0..2\pi$) | varies | `[Established]` |
| `+0x14` | 2 | `i16` (LE) | `pitch_bam` | Pitch orientation angle in 16-bit BAM | varies | `[Established]` |
| `+0x16` | 2 | `i16` (LE) | `yaw_bam` | Yaw (heading) orientation angle in 16-bit BAM; printed Yaw is its negation | varies | `[Established]` |
| `+0x18` | 2 | `u16` (LE) | `unknown_18` | Unknown; never nonzero; flipped, no printed change | 0 in 2,032 | `[Bounded Observation]` |
| `+0x1A` | 2 | `i16` (LE) | `watch_object` | Slot the prop watches (printed Watch Object − 1); the watch switch is § 3.2's bit 1 | −1 in 306, all with watch off; positive values name a slot present in the same set in 126 of 130, never the prop's own | `[Supported Inference]` |
| `+0x1C` | 2 | `i16` (LE) | `method_object` | Slot a Seek, Spot, Follow or Attach prop acts on (printed Method Object − 1) | −1 in 27; positive values name a slot present in the same set in 313 of 319, never the prop's own | `[Supported Inference]` |
| `+0x1E` | 2 | `u16` (LE) | `speed` | Face, Free and Seek props: speed, about 12.01 per printed unit (§ 3.5's `change speed` scale). Spot, Follow and Attach: printed Distance × 51.2 | varies | `[Supported Inference]` |
| `+0x20` | 2 | `u16` (LE) | `zoom` | Camera zoom × 8192, so `0x2000` is 1.0; printed for slots 0–7 only | `0x2000` in 1,390 of 1,390 in slots 8–39; 0.20 to 7.99 | `[Bounded Observation]` |
| `+0x22` | 2 | `i16` (LE) | `roll_anim` | Printed Roll Anim, in degrees per second | `+0x22`–`+0x27` nonzero in 103 (50 in slots 0–7) | `[Bounded Observation]` |
| `+0x24` | 2 | `i16` (LE) | `pitch_anim` | Printed Pitch Anim | see `+0x22` | `[Bounded Observation]` |
| `+0x26` | 2 | `i16` (LE) | `yaw_anim` | Printed Yawing Anim, negated | see `+0x22` | `[Bounded Observation]` |
| `+0x28` | 2 | `i16` (LE) | `heading_pitch_bam` | Heading pitch, or for Spot, Follow and Attach the offset pitch, in BAM | nonzero in 406 | `[Supported Inference]` |
| `+0x2A` | 2 | `i16` (LE) | `heading_yaw_bam` | Heading yaw, or for Spot, Follow and Attach the offset yaw, in BAM; printed as its negation | nonzero in 485 | `[Supported Inference]` |
| `+0x2C` | 2 | `i16` (LE) | `heading_pitch_anim` | Printed Heading Pitch Anim on the Free props, Offset Pitch Anim on the Spot prop | `+0x2C`–`+0x2F` nonzero in 50 (14 in slots 0–7) | `[Bounded Observation]` |
| `+0x2E` | 2 | `i16` (LE) | `heading_yaw_anim` | Printed Heading Yaw Anim on the Free props, Offset Yaw Anim on the Spot prop, negated | see `+0x2C` | `[Bounded Observation]` |
| `+0x30` | 1 | `u8` | `method` | Prop method: `0` Face, `1` Free, `2` Seek, `3` Spot, `4` Follow, `5` Attach, the handbook's order (*handbook* p.68) | 0–5 in 2,032 | `[Supported Inference]` |
| `+0x31` | 1 | `u8` | `method_high` | High byte of the method word `TYPESET` reads at `+0x30`; every nonzero value tried changes the prop's printed lines or its method name, except `0x40` on the Spot prop | 0 in 2,032 | `[Bounded Observation]` |
| `+0x32` | 2 | `i16` (LE) | `acceleration` | Printed Acceleration on the Free props, Distance Anim on the Spot prop, as about 0.2601 × the word (`0x4000` prints 4261, § 3.5's `change acceleration` scale) | `+0x32`–`+0x33` 0 in 2,009 | `[Bounded Observation]` |
| `+0x34` | 1 | `u8` | `display_flags` | Bitfield; bit 6 set hides the prop (see § 3.4) | `0x00`, `0x40`, `0x80` or `0xC0` in 2,029 of 2,032 | `[Bounded Observation]` |
| `+0x35`–`+0x3D` | 9 | `u8[9]` | `unknown_35` | Unknown; not padding; flipped, no printed change | nonzero in 607 | `[Bounded Observation]` |
| `+0x3E`–`+0x3F` | 2 | `u8[2]` | `next_slot_flags` | Copy of the next slot's `+0x02`–`+0x03` | equal in 1,725 of 1,725 where that slot is present | `[Supported Inference]` |

The dumps print every Anim value, Acceleration and Distance Anim as 0 in the 7 sets the corpus holds.
The sweep flipped `+0x22`–`+0x27`, `+0x2C`–`+0x2F`, `+0x31` and `+0x32` on four `BOMBING.SET` prop records (Face, Spot and two Free) and compared the resulting `TYPESET` dumps.
The sweep tested Locked on all four records and Placed on the Face prop in slot 0.
Every tested anim word prints within 1 of $\text{value} \times 360 / 65536 \times 50$, so `0x4000` prints 4500 and `0x0001` prints 0; the Yawing, Heading Yaw and Offset Yaw anims print negated, as the yaw angles do, and the roll and pitch anims do not.
That scale is degrees per second for a word in BAM per tick at 50 Hz, and the heading anims would then be the rates of `+0x28` and `+0x2A`; both readings are `[Supported Inference]`, since no flip shows a prop move.
Seek, Follow and Attach props were not flipped.
Where a prop's dump has no line for a field, flipping its bytes showed no change: `+0x22`–`+0x27` on the Spot prop and on the Free prop in a recording slot, whose dumps print no Roll, Pitch or Yaw, and `+0x2C`–`+0x2F` and `+0x32` on the Face prop, whose dump prints no heading or Acceleration.
`TYPESET` reads `+0x30`–`+0x31` as one method word: on the Spot prop a high byte of `0x01` prints an empty method name and `0x02` to `0x20` print `(null)`, with no other line changed, `0x40` changes nothing, and `0x80` and `0xFF` change which lines it prints; on the Face and Free props every nonzero value tried changes which lines they print.

`+0x18`–`+0x19` and `+0x35`–`+0x3D` (every single-bit flip and the fills `0x00` and `0xFF` of each byte), bit 0 of `+0x02` and bits 1, 3 and 4 of `+0x03` printed no change in any variant tried on the four props; `TYPESET` does not print them, which leaves open whether the game reads them.
`[Bounded Observation]`: one set and one `TYPESET` build (MD5 `40a0c481…`).

_Source: [TYPESET byte flips on four BOMBING.SET prop records](../../../work/2026-11/835_set-prop-fields/journal.md#2026-11-24-typeset-byte-flips-on-four-bombingset-prop-records)._

### 3.2 Prop Behavior Flags (`behavior_flags`, `+0x02`)

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | - | - | E | - | C | A | W | ? |
     +---+---+---+---+---+---+---+---+
               |       |   |   |   +-- Unknown; set in 2,028 of 2,032 records; no printed change
               |       |   |   +------ Watch: track the watch object (+0x1A)
               |       |   +---------- Autozoom
               |       +-------------- Collision
               +---------------------- Explosion: the prop can be blown up
```

Bits 1, 2, 3 and 5 each match one printed switch, Watch, Autozoom, Collision and Explosion, in every printed prop of the 7 dumped sets the corpus holds. `[Supported Inference]`
Bits 4, 6 and 7 are never set in the 2,032 records. `[Bounded Observation]`
Flipping bit 0 on four `BOMBING.SET` props, and bits 4, 6 and 7 on one, changes no printed line (§ 3.1). `[Bounded Observation]`

### 3.3 Prop Placement Flags (`placement_flags`, `+0x03`)

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | - | - | - | ? | ? | S | ? | P |
     +---+---+---+---+---+---+---+---+
                           |       +-- Placed in world (1 = active entity, 0 = empty)
                           +---------- Shadow: cast a ground shadow
```

Bit 2 matches the printed Shadow switch in every dumped prop. `[Supported Inference]`
Bit 0 is set in 2,030 of the 2,032 records, and every dumped prop prints `Placed :On`; clearing it on a `BOMBING.SET` prop prints `Placed :Off` and changes nothing else. `[Bounded Observation]`
Bit 1 is set in 1,991 records, bit 3 in 882 and bit 4 in 1,810; bits 5 to 7 are never set. `[Bounded Observation]`
Flipping bits 1, 3 and 4 on four `BOMBING.SET` props, and bits 5 to 7 on one, changes no printed line (§ 3.1). `[Bounded Observation]`

### 3.4 Prop Display Flags (`display_flags`, `+0x34`)

Bit 6 set hides the prop: it is set exactly where the dump prints `Visible :Off`, in 80 of 80 printed props. `[Supported Inference]`
On the 2,032 records the byte is `0x00`, `0x40`, `0x80` or `0xC0` in 2,029, so its other variation sits in bit 7, set in 103 records; no dumped prop sets bit 7, and every one prints `Locked :Off`.
Bit 7 is Locked: setting it on four `BOMBING.SET` props turns `Locked :Off` into `Locked :On` and changes nothing else (§ 3.1). `[Bounded Observation]`
The hidden and locked bits this section used to place at bits 2 and 3 are set in 2 records, both recording slots, and are withdrawn. `[Bounded Observation]`

### 3.5 File Layout: the Event Table at `0x54`

The event table comes first, immediately after the 84-byte header, and every event record is the same size:

$$\text{size} = \texttt{0x54} + 67 \times \text{events} + 64 \times \text{props}$$

[`set.ksy`](set.ksy) is the executable definition, including the header field names, the 67-byte record and its eight 7-byte THEN slots; this section does not repeat them.

For `BOMBING.SET` the event table is `0x54`–`0x96` and the props begin at `0x97`, which is exactly the offset the 2004 notes found by deleting a prop. `[Supported Inference]`

**Verification.**
Every set with a printed dump reproduces its own size from its printed counts: BOMBING 8/1 → 663, BOMBING2 7/1 → 599, DRIVING 15/8 → 1580, FIND&HIT 4/2 → 474, FIND&HT2 4/2 → 474, REALISM 39/10 → 3250.
It closes on all 129 sets available locally — 93 under `corpus/` (35 loose, 30 `Maverick`, 21 `Christmas_2025`, 6 `MIC-SETS`, 1 `ClawIsle`) and 36 under `corpus/stuntisl/SETS/` — with no exception, and `0x54 + 67 × num_events` lands on the prop table for each.
Reproduce it with `mise run verify-corpus -- --schema set` and `mise run verify-corpus -- --corpus corpus/stuntisl/SETS --schema set`; `tests/test_set_schema.py` covers the same shape offline.
The sweep stays out of `mise run check`, which is corpus-free by design.

**How this was established.**
`TYPESET.EXE` prints a set, so flipping one byte and re-printing maps a byte to the field it feeds ([§ 6 of the STUNT.EXE note](../../stunt-exe/sets.md)).
Every offset of `BOMBING.SET` was flipped and re-printed.

**Event fields, by flip.**
Each row is a single-byte flip that changes exactly one printed value; the field names are the ones in [`set.ksy`](set.ksy):

| Field | Flip changes |
|---|---|
| `if_type` | the whole `Event#1` block disappears, or its IF clause changes form |
| `if_object_1` | `If Any Weapon` → `If Any Object` |
| `if_object_2` | `hits …(12)` → `(11)` |
| `if_operand` | the time or count operand when the condition takes one |
| `and_1_type` | `And nothing` → `And it's before 0 seconds` |
| `action_type` (slot 1) | `Then explode` → `Then fade to` |
| `target` (slot 1) | `explode …(11)` → `(12)` |
| `action_type` (slot 2) | `And play` → `And cut to` |
| `sound_routing` (slot 2) | appends `, tape only` |
| `action_type` (slots 3–8) | each turns one `And do nothing` into `And award $0` |

The slot operand columns were read by writing a value into each byte under a known action type.

The `wait` operand (`operand` in a THEN slot) is in 50 Hz ticks, not seconds: 256 reads back as `5.12 seconds`, which is 256/50, and 5 reads back as `0.1 seconds`.
So the authored timebase in the file is the same 50 Hz clock as `[I4]`.

**The `change` operand is scaled by the property.**
Writing `0x4000` — a quarter turn in BAM — into a `change` action's 16-bit operand prints differently for each property in that slot's `secondary_operand` byte:

| Property | Printed for `0x4000` |
|---|---|
| `roll` | `90` |
| `yaw anim` | `-4500` |
| `zoom` | `2.5` |
| `speed` | `1364` |
| `acceleration` | `4261` |

So the operand is a signed 16-bit whose unit belongs to the property, not to the record:

- **Angles** (`roll`, `pitch`, `yaw` and the heading pair) are BAM at 65536 per turn, printed as degrees: `0x4000` is 90°.
- **Anim properties** are that same BAM value read as a per-tick rate and printed in degrees per second at 50 Hz with the sign flipped: `printed = -angle × 50`.
  This holds on 11 of 11 samples from `0x0000` to `0xFFFE`; the single boundary case, `0x8000`, prints `-9000` rather than `+9000` because −180° is normalised to +180° before the sign flip.
- **Scalar properties** carry their own scale, of which only `zoom` is pinned here (`0x4000` → 2.5).
  Enumerating the rest is property work, not event work.

An 11-byte clause header plus eight 7-byte slots is 67 bytes, the record size, and the last slot ends where the prop table starts.
The second AND qualifier's type printed no change when flipped, so `and_2_type` is inferred from the record's spacing rather than observed. `[Supported Inference]`

Reading the record as a 55-byte base plus 67 per further event, or as 12-byte blocks, or as a table after the props, is withdrawn: the prop-count arithmetic fits those splits equally, and only the flips distinguish them.

### 3.6 Event Operators

`TYPESET.EXE` is the tool that prints a set (`SETINFO.BAT` runs `TYPESET %1.SET > %1.TXT`), so these are the operator names the retail build itself emits.
It renders each rule through printf templates, which makes each operand's width part of the evidence: `\\1O` is an object index, `\\1b` a byte, `\\1w` a word, `\\3t` a time, `\\1m` miles per hour.
`[Established]` as vocabulary; the numeric encodings are in the tables below.

**IF** — `\\1O hits \\2O`, `\\1O crashes`, `\\1p seconds have elapsed`, `weapon count = \\1w`, `never`.

**AND** — `it's before \\1p seconds`, `it's after \\1p seconds`, `event #\\1w has happened`, `event #\\1w hasnt happened`, `flag #\\1b = \\2b`, `flag #\\1b <> \\2b`, `plane's speed < \\1m mph`, `plane's speed > \\1m mph`.

**THEN** — `do nothing`, `award $\\3w`, `play \\s`, `cut to \\1o`, `set time to \\3t`, `finish - \\r`, `change \\1o's \\2v to \\x`, `wait \\3p seconds`, `start recording`, `stop recording`, `stop \\1o`, `kill \\1o`, `explode \\1o`, `fade to \\3w%`, `set flag #\\2b to \\3b`, `modify flag #\\2b by \\3b`, `stop recording if autoediting`.

**The `change` property set (`\\2v`)** — shape, WE position, altitude, SN position, roll, pitch, yaw, roll anim, pitch anim, yaw anim, heading pitch, heading yaw, heading pitch anim, heading yaw anim, speed, acceleration, zoom, watch obj, method, method obj, visibility, collideability, auto zoom, distance.

The four `EVT_*` codes this section previously listed are withdrawn: no source in the corpus reproduces them, and the templates above are the vocabulary the binary actually uses.

### Encoding

The numeric values were read off `BOMBING.SET` by writing each value into one type byte and re-printing (§ 3.5).
`[Supported Inference]` for each table, since every entry was observed rather than inferred.

**IF condition type** (`if_type`): `0` —, `1` hits, `2` crashes, `3` seconds elapsed, `4` weapon count, `5` nothing, `6` it's before, `7` it's after.

**AND qualifier type** (`and_1_type`, `and_2_type`): `0` nothing, `1` it's before, `2` it's after, `3` event happened, `4` event hasn't happened, `5` flag =, `6` flag <>, `7` speed <, `8` speed >.
Values above `8` fall through into the action table below, which is how the two tables sit next to each other in the image.

**THEN action type** (`action_type`, in every slot): `0` do nothing, `1` award $, `2` play sound, `3` cut to, `4` set time, `5` finish, `6` change, `7` wait, `8` start recording, `9` stop recording, `10` stop, `11` kill, `12` explode, `13` fade, `14` set flag, `15` modify flag, `16` stop recording if autoediting.
Values `17` and above print the `change` property names (shape, WE position, altitude, …), again an out-of-range read into the adjacent table rather than a valid action.

The handbook enumerates the authoring actions this table encodes: `CutTo`, `Change` (with roughly twenty sub-parameters — shape, position, altitude, roll/pitch/yaw, speed, acceleration, zoom, watch target, visibility, collideability, autozoom), `Explode`, `Kill`, `Fade`, `Finish`, `Set Flag`, `Set Time`, `Start Rec`, `Stop Rec`, `Start Sound`, `Wait` and `Award $` (*handbook* pp.92–95), behind the triggers `Collision`, `Crash`, `Time` (maximum 655 seconds), `Weapon Count` and the `Never` placeholder (pp.89–90).
A `change` action carries its property in `secondary_operand` and its new value in the 16-bit `operand` (§ 3.5), so the record carries the sub-parameter directly.

### 3.7 Editor-to-World Coordinate Conversion (`[I1]`)

All positions within `.SET` are authored in Set Designer editor coordinates ranging from $0$ to $200{,}000$ integer units, with the island center located at $(100000, 0, 100000)$.
StuntReel transforms these coordinates into the metric right-handed basis ($+X$ Right/East, $+Y$ Up/Altitude, $+Z$ Backward/South, $-Z$ Forward/North) via:

$$X_{\text{world}} = \frac{X_{\text{editor}} - 100000}{10.0} \quad (\text{meters})$$

$$Y_{\text{world}} = \frac{Y_{\text{editor}}}{10.0} \quad (\text{meters})$$

$$Z_{\text{world}} = \frac{Z_{\text{editor}} - 100000}{10.0} \quad (\text{meters})$$

- **Fixed-Point Conversion:** In `.SET` binary storage, coordinates are stored as 32-bit $16.16$ signed fixed-point integers.
  To obtain floating-point meters:
  $$\text{pos}_{\text{meters}} = \frac{\text{raw\_i32}}{65536.0}$$
- **Sign:** a prop record stores its altitude negated, $y = -\text{altitude}_{\text{editor}} / 10$ (§ 3.1), so $Y_{\text{world}} = -y$.
- **Scale Factor:** Exactly 10 Set Designer editor units equal 1.0 meter in world coordinates.
  An island width of 200,000 units spans 20,000 meters (20 kilometers).

---

## 4. Open Questions & Analysis Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-SET-01]` | Vehicle Tuning Bytes (`reserved_settings`) | Precise aerodynamic scalar mappings governing flight control sensitivity and elevator response in Set Designer. | `[Unknown]` |
| `[BK-SET-02]` | Unknown Prop Bytes | Narrowed: `TYPESET` flips on four props named the bytes it prints as the anims and as Acceleration or Distance Anim, the method word's high byte, and Locked; Placed was flipped on one prop (§ 3.1). Still unknown, and printing nothing when flipped: `+0x18`–`+0x19`, `+0x35`–`+0x3D`, bit 0 of `+0x02`, and bits 1, 3 and 4 of `+0x03`. Naming them needs the game's own reads, in `STUNT.EXE` or `PLAYONE.EXE`, not the printer. | `[Bounded Observation]` |
| `[BK-SET-03]` | `change` Operand Scales | The 16-bit `change` operand is BAM for angles and ×50 for anim properties (§ 3.5); only `zoom` is pinned among the scalar properties, and `speed`'s 1364 for `0x4000` matches the prop record's 12.01 per printed unit (§ 3.1), while `zoom`'s 2.5 differs from the record's 8192 per unit. | `[Bounded Observation]` |
| `[BK-SET-04]` | Prop Record Field Map | Closed: the leading word is the 0-based prop slot, stored only for occupied slots, and the trailing word copies the next slot's flags, on all 129 sets and 2,032 records; the printed dumps name most other fields, and every byte is named or marked unknown with a count (§ 3.1). The unknown bytes are `[BK-SET-02]`. | `[Supported Inference]` |
| `[BK-SET-05]` | Event Action-Code Catalogue | Map the handbook's THEN actions (*handbook* pp.92–95) onto `action_type` values. Progress: `num_events` at `0x53` enumerates a set's rules, § 3.6 fixes codes `0`–`16`, and the record is 67 bytes; open is whether every handbook action has exactly one code. | `[Hypothesis]` |

---

## 5. Attribution & Provenance

The technical specifications for the `.SET` format are synthesized from the following primary community research and analysis artifacts:

- **Neil Halelamien (2004):** Analysis of `.SET` file structures, binary diff analysis of Set Designer output files (`100000.SET`, `NOPROP1.SET`), bitmask decoding of vehicle and prop state flags, and the 2004 SIFA email thread (`corpus/siarchive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`, `corpus/siarchive/Developer/Notes_SETFile/SET_File_Email_Thread.txt`).
- **Dave Palmowski (1999–2004):** Analysis of prop list insertion for custom shockwave generators and prop catalog indices (`corpus/siarchive/Developer/Notes_SETFile/SET_File_Email_Thread.txt`).
- **Dean Newbury (2004):** SIFA correspondence and prop slot constraint analysis.
- **Doug Armknecht (2000–2002):** World coordinate space and island center offset documentation in film trajectory analyses (`corpus/siarchive/Developer/SI_FLM_Format/FLM_NOTES.md`).
- **The Assembly Line / Disney (1992):** The retail handbook (`corpus/siarchive/Docs/Manual/`), read as a primary source for authoring semantics; see [`research/handbook.md`](../../handbook.md).
- **Disney tutorial sets (1993):** Six sets printed by `TYPESET` in four `.TXT` files under `corpus/siarchive/Misc/Sets/` (`BOMBING`, `BOMBING2`, `DRIVING`, `FIND&HIT`, `FIND&HT2`, `REALISM`; `Printed at :Thu Jan 21 15:56:19 1993`), printed again with `REMOTE` in the revised handbook `corpus/siarchive/Docs/Disney_Support/SIUPDATE.TXT`; each dump names every header and prop setting.
- **Stunt Reel contributors (2026):** Resolution of the 80-byte stride historical error to exact 64-byte (`0x40`) stride, validation of 16.16 fixed-point math, and contract alignment.

---

## Ruled out

- *`prop_slot_id` as the record index*: it is the slot number, and every retail set skips at least one slot ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-17-prop-slot-words-and-per-offset-columns-on-the-retail-sets)).
- *`+0x18`–`+0x1D` as a velocity vector*: `+0x18` is always zero, and `+0x1A` and `+0x1C` hold −1, 0 or a slot number ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-17-prop-slot-words-and-per-offset-columns-on-the-retail-sets)).
- *`+0x20`–`+0x33` as a 20-byte trajectory state, `+0x35`–`+0x3F` as padding, and the hidden and locked bits of § 3.4*: the column counts in § 3.1 and § 3.4 contradict each ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-17-prop-slot-words-and-per-offset-columns-on-the-retail-sets)).
- *`+0x20`–`+0x25`, `+0x2E`–`+0x2F` and bits 1–2 of `+0x02` as set only for recording slots*: true of the retail sets, but community sets break them in slots 8–39 in 36, 32 and 40 records ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-20-prop-slot-rules-and-columns-on-all-129-sets)).
- *Visibility as bit 6 of `+0x02`*: that bit is never set in 2,032 records, and the printed Visible switch follows bit 6 of `+0x34` ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-20-printed-set-dumps-against-the-prop-bytes)).
- *0 at `+0x1A` or `+0x1C` as "no slot"*: the dumps print it as object 1, slot 0 ([journal](../../../work/2026-11/483_set-prop-slots/journal.md#2026-11-20-printed-set-dumps-against-the-prop-bytes)).
- *`+0x18`–`+0x19` or `+0x35`–`+0x3D` as a printed setting*: no flip of them tried on four `BOMBING.SET` props changes any line `TYPESET` prints, while the printed anims, Acceleration, Distance Anim, Locked and Placed each sit elsewhere ([journal](../../../work/2026-11/835_set-prop-fields/journal.md#2026-11-24-typeset-byte-flips-on-four-bombingset-prop-records)).

## Open questions

The backlog in § 4 is this note's open work, in its order there; `[BK-SET-04]` is closed.
`[BK-SET-02]`'s remaining bytes print nothing under `TYPESET`, so naming them needs the game's own reads of the prop record.
Ten slot references, in 9 records of 6 sets, name a slot the set does not store; whether the player ignores them is open.
§ 3.5's sign flip for anim properties was measured on `yaw anim`; the prop records print roll and pitch anims unnegated (§ 3.1), so whether a `change roll anim` or `change pitch anim` operand prints negated is open.
