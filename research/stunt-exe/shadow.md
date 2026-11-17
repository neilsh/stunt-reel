---
summary: "`STUNT.EXE`'s film shadow draw is `PLAYONE`'s code at a fixed offset, and its writers of the slot shadow flag (the prop editor's SHD toggle, the prop-to-slot build, a fixed setup, the film-stream create) compare no height."
sidebar_label: "Actor shadow draw & flag"
---

# STUNT.EXE: The Actor Shadow Draw and the Shadow Flag

**Scope:** whether the authoring executable hides a high actor's shadow by height, the handbook's "close enough to the ground" (`SIManual.txt:5039-5066`). Read from the unpacked OldPLAY image (`stunt.img`, 248,460 bytes, [`sets.md` § 1](sets.md#1-which-builds-the-corpus-holds)); nothing run. `PLAYONE`'s side is [`sod-vm-frame.md` § 9.1](../playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw).

## 1. The same draw code as `PLAYONE`

`[Established]`, by byte comparison and disassembly. `STUNT.EXE` holds `PLAYONE`'s scene walk and shadow path at `PLAYONE` image offset `+ 0x55C7`, the same instructions and relative call displacements; the queues' view-eye operand is `DS:0x99B6` where `PLAYONE` has `0x2A68`, so the actor queue and the shadow queue's tail differ in those bytes:

| `PLAYONE` | `STUNT.EXE` | Role |
|---|---|---|
| `0x19FC` | `0x6FC3` | Shadow queue: plane solve on slot `+0x1E`, box height `+0x20/+0x22` |
| `0x1A90` | `0x7057` | Actor queue |
| `0x1B0C` | `0x70D3` | Cull: view depth, frustum, distance exponent |
| `0x1C41` | `0x7208` | The shadow matrix's Y-row rewrite from the plane |
| `0x1E2F` | `0x73F6` | The walk's `SIF_SHADOW` test before the shadow queue |

`0x6FC3` has one caller, `0x73FC` in that walk. The actor queue `0x7057` has a second, `0xE4EC`, with no shadow call. The plane pointer is stored at `0x7C85` (`mov [si+1Eh],ax`) after a polygon crossing count, as `PLAYONE`'s probe does at `0x26BE`; the rest of `PLAYONE`'s probe `0x240A` is not byte-identical here and was not compared. So a shadow in a film `STUNT.EXE` plays back takes the same path, with no height compare, as in `PLAYONE`.

## 2. Who sets the shadow flag

`[Established]` for the writers listed; `[Supported Inference]` that there are no others, since they were found by byte pattern (`test`, `or`, `and`, `xor` and `mov` on `[reg + 1]`), which misses another addressing form. Slot byte `+1` bit 2 is `SIF_SHADOW` ([`flm.md`](../formats/flm.md#32-object-type-flags-type_flags-u8)).

| Offset | Write | Source of the value |
|---|---|---|
| `0xDB2B` | `xor byte [di+1], 4` | The prop editor's SHD toggle, one of a run with `0xDB1D` (`xor [di], 8`), `0xDB24` (`xor [di], 20h`) and `0xDB38` (`xor [di+50h], 80h`) |
| `0xCD96`, `0xCD98` | `or al, 4`, `mov [di+1], al` | Bit `0x40` of the record's byte `+0`, cleared there as it is copied |
| `0xBE88` | `or byte [di+1], 4` | A fixed setup that also stores flags `0x19` and shape `0x104` in another record (`0xBE93..0xBE98`) |
| `0x92C4` | `mov [di+1], al` | The film stream's create, `es lodsb` |

None of them compares a height. The stream censuses agree: drawn shapes keep `SIF_SHADOW` more than 100 m up in 262 of the 529 distinct corpus films (`[Bounded Observation]`, counted by the census script the source below names), and the flag's flips follow no one height ([`sod-vm-frame.md` § 9.1](../playone-exe/sod-vm-frame.md#91-the-actor-shadow-draw)).

_Source: [the shadow's cull, the display-list run and STUNT.EXE's shadow draw](../../work/2026-11/512_altitude-cutoff/journal.md#2026-11-16-the-shadows-cull-the-display-list-run-and-stuntexes-shadow-draw)._

## Ruled out

* **A height compare in `STUNT.EXE`'s shadow draw or shadow-flag writers** (sections 1 and 2) ([the #512 read](../../work/2026-11/512_altitude-cutoff/journal.md#2026-11-16-the-shadows-cull-the-display-list-run-and-stuntexes-shadow-draw)).

## Open questions

* **The flight view's shadow.** Only the film scene walk was followed; whether the live flight in `STUNT.EXE` draws through the same walk is not traced.
