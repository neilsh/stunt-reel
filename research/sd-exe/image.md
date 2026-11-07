# SD.EXE: Image Layout and Routines

**Scope:** `SITools/SD.EXE`, the developers' scenery designer: how to read its image, and where its routines and strings sit. What its files mean stays in the format notes: [`map.md`](../formats/auxiliary/map.md) for `MAP.BIN`, `REGIONS.BIN` and the tree build, [`anchorpt.md`](../formats/auxiliary/anchorpt.md) for `ANCHORPT.DAT`, and [`scenery.md`](../formats/auxiliary/scenery.md) for the tree.

## 1. The file

`corpus/siarchive/SITools/SD.EXE`, 210,846 bytes, MD5 `4de4edd7aaf223e9ecfeb42d06c5389b`. It is a plain MZ executable, not packed (`[Established]`, header read 2026-11-06):

| Header field | Value |
|---|---|
| Header size | `0x60` paragraphs, so **load-image offset = file offset − `0x600`** |
| Entry `CS:IP` | `0000:077E` |
| `SS:SP` | `423E:FEB2` |
| Relocations | 247 |
| Load image | `0x3319E` bytes |

Every offset in the notes that cite `SD.EXE` is a load-image offset unless it says "file offset".

## 2. Segments

The relocated words name eight segment values (`[Established]`, counted from the relocation table). The roles are `[Supported Inference]` from what each holds.

| Segment | Relocations | Role |
|---|---|---|
| `0x0000` | 41 | Code, including the entry |
| `0x0F7F` | 102 | Code |
| `0x14FE` | 5 | Data: starts at the object table (load image `0x14FE0`, section 3). Loaded into `DS` twice |
| `0x163D` | 37 | **DGROUP**: the file names and assembler templates below. Loaded into `DS` six times |
| `0x259A` | 54 | Data; loaded into `DS` eight times |
| `0x3319` | 6 | Its first 14 bytes end the load image (`0x33190`–`0x3319D`); the rest is allocated at run time |
| `0x3AEA` | 1 | Past the load image: allocated at run time |
| `0x423E` | 1 | Stack (`SS`) |

A `DS` offset in DGROUP is the load-image offset − `0x163D0`; `anchorpt.dat` is at `DS:0x20BA`.

## 3. Strings

`[Established]`, file offsets:

| Offset | String | Used by |
|---|---|---|
| `0x16AAD`–`0x16ACD` | `pfont.bin`, `palette.lbm`, `night.lbm`, `res\*.res` | The editor's own display and resources |
| `0x155E0`… | 255 slots `shapes\--------.bin` | The object table, segment `0x14FE`: compiled shapes it places |
| `0x18181`, `0x18ACA`, `0x18AD7` | `Object dir:`, `Object Name:`, `Object height (ft):` | Object placement prompts |
| `0x18A8A` | `anchorpt.dat` | Anchor load and save |
| `0x18A97`, `0x18AAC` | `\stunt\landscape.asm`, `\stunt\anchor.asm` | The assembler output |
| `0x18BB1`–`0x18C10` | `strucs.asm`, `anchorpts,noanchpts`, `($-anchorpts)/aptlen` | The anchor table's assembler template |
| `0x18C94`, `0x18C9C` | `map.bin`, `Anchor point height (ft) :` | Terrain patches |
| `0x1A170`–`0x1A1A6` | `scenery.bin`, `squished.bin`, `Can't create scenery.bin`, `regions.bin` | The block tree and the unread outputs |

## 4. Routines

`[Established]`, load-image offsets. The evidence for each is in the note named.

| Offset | Routine | Note |
|---|---|---|
| `0x8F67` | Read `ANCHORPT.DAT`: `0x1C × 0x400` bytes into the anchor buffer at offset 4 | [`anchorpt.md`](../formats/auxiliary/anchorpt.md) section 1 |
| `0x8FA0` | Write `ANCHORPT.DAT` back from the same buffer | same |
| `0xB0F8` | Clear the in-use byte of all 1,000 patch records | [`map.md`](../formats/auxiliary/map.md) section 2.2 |
| `0xB10D`, `0xB17D` | Convert links and vertices to memory form on load, and back on save | same |
| `0xB1EF`, `0xB221` | Load and save `MAP.BIN` (list head `DS:0x22C2`) | same |
| `0xB78C`, `0xB7D2`, `0xB7F6` | Append, prepend and unlink a patch | [`map.md`](../formats/auxiliary/map.md) section 3.1 |
| `0xD21A` | Emit one tree node per patch, recursing through `next` and `first_child` | [`map.md`](../formats/auxiliary/map.md) section 3.2 |
| `0xD2D9`, `0xD399` | Collect a leaf's top-level patches, and compile them | same |
| `0xD43B` | Walk the `REGIONS.BIN` block tree | same |
| `0xE9B6`–`0xED28` | Write `SCENERY.BIN` and `SQUISHED.BIN`; unread | [`map.md`](../formats/auxiliary/map.md) section 4.2 |

To find the code behind another string, turn its file offset into a load-image offset (− `0x600`), take the segment from section 2 whose base (segment × 16) is the highest at or below it, subtract that base, and search the code segments for the result as a 16-bit immediate or displacement. The object table is in `0x14FE`; every other string above is in DGROUP.

## Ruled out

- **`SD.EXE` as the `.SIO` to `.SOD` compiler** (2026-11-06): the image names no `.sio` or `.sod` file and only reads compiled shapes from `shapes\*.bin`. `SLICE.exe` opens `.SIO` files itself. What compiles them is open ([`sio.md`](../formats/auxiliary/sio.md)).

## Open questions

1. **What `SCENERY.BIN` and `SQUISHED.BIN` encode**: [`map.md`](../formats/auxiliary/map.md) section 4.2.
2. **Whether `SD.EXE` run on the corpus files rebuilds the shipped tree**: [`map.md`](../formats/auxiliary/map.md) section 4.2.
3. **The roles of segments `0x0F7F` and `0x259A`.** Section 2 has only counts.
