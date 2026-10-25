# Specification: .SET Scenery & World Layout Format

## 1. Overview & File Identification

The `.SET` format encapsulates complete world scenes, stage configurations, prop placements, environmental conditions, and scripted event triggers used throughout *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line). It is the primary scene definition format, written and read only by the Set Designer subsystem in `STUNT.EXE`; the string evidence is in [`research/stunt-exe/sets.md`](../../stunt-exe/sets.md). Neither `makeone.img` nor `playone.img` contains the `.SET` string — both reference only `VAULT\*.TKE`, `VAULT\*.FLM`, `VAULT\SPOOL.$$$` and `VAULT\*.*` — so the film linker and the player reach a set through the `.ALL` archive rather than by opening the file.

- **File Extension:** `.SET`
- **Magic Bytes:** None in the initial header word. Instead, `.SET` files begin with an ASCII stunt name string (`0x00`–`0x1D`) and contain a structural magic constant `0x08` at byte offset `0x52`.
- **Typical Container / Storage:** Loose files in `SETS\` or `VAULT\` directories, or packed as raw byte stream resources inside custom `.RES` archives (e.g. `SETS.RES`).
- **Byte Endianness:** Little-endian (standard x86 16-bit real mode).
- **Engine Lifecycle Role:**
  1. *Staging & Environment Initialization:* Configures global stage parameters including time of day (which modulates palette lighting ramps via Mode 13h DAC lookup tables), initial camera view modes, default vehicle equipment (landing gear, flaps, wheel brakes), and weapon payloads.
  2. *Prop Entity Instantiation:* Allocates and positions both static scenery props (buildings, trees, runway lights) and dynamic actor entities (aircraft, ground vehicles, cameras) in world space.
  3. *Scripted Event Triggering:* Drives deterministic gameplay and cinematic triggers (timed explosions, dynamic camera cuts, audio cue playback, and vehicle autopilot takeover).

**Governing invariants:** [`[I1]`](../../../docs/SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization). **Contract and code:** [`contracts/shape.rs`](../../../crates/stunt-core/src/contracts/shape.rs) and [`contracts/vfs.rs`](../../../crates/stunt-core/src/contracts/vfs.rs). No synthetic `.SET` fixture exists yet.

---

## 2. Header & Memory Layout

A `.SET` file begins with a 96-byte (`0x60`) global environment header containing mission metadata, vehicle configuration, and table count indicators. The executable header layout is [`set.ksy`](set.ksy).

### 2.1 Global Environment Header (`0x0000`–`0x005F`) (`# [FMT-SET-HEADER]`)

| Offset (Hex) | Size (Bytes) | Type | Field Name | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `0x00`–`0x1D` | 30 | `char[30]` | `stunt_name` | ASCII stunt or mission title, space-padded or null-terminated | `[Established]` |
| `0x1E`–`0x26` | 9 | `u8[9]` | `reserved_header` | Header alignment padding (typically zeroed) | `[Bounded Observation]` |
| `0x27` | 1 | `u8` | `recording_mode` | Film recording flag: `0x00` = Off, `0x01` = Auto, `0x02` = On; `0xFF` also occurs (see below) | `[Established]` |
| `0x28`–`0x29` | 2 | `u16` (LE) | `first_take_bonus` | Cash award for completing stunt on the first take | `[Established]` |
| `0x2A`–`0x2B` | 2 | `u16` (LE) | `crash_penalty` | Cost deducted from budget upon aircraft or prop destruction | `[Established]` |
| `0x2C` | 1 | `u8` | `vehicle_flags` | Initial player vehicle mechanical state bitmask (see § 2.2) | `[Established]` |
| `0x2D` | 1 | `u8` | `reserved_2d` | Structural alignment byte | `[Bounded Observation]` |
| `0x2E`–`0x2F` | 2 | `u16` (LE) | `time_of_day` | Simulation time scalar (`0..65535`), modulating palette lighting ramp; encoding unconfirmed (§ 3.5) | `[Bounded Observation]` |
| `0x30` | 1 | `u8` | `reserved_30` | Internal engine padding | `[Bounded Observation]` |
| `0x31` | 1 | `u8` | `default_camera` | Default active camera rig index (`cam_id - 1`) | `[Established]` |
| `0x32` | 1 | `u8` | `weapon_type` | Primary player vehicle armament: `0` = None, `1` = Machine Gun, `2` = Missiles, `3` = Bombs | `[Established]` |
| `0x33` | 1 | `u8` | `max_takes` | Maximum allowed filming retakes (default: `99`) | `[Established]` |
| `0x34`–`0x35` | 2 | `u16` (LE) | `take_penalty` | Budget deduction per retake | `[Established]` |
| `0x36`–`0x3D` | 8 | `u8[8]` | `reserved_settings` | Camera rig tuning and sensitivity parameters | `[Bounded Observation]` |
| `0x3E` | 1 | `u8` | `initial_view_mode` | Initial viewpoint mode index (see § 2.3) | `[Established]` |
| `0x3F`–`0x51` | 19 | `u8[19]` | `reserved_pad` | Reserved alignment and internal runtime pointers | `[Bounded Observation]` |
| `0x52` | 1 | `u8` | `magic_tag` | Structural validation constant `0x08` | `[Established]` |
| `0x53` | 1 | `u8` | `event_count` | Number of event records. Agrees with the printed event count of all six sets that have a dump (1, 1, 8, 2, 2, 10) | `[Bounded Observation]` |
| `0x54` | — | — | *(end of header)* | The header stops here: `0x54` is the first byte of the first event record (§ 3.5) | `[Established]` |

`0x53` is a single byte, so the encoding admits 255 events while the authoring tools expose 64: an **authored limit**, not a field bound ([`GLOSSARY.md`](../../../GLOSSARY.md)). The prop count is not stored in a dedicated header byte at all — the six dumped sets carry 4 to 39 props and no header byte matches them.

The header is 84 bytes, ending at `0x53`. The 12 bytes this table used to list at `0x54`–`0x5F` are the first event record's leading fields, not a table header; see § 3.5.

The recording byte is the authoring screen's Global-Rec setting: the handbook names the three values Off, Auto and On, and states that an event's `Start Rec` or `Stop Rec` overrides this byte and every other recording setting (*handbook* p.97). It records authored policy rather than per-frame data; whether `PLAYONE.EXE` reads it is not established. Two corpus sets that both print `Initial Recorder :On` store different bytes — `0x02` in `BOMBING.SET` and `0xFF` in `DRIVING.SET` — so `0xFF` is not reliably an unset sentinel and its meaning is open.

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

The prop record table is documented as beginning at offset `0x0060` (or `0x0160` with extended mission briefing headers). Corpus evidence is not decisive: for 139 of 626 records read at `0x0060`, `prop_slot_id` is at least `prop_count`, so either the table start or the field layout differs in those files (`[BK-SET-04]`). `set.ksy` therefore encodes only the 96-byte header and leaves the remainder raw.

> **Historical Stride Correction:** Early community reverse engineering notes (Neil Halelamien, 2004) asserted that "Every prop takes (16*5=80 bytes)". Empirical analysis of record deltas ($0xD6 - 0x97 + 1 = 0x40 = 64\text{ bytes}$) disproves this typo: each record is strictly **64 bytes (0x40)**, perfectly aligning with four 16-byte paragraph blocks in real-mode x86 memory.

| Relative Offset | Size | Type | Field Name | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `+0x00` | 2 | `u16` (LE) | `prop_slot_id` | Prop slot index ($0, 1, 2, \dots, N-1$) | `[Established]` |
| `+0x02` | 1 | `u8` | `behavior_flags` | Behavior and interaction bitfield (see § 3.2) | `[Established]` |
| `+0x03` | 1 | `u8` | `placement_flags` | World placement and shadow bitfield (see § 3.3) | `[Established]` |
| `+0x04` | 2 | `u16` (LE) | `object_model_id` | Catalog ID mapping `.SOD` geometry: `(res_index << 8) \| item_index` | `[Established]` |
| `+0x06` | 4 | `i32` (LE) | `coord_x_fixed` | East/West position in 16.16 fixed point: $X = (x_{\text{editor}} - 100000) / 10$ | `[Established]` |
| `+0x0A` | 4 | `i32` (LE) | `coord_y_fixed` | Altitude position in 16.16 fixed point: $Y = y_{\text{editor}} / 10$ | `[Established]` |
| `+0x0E` | 4 | `i32` (LE) | `coord_z_fixed` | North/South position in 16.16 fixed point: $Z = (z_{\text{editor}} - 100000) / 10$ | `[Established]` |
| `+0x12` | 2 | `i16` (LE) | `roll_bam` | Roll orientation angle in 16-bit BAM ($0..65535 \equiv 0..2\pi$) | `[Established]` |
| `+0x14` | 2 | `i16` (LE) | `pitch_bam` | Pitch orientation angle in 16-bit BAM | `[Established]` |
| `+0x16` | 2 | `i16` (LE) | `yaw_bam` | Yaw (heading) orientation angle in 16-bit BAM | `[Established]` |
| `+0x18`–`+0x1D` | 6 | `i16[3]` | `velocity_vector` | Initial linear velocity vector components $[v_x, v_y, v_z]$ | `[Supported Inference]` |
| `+0x1E` | 2 | `u16` (LE) | `speed` | Scalar speed magnitude in knots or internal simulation units | `[Established]` |
| `+0x20`–`+0x33` | 20 | `u8[20]` | `trajectory_state` | Kinematic waypoint spline parameters and target lock links | `[Bounded Observation]` |
| `+0x34` | 1 | `u8` | `override_flags` | Visibility and editing lock bitmask (see § 3.4) | `[Established]` |
| `+0x35`–`+0x3F` | 11 | `u8[11]` | `reserved_prop` | Alignment padding bytes | `[Bounded Observation]` |

### 3.2 Prop Behavior Flags (`behavior_flags`, `+0x02`)

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | - | V | E | - | C | A | W | - |
     +---+---+---+---+---+---+---+---+
           |   |       |   |   +-- Watch target by cameras
           |   |       |   +------ Autozoom camera tracking
           |   |       +---------- Collision detection enabled (0x08)
           |   +------------------ Explodable on projectile / terrain impact
           +---------------------- Visibility flag (legacy display enable)
```

### 3.3 Prop Placement Flags (`placement_flags`, `+0x03`)

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | Reserved (0)  | S | - | P |
     +---+---+---+---+---+---+---+---+
                       |       +-- Placed in world (1 = active entity, 0 = empty)
                       +---------- Cast real-time ground shadow (1 = shadow active)
```

### 3.4 Prop Override Flags (`override_flags`, `+0x34`)

```
Bit:   7   6   5   4   3   2   1   0
     +---+---+---+---+---+---+---+---+
     | Reserved (0)  | L | V | - | - |
     +---+---+---+---+---+---+---+---+
                       |   +------ Visibility hidden override (1 = hidden)
                       +---------- Position locked on set (1 = immovable)
```
### 3.5 File Layout: the Event Table at `0x54`

The event table comes first, immediately after the 84-byte header, and every event record is the same size:

$$\text{size} = \texttt{0x54} + 67 \times \text{events} + 64 \times \text{props}$$

| Range | Contents |
|---|---|
| `0x00`–`0x53` | The 84-byte header (§ 2.1) |
| `0x54 + 67k` | Event record `k`, 67 bytes, for `k = 0 .. events - 1` |
| `0x54 + 67 \times events` | Prop records, 64 bytes each, every prop stored |

For `BOMBING.SET` the event table is `0x54`–`0x96` and the props begin at `0x97`, which is exactly the offset the 2004 notes found by deleting a prop. `[Supported Inference]`

**Verification.** Every set with a printed dump reproduces its own size from its printed counts: BOMBING 8/1 → 663, BOMBING2 7/1 → 599, DRIVING 15/8 → 1580, FIND&HIT 4/2 → 474, FIND&HT2 4/2 → 474, REALISM 39/10 → 3250. It also closes on all 35 loose corpus sets, and `0x54 + 67 \times events` lands on the prop table for each.

**How this was established.** `TYPESET.EXE` prints a set, so flipping one byte and re-printing maps a byte to the field it feeds ([§ 6 of the STUNT.EXE note](../../stunt-exe/sets.md)). Every offset of `BOMBING.SET` was flipped and re-printed.

**Event record fields**, offsets from the record start. Each row is a flip that changes exactly one printed value:

| Offset | Flip changes | Field |
|---|---|---|
| `+0x00` | the whole `Event#1` block disappears, or its IF clause changes form | IF condition type (§ 3.6) |
| `+0x01` | `If Any Weapon` → `If Any Object` | IF object 1, a 0-based prop index; `0xFE` = Any Weapon, `0xFF` = Any Object |
| `+0x02` | `hits …(12)` → `(11)` | IF object 2, or the time/count operand when the condition takes one |
| `+0x05` | `And nothing` → `And it's before 0 seconds` | first AND qualifier type |
| `+0x0B` | `Then explode` → `Then fade to` | THEN slot 1 type |
| `+0x0C` | `explode …(11)` → `(12)` | THEN slot 1 target, 0-based |
| `+0x12` | `And play` → `And cut to` | THEN slot 2 type |
| `+0x18` | appends `, tape only` | sound routing flags |
| `+0x19, +0x20, +0x27, +0x2E, +0x35, +0x3C` | each turns one `And do nothing` into `And award $0` | THEN slots 3 to 8 types |

**Clause header** (the 11 bytes before the slots):

| Offset | Field |
|---|---|
| `+0x00` | IF condition type (§ 3.6) |
| `+0x01` | IF object 1, 0-based; `0xFE` = Any Weapon, `0xFF` = Any Object |
| `+0x02` | IF object 2, or the operand a time/count condition takes |
| `+0x03`–`+0x04` | Operand word for the IF condition, unused by a collision rule |
| `+0x05` | AND #1 type (§ 3.6) |
| `+0x06`–`+0x07` | AND #1 operand |
| `+0x08` | AND #2 type |
| `+0x09`–`+0x0A` | AND #2 operand |

**THEN slot** (7 bytes; the operand columns were read by writing a value into each byte under a known action type):

| Offset | Field |
|---|---|
| `+0x00` | Action type (§ 3.6) |
| `+0x01` | Target object, 0-based |
| `+0x02` | Secondary operand: the flag number for `set flag` / `modify flag` |
| `+0x03`–`+0x04` | `u16` operand: dollars for `award $`, and the flag value's low byte |
| `+0x05` | Sound volume, 1 to 4 |
| `+0x06` | Sound routing: `1` tape only, `2` pilot only |

The `wait` operand at `+0x03`–`+0x04` is in 50 Hz ticks, not seconds: 256 reads back as `5.12 seconds`, which is 256/50, and 5 reads back as `0.1 seconds`. So the authored timebase in the file is the same 50 Hz clock as `[I4]`.

So the layout is an IF clause, two AND qualifiers, then a run of 7-byte THEN slots: slot 1 begins at `+0x0B`, and slot `k` begins at `+0x0B + 7(k-1)`. The arithmetic closes exactly: an 11-byte clause header plus eight 7-byte slots is 67 bytes, the record size, and the last slot ends where the prop table starts. The second AND qualifier's type is at `+0x08` by that spacing, but flipping it printed no change, so it is inferred rather than observed.

Reading the record as a 55-byte base plus 67 per further event, or as 12-byte blocks, or as a table after the props, is withdrawn: the prop-count arithmetic fits those splits equally, and only the flips distinguish them.

### 3.6 Event Operators

`TYPESET.EXE` is the tool that prints a set (`SETINFO.BAT` runs `TYPESET %1.SET > %1.TXT`), so these are the operator names the retail build itself emits. It renders each rule through printf templates, which makes each operand's width part of the evidence: `\\1O` is an object index, `\\1b` a byte, `\\1w` a word, `\\3t` a time, `\\1m` miles per hour. `[Established]` as vocabulary; the numeric encoding of each operator is still unknown.

**IF** — `\\1O hits \\2O`, `\\1O crashes`, `\\1p seconds have elapsed`, `weapon count = \\1w`, `never`.

**AND** — `it's before \\1p seconds`, `it's after \\1p seconds`, `event #\\1w has happened`, `event #\\1w hasnt happened`, `flag #\\1b = \\2b`, `flag #\\1b <> \\2b`, `plane's speed < \\1m mph`, `plane's speed > \\1m mph`.

**THEN** — `do nothing`, `award $\\3w`, `play \\s`, `cut to \\1o`, `set time to \\3t`, `finish - \\r`, `change \\1o's \\2v to \\x`, `wait \\3p seconds`, `start recording`, `stop recording`, `stop \\1o`, `kill \\1o`, `explode \\1o`, `fade to \\3w%`, `set flag #\\2b to \\3b`, `modify flag #\\2b by \\3b`, `stop recording if autoediting`.

**The `change` property set (`\\2v`)** — shape, WE position, altitude, SN position, roll, pitch, yaw, roll anim, pitch anim, yaw anim, heading pitch, heading yaw, heading pitch anim, heading yaw anim, speed, acceleration, zoom, watch obj, method, method obj, visibility, collideability, auto zoom, distance.

The four `EVT_*` codes this section previously listed are withdrawn: no source in the corpus reproduces them, and the templates above are the vocabulary the binary actually uses.

### Encoding

The numeric values were read off `BOMBING.SET` by writing each value into one type byte and re-printing (§ 3.5). `[Supported Inference]` for each table, since every entry was observed rather than inferred.

**IF condition type** (`+0x00`): `0` —, `1` hits, `2` crashes, `3` seconds elapsed, `4` weapon count, `5` nothing, `6` it's before, `7` it's after.

**AND qualifier type** (`+0x05` and `+0x08`): `0` nothing, `1` it's before, `2` it's after, `3` event happened, `4` event hasn't happened, `5` flag =, `6` flag <>, `7` speed <, `8` speed >. Values above `8` fall through into the action table below, which is how the two tables sit next to each other in the image.

**THEN action type** (`+0x0B`, `+0x12`, and the first byte of each later 7-byte slot): `0` do nothing, `1` award $, `2` play sound, `3` cut to, `4` set time, `5` finish, `6` change, `7` wait, `8` start recording, `9` stop recording, `10` stop, `11` kill, `12` explode, `13` fade, `14` set flag, `15` modify flag, `16` stop recording if autoediting. Values `17` and above print the `change` property names (shape, WE position, altitude, …), again an out-of-range read into the adjacent table rather than a valid action.

The handbook enumerates the authoring actions this table encodes: `CutTo`, `Change` (with roughly twenty sub-parameters — shape, position, altitude, roll/pitch/yaw, speed, acceleration, zoom, watch target, visibility, collideability, autozoom), `Explode`, `Kill`, `Fade`, `Finish`, `Set Flag`, `Set Time`, `Start Rec`, `Stop Rec`, `Start Sound`, `Wait` and `Award $` (*handbook* pp.92–95), behind the triggers `Collision`, `Crash`, `Time` (maximum 655 seconds), `Weapon Count` and the `Never` placeholder (pp.89–90). Only the four codes above have confirmed symbols, so name-to-code mapping is `[Hypothesis]`. A 12-byte record cannot carry the `Change` sub-parameters directly; either records chain or the payload points elsewhere.

### 3.7 Editor-to-World Coordinate Conversion (`[I1]`)

All positions within `.SET` are authored in Set Designer editor coordinates ranging from $0$ to $200{,}000$ integer units, with the island center located at $(100000, 0, 100000)$. StuntReel transforms these coordinates into the metric right-handed basis ($+X$ Right/East, $+Y$ Up/Altitude, $+Z$ Backward/South, $-Z$ Forward/North) via:

$$X_{\text{world}} = \frac{X_{\text{editor}} - 100000}{10.0} \quad (\text{meters})$$

$$Y_{\text{world}} = \frac{Y_{\text{editor}}}{10.0} \quad (\text{meters})$$

$$Z_{\text{world}} = \frac{Z_{\text{editor}} - 100000}{10.0} \quad (\text{meters})$$

- **Fixed-Point Conversion:** In `.SET` binary storage, coordinates are stored as 32-bit $16.16$ signed fixed-point integers. To obtain floating-point meters:
  $$\text{pos}_{\text{meters}} = \frac{\text{raw\_i32}}{65536.0}$$
- **Scale Factor:** Exactly 10 Set Designer editor units equal 1.0 meter in world coordinates. An island width of 200,000 units spans 20,000 meters (20 kilometers).

---

## 4. Open Questions & Reverse Engineering Backlog

| Item ID | Topic | Description | Evidentiary Tier |
| :--- | :--- | :--- | :--- |
| `[BK-SET-01]` | Vehicle Tuning Bytes `0x36`–`0x3D` | Precise aerodynamic scalar mappings governing flight control sensitivity and elevator response in Set Designer. | `[Unknown]` |
| `[BK-SET-02]` | Trajectory Waypoint Spline Record | Bit-level packing of the 20-byte `trajectory_state` field (`+0x20`–`+0x33`) governing multi-point AI flight paths. | `[Bounded Observation]` |
| `[BK-SET-03]` | Extended Event Opcode Catalog | Verification of additional action codes ($0x0005..0x0010$) for mid-air refueling, formation flying, and radio chatter. | `[Hypothesis]` |
| `[BK-SET-04]` | Header Size Variants (`0x60` vs `0x160`) | Disambiguation of extended 352-byte headers observed in mission `.SET` files with full narrative briefing text. | `[Supported Inference]` |
| `[BK-SET-05]` | Event Action-Code Catalogue | Map the handbook's THEN actions (*handbook* pp.92–95) onto `action_code` values. Progress: `0x53` is the event count, so a set's rules are now enumerable from its header. Open: the event table's location and its 12-byte stride are both uncorroborated (§ 3.5). | `[Hypothesis]` |

---

## 5. Attribution & Provenance

The technical specifications for the `.SET` format are synthesized from the following primary community research and reverse engineering artifacts:

- **Neil Halelamien (2004):** Reverse engineering of `.SET` file structures, binary diff analysis of Set Designer output files (`100000.SET`, `NOPROP1.SET`), bitmask decoding of vehicle and prop state flags, and the 2004 SIFA email thread (`corpus/siarchive/Developer/Notes_SETFile/Stunt_Island_SET_fileformat_notes.txt`, `corpus/siarchive/Developer/Notes_SETFile/SET_File_Email_Thread.txt`).
- **Dave Palmowski (1999–2004):** Analysis of prop list insertion for custom shockwave generators and prop catalog indices (`corpus/siarchive/Developer/Notes_SETFile/SET_File_Email_Thread.txt`).
- **Dean Newbury (2004):** SIFA correspondence and prop slot constraint analysis.
- **Doug Armknecht (2000–2002):** World coordinate space and island center offset documentation in film trajectory analyses (`corpus/siarchive/Developer/SI_FLM_Format/FLM_NOTES.md`).
- **The Assembly Line / Disney (1992):** The retail handbook (`corpus/siarchive/Docs/Manual/`), read as a primary source for authoring semantics; see [`research/handbook.md`](../../handbook.md).
- **Disney tutorial sets (1993):** The 92 `.SET` files and 22 printed field dumps under `corpus/siarchive/Misc/Sets/`, emitted by the authoring tools (`Printed at :Thu Jan 21 15:56:19 1993`), which decode every header and prop field in prose.
- **StuntReel Teamwork Team (2026):** Resolution of the 80-byte stride historical error to exact 64-byte (`0x40`) stride, validation of 16.16 fixed-point math, and contract alignment.

---
