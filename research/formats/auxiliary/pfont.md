---
summary: "`PFONT.BIN`: 1,152-byte font of a 128-byte width table and 128 8x8 one-bit glyphs, and the `PLAYONE.EXE` credits rule (centring, ink 255, shadow) that reproduces the `INTRO.FLM` title cards."
---
# Specification: `PFONT.BIN` Proportional Bitmap Font

## 1. Overview & File Identification

`PFONT.BIN` is the bitmap font `PLAYONE.EXE` loads at startup (the name is the string at `DS:0x05CA`, [`memory-map.md`](../../playone-exe/memory-map.md)). It draws the film's credits text, the two lines that `.FLM` opcode `0x99` sets and `0x98` clears ([`flm.md`](../flm.md)), and, by its name and the `0x05CA` reference, the UI's dialog text.

- **File name:** `PFONT.BIN`, at the engine root beside `PLAYONE.EXE` and the `VAULT` directory.
- **Magic bytes:** none. The file is exactly 1,152 bytes.
- **Byte order:** single bytes only.
- **Where it ships:** every `PLAYONE` tree in the corpus holds one: the demo `stisldem/`, the full game, `builds/patch3` and `builds/unpatched`, and each film folder under `siarchive/Films/` ([`patch3.md`](../../playone-exe/patch3.md): Patch #3 leaves it unchanged).

**Governing invariants:** [`[I3]`](../../../docs/SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading) (the glyphs carry no colour; the caller picks palette indices) and [`[I7]`](../../../docs/SPEC.md#i7-asset-isolation--small-pure-rust-core-dependencies) (the file is game data, read from the corpus at run time, never committed). **Code:** [`font.rs`](../../../crates/stunt-core/src/font.rs) parses it, [`credits.rs`](../../../crates/stunt-core/src/credits.rs) lays out the credits; the synthetic fixture is `synthetic_pfont.bin` ([`tests/fixtures/README.md`](../../../tests/fixtures/README.md)).

---

## 2. Header & Memory Layout

The byte layout is [`pfont.bin.ksy`](pfont.bin.ksy): a 128-byte width table, then 128 glyphs of 8 one-byte rows, both indexed by character code. `[Established]`: the file is 1,152 bytes in every copy, and drawing a string by this layout reproduces the captured `INTRO.FLM` title cards pixel for pixel (section 3.2).

`PLAYONE` reads the width table at `DS:0x4F02` (`0x58D0` indexes `[bx + 0x4F02]` by character code), so the file is loaded whole into `DGROUP`; where the glyph rows land is `[Unknown]`.

---

## 3. Data Structures & Opcode Table

### 3.1 Glyphs and Advance

Each glyph row is one byte, bit 7 the leftmost pixel, so a glyph is at most 8 pixels wide and 8 tall. The width byte is the character's whole advance, inter-character spacing included: `0x58D0` measures a string as the plain sum of its widths, and the next glyph starts that many pixels to the right. The capital letters are 7 rows tall with row 7 blank, and `I` is 2 wide (1 pixel and 1 space) while `Y` is 8 (`[Established]`, static and capture).

`0x58E8` is a second measuring routine that adds 1 per character; which text uses it is `[Unknown]`.

### 3.2 Drawing the Credits

`[Established]`, static at the image offsets below and pixel-exact on the capture. The per-frame routine draws the credits after the 3D scene (`0x0F7B`, [`sod-vm.md` § 9](../../playone-exe/sod-vm.md#9-per-frame-routine-and-scene-composition)):

| Step | Rule | Offset |
|---|---|---|
| Skip | No credits when the first byte of the text at `state + 0xFE` is negative | `0x0F7F` |
| Line 1 x | `left + ((right - left - width) >> 1)`, an arithmetic shift | `0x0F84` |
| Line 1 y | `top + ((bottom - top - 28) >> 1)` | `0x0F97` |
| Line 2 | Same centring, 20 rows below line 1; skipped when the line is empty | `0x0FB0` |
| Colour | Ink index 255 (`CX = 0xFF`) | `0x0FA9` |
| Shadow | `0x58BD` draws the string at `x + 1` in colour 0, then at `x` in the given colour | `0x58BD` |

`left`, `right`, `top` and `bottom` are the inclusive clip rectangle at `DS:0x2294`, `0x2296`, `0x2298` and `0x229A`. With the 320 x 185 film view (`0..319`, `0..184`), `DISNEY INTRO REEL` (width 92) lands at x 113, row 78, and its countdown number at row 98. Two checks against the capture: every frame of `vault-intro/frames/006` that shows text (71 frames before tick 1520, the countdown from 15 to 1) matches the rule exactly, ink and shadow; and the renderer, drawing by it, scores SSIM 1.000 on all 69 frames before tick 760 of the reference `vault-intro/frames/004`, so each countdown step changes on the captured tick.

---

## 4. Open Questions & Analysis Backlog

1. **Odd widths.** Every string on the captured title cards has an even width, so the capture cannot tell `right = 319` from `318`; the inclusive 184 bottom row (the film view's 185 rows) suggests 319. `[Hypothesis]`.
2. **Codes past 127.** `0x58D0` indexes the width table by the full byte, so a code at or above `0x80` would read past it. No film text has one; the parser gives such codes no width and no glyph. `[Unknown]`.
3. **Where the glyph rows are loaded** and which routine draws UI dialog text with them. `[Unknown]`.
4. **Clipping.** Whether the text driver `[0x225A]` clips to the clip rectangle is `[Unknown]`; the renderer clips only to the page, which no film text reaches past.
5. **Credits ink and the cursor share index 255.** Parity's UI overlay mask keeps index 255 on ticks where the film shows credits, as the render record says, and masks it as the cursor elsewhere ([`method.md`](../../parity/method.md) § 2).
6. **Renderer gaps, not findings.** The renderer draws credits on offscreen pages only, not in the interactive window, and a render without `--viewport-rows` centres them in the whole page (line 1 at row 85, not 78).

---

## 5. Attribution & Provenance

Layout and drawing rule read from `PLAYONE.EXE` (`corpus/stuntisl/PLAYONE.EXE`, unpacked with [`unlzexe.py`](../../../python/scripts/unlzexe.py)) and checked against the `vault-intro` capture by Neil Halelamien, 2026-11-01 ([#75](https://github.com/neilsh/stunt-reel/issues/75)). The 1,152-byte length was confirmed on every copy in the corpus, among them `corpus/stisldem/PFONT.BIN` and `corpus/siarchive/Films/NewPLAY/PFONT.BIN`.
