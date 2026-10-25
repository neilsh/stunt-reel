# The Stunt Island Handbook: A Source Card

**Subject:** the retail documentation as a *source*, not as a subject of its own. Findings drawn from it live in the note for their subject ([routing rule](README.md#routing-rule)); this card records what the document is, how far it can be trusted, and where each of its findings went.

## 1. The files

| File | What it is |
|---|---|
| `corpus/si_archive/Docs/Manual/stuntisle.pdf` | The retail handbook, 5.1 MB, scanned page images. Gitignored with the rest of `corpus/`. |
| `corpus/si_archive/Docs/Manual/SIManual.txt` | OCR text of that scan, 13,333 lines. The Table of Contents sits at lines 62–387; an alphabetical index ends the file. Chapter headings repeat as page footers. |
| `corpus/si_archive/Docs/Disney_Support/SIUPDATE.TXT` | The revised handbook, 5,961 lines: same chapters plus eight tutorials and a support FAQ. |
| `corpus/si_archive/Docs/Disney_Support/SIUPDATE2.txt` | The later revised edition, 7,033 lines. |
| `corpus/SIPatch.zip` | The Product Update (called Patch #3 in the support text): Cessna/Beechcraft elevator, Easy/Hard flight model, rudder pedals. `SINEW.TXT` is its changelog. |

## 2. How to cite it

`handbook p.N` for a printed page. When a number matters, add the OCR line: `handbook p.136, SIManual.txt:9389`. Page anchors come from the contents list and in-text cross-references ("see page 81"); a page inferred between two anchors is marked `est.`.

## 3. How far it can be trusted

The handbook documents the **authoring** front end (`STUNT.EXE`), which [`docs/SPEC.md` § 2.1](../docs/SPEC.md#21-explicit-scope-boundaries--non-goals) excludes. Nothing in it describes a byte layout.

**Reliable for structure.** Which options exist, what they are called, and what a numbered slot means: "Prop slots 1 through 8 are slots that record film" (p.62); "8 possible camera shots: one from the stunt aircraft (prop slot 1), one from the spotter plane (prop slot 2), and six from other positions" (p.78); the IF/AND/THEN operator names (pp.88–95); Global-Rec Off/Auto/On (p.97).

**Not reliable for numbers.** The text is OCR of a scan and corrupts digits and letters — `15,4Sifeet`, `Jill I feet`, `Flaps: les` (Yes), `Global-Ret` (Global-Rec). Two specific traps:

- **No frame rate or tick rate appears anywhere.** Deck counters print as hundredths of a second (`00:00.00`) and are called "seconds". Nothing reconciles that with the 50 Hz clock of `[I4]`, so the handbook cannot corroborate it; that rests on the PIT divisor alone.
- **Its units are nominal.** The island grid is called "feet" (p.62, 0 to 200,000, centred at 100,000), while [`formats/auxiliary/set.md`](formats/auxiliary/set.md) converts at 10 editor units to 1 m. The two readings differ by 3.048×, and parity at `SSIM ≈ 0.78` rules out a 3× world-scale error, so the handbook's "foot" is the fiction's unit rather than a measurement.

**Missing entirely:** any byte layout, header, chunk table or version field; screen resolution (only "VGA 256-color", p.11 — the Product Update does state `320x200x256`); a unit for altitude; ranges for roll, pitch, yaw or offset distance; and the word "trailer".

## 4. Evidentiary status

A handbook-only claim is `[Hypothesis]` with an inline `handbook p.N`, promoted only when bytes or a corpus file corroborate it ([`docs/SPEC.md` § 2.4](../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system)). It is never `[Established]`: that tier needs disassembled code or a runtime trap. The 8-recording-slot reading in [`formats/flm.md`](formats/flm.md) `Q-FLM-10` is the worked example — bytes give `0x90`–`0x97` as `view_obj = c & 0x0F`, the handbook names what slots 1 and 2 are, and the two together are `[Supported Inference]`.

## 5. Where its findings went

| Finding (`handbook` page) | Home |
|---|---|
| 8 recording slots, 1 = stunt aircraft, 2 = spotter (62, 78) | [`formats/flm.md`](formats/flm.md) `Q-FLM-10` |
| `recording_mode` is Off/Auto/On, and events override it (97) | [`formats/auxiliary/set.md`](formats/auxiliary/set.md) § 2.1 |
| IF/AND/THEN operator vocabulary (88–95) | [`formats/auxiliary/set.md`](formats/auxiliary/set.md) § 3.6, `[BK-SET-05]` |
| Authored limits: 40 prop slots, 64 events, 655 s (62, 87, 90) | [`GLOSSARY.md`](../GLOSSARY.md); `set.md` § 2.1 |
| Zoom 0.2 to 7.99, default 1.0 (80) | [`formats/concepts/coordinates-and-units.md`](formats/concepts/coordinates-and-units.md) § 3.5 |
| Set, Take, Event, Flag, Prop slot, Recording slot, Camera angle, Sound slot, Authored limit | [`GLOSSARY.md`](../GLOSSARY.md) |

**Deliberately not integrated.** Aircraft specification tables, career economy, Hall of Fame and contest scoring, installation layout, `ADDSNDS` internals and joystick calibration are `STUNT.EXE` domain and stay out under § 2.1. The support FAQ's advice on detail levels is superseded by [`playone-exe/lod.md`](playone-exe/lod.md), which locates the same setting as the `GAME.VAR` detail word at `0x22A4`.

## Ruled out

- *Handbook as corroboration for `[I4]` or `[I3]`*: it states no frame rate, tick rate, resolution or palette data.
- *Handbook units as a measurement basis*: the "feet" grid contradicts the `.SET` scale by 3.048×, and parity keeps the metric reading.
- *`SPOOL.$$$` as a playback artifact*: the 64 KB flight-data buffer and its 1 MB cap belong to recording in `STUNT.EXE`, not to `PLAYONE.EXE` playback.

## Open questions

1. **Which build is analysed?** [`playone-exe/startup.md`](playone-exe/startup.md) pins no version, and `SI_UP2` (12/09/92) fixed a palette shift where ocean and lakes rendered red or pink on some video cards. Whether that patch touched `PLAYONE.EXE`'s palette path, and so whether any `[MEM-*]` offset is build-specific, is unestablished.
2. **Are flags the film's variable registers?** The handbook's flags are -128 to 127, a signed byte, while film variables are 16-bit. The "16 flags, 16 slots" reading in `Q-FLM-10` survives only as `[Hypothesis]`.
3. **Can the action codes be named?** The THEN list (pp.92–95) is the candidate catalogue for `action_code`, and the corpus offers 92 `.SET` files under `corpus/si_archive/Misc/Sets/`, 22 with a printed `.TXT`. Those prints are tutorial articles rather than one-to-one dumps and disagree with their binaries on at least two header fields, so they are a lead and not an oracle. See `[BK-SET-05]` in [`formats/auxiliary/set.md`](formats/auxiliary/set.md).
