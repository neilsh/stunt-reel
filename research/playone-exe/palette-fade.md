# `PLAYONE.EXE`: Film Brightness and the End-of-Film Fade

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), statically unpacked
* **Method**: The packed file was decompressed with a local LZEXE 0.91 unpacker into a 200,524-byte load image (no MZ header). Disassembly is Capstone 16-bit. Corpus cross-check: `CTRY.FLM` `var_set` stream against the fade levels measured from the parity captures (`build/parity/reference/ctry`).
* **Scope**: What drives the palette fade at the end of `CTRY.FLM` (Q-FLM-09 in [`../formats/flm.md`](../formats/flm.md)).
* **Anchor**: `# [MEM-FLM-VARS]`, `# [MEM-PALETTE]`

Offsets below are load-image offsets. Code is in image segment `0x0000`, which runs at `CS = 0x0824` in the captured session (`DS = 0x1575`, and `DGROUP` is image paragraph `0x0D51`, so the image loads at `0x1575 - 0x0D51 = 0x0824`). `DS:` offsets are `DGROUP`-relative. The unpacked image and the unpacker are local evidence and are not committed.

---

## 1. Finding

`[Established]` The fade is authored in the film. `CTRY.FLM` ramps film variable 14 from 32768 to 0 with `var_set` opcodes between ticks 993 and 1333. `PLAYONE` interpolates the variable every frame and uses its high byte as palette brightness. It is not a fixed end-of-film routine.

```mermaid
flowchart LR
    A["FLM var_set 14<br/>(0x8E, value u16)"] --> B["next buffer<br/>DS:0x474A+0xDE+2n"]
    B --> C["per-frame lerp 0x136F<br/>live = prev + (next-prev)*frac"]
    C --> D["live vars<br/>DS:0x474A+0x7E+2n"]
    D --> E["0x0EE6: DX=var13,<br/>CX=var14, AX=var15"]
    E --> F["0x0FD2 palette build<br/>entries 0..239"]
    F --> G["driver set_palette<br/>[DS:0x2252] = 0x7B70"]
    G --> H["VGA DAC 0x3C8/0x3C9"]
```

## 2. Film Variables

The film player keeps its state in a structure at `DS:0x474A`. Its sibling at `DS:0x4888` holds the film clock at `+0x0E` (`# [MEM-FLM-TICK]`). Both are initialised by the routine at `0x3723`, which also zeroes the 16 live variables at `+0x7E`.

| Field | Content |
|---|---|
| `+0x20`, `+0x22` | 16-bit masks: which variables a `before` record touched, one per playback direction |
| `+0x24` | Mask of variables interpolated in the current slice |
| `+0x7E + 2n` | Live value of variable `n` (`u16[16]`) |
| `+0x9E + 2n` | `before` value of variable `n` |
| `+0xBE + 2n`, `+0xDE + 2n` | Slice start and end values of variable `n` |

* **`var_set` (`0x80`–`0x8F`), handler `0x3D54`:** stores the operand at `+0xDE + 2n`, or at `+0xBE + 2n` when the direction flag `DS:0x2274` is negative.
* **`before` (`0xA0`–`0xAF`), handler `0x3D2A`:** stores the operand at `+0x9E + 2n` and sets bit `n` in `+0x20` or `+0x22`. Opcodes `0xB0`–`0xBF` hit `int3` in this build.
* **Interpolation, `0x136F`:** for every variable whose bit is set in `+0x24`, `live = start + ((end - start) * frac) >> 15`, with `frac` taken from `DS:0x22E0 >> 1`. Variables therefore move linearly between `var_set` keys rather than stepping.

## 3. Palette Build

`0x0EE6` loads the variables from the `0x474A` structure and calls `0x0FD2`:

| Register | Source | Use in `0x0FD2` |
|---|---|---|
| `DX` | var 13 (`+0x98`) | Night term: `|DX| - 0x2000`, clamped to `0..0x4000`; its high byte `N` (`0..64`) darkens the scene entries, moves the sky gradient toward its night colours, and from `N >= 0x20` switches entries 213–214 to their night colours (section 3.1) |
| `CH` | high byte of var 14 (`+0x9A`) | Brightness `BL = round(CH / 2)`, `0..64` |
| `AH` | high byte of var 15 (`+0x9C`) | Saturation `BH = round(AH / 2)`, `0..64` |

The routine caches the three inputs at `DS:0x227B..0x227D` and returns early when they are unchanged. Otherwise it rebuilds the working palette `DS:0x2768` from the base palette `DS:0x2468`. The per-entry transform at `0x10C4` works in 6-bit DAC units:

$$g = \left\lfloor \frac{\lfloor (3R + B) / 4 \rfloor + G}{2} \right\rfloor,\qquad c' = \left\lfloor \frac{\left(g + \lfloor (c - g)\,BH / 64 \rfloor\right) BL}{64} \right\rfloor$$

This applies to each channel `c` of entries 0–239, in two blocks. The first block (entries 0–214, or 0–208 when `N >= 0x20`) uses the darkened brightness `BL' = ((0x80 - (N + N/2)) * BL * 2) >> 8`; the second (to entry 239) uses `BL`. Both divisions by 64 are `imul; shl ax, 2; mov al, ah`, so they floor toward negative infinity. Entries 240–255, the cursor and button-bar colours loaded by `0x7DB2` from a 48-byte palette resource, are never touched. That is why they do not fade. The new palette reaches the DAC through the driver's `set_palette` vector, unless the screen-faded flag `DS:0x227A` is set.

At full values (`var14 = var15 = 32768`, so `CH = AH = 0x80` and `BL = BH = 64`) and `N = 0` the transform is the identity.

### 3.1 Night Term (Var 13)

Before the transform, `0x0FD2` rewrites parts of the base palette from constants in `DGROUP`, in 6-bit DAC units:

| Source | Content | Written to |
|---|---|---|
| `DS:0x09DE` | Six `(day, night)` byte pairs: zenith `R, G, B` = `(0, 0)`, `(40, 0)`, `(63, 0)`; horizon `R, G, B` = `(52, 26)`, `(52, 0)`, `(52, 26)` | Each channel becomes `day + floor((night - day) * N / 64)`, stored at `DS:0x09EA` |
| `DS:0x09EA` | Zenith and horizon colours for this `N` | Entries 224–238: step `k = 1..15` is `zenith + trunc((horizon - zenith) * k / 15)` (`idiv`) |
| `DS:0x09F0` | Day lights `(40, 38, 38)`, `(29, 26, 26)` | Entries 213–214 when `N < 0x20` |
| `DS:0x09F6` | Night lights `(63, 46, 0)`, `(56, 55, 55)` | Entries 213–214 when `N >= 0x20` |

The sky gradient is therefore never the static `pal.h` table: at `N = 0` entries 224–238 run from `(3, 40, 63)` to `(52, 52, 52)`. The `CTRY` captures, where var 13 is 45 (so `N = 0`), match this exactly at entries 224, 233 and 238 (`(12, 162, 255)`, `(138, 194, 227)`, `(210, 210, 210)` after the DAC's 6-to-8-bit expansion). The night path (`N > 0`) is decoded but not yet checked against a capture.

## 4. Driver Vector Table

The 17-entry vector table at `DS:0x10A4` is copied to `DS:0x2240` at `0x47E9`. Then `[DS:0x2240]` is jumped to. The palette slots are:

| Slot | Target | Routine |
|---|---|---|
| `DS:0x224E` | `0x7AE1` | Blocking fade-in: ramps `DS:0x14CC` up to `DS:0x2768` over `BX/2` steps, two retraces per step |
| `DS:0x2250` | `0x7B0D` | Blocking fade-out, the same in reverse |
| `DS:0x2252` | `0x7B70` | `set_palette`: index 0, then 384 bytes on each of two retraces (all 256 entries) |
| `DS:0x225E` | `0x7DB2` | Load palette resource into `DS:0x2768`, 8-bit to 6-bit (`shr 2`); a 48-byte resource lands at entries 240–255 |

The blocking fades are used only by the screen transitions at `0x4916` and `0x494A` (`BX = 0x20`, about 0.45 s). They are not the film fade.

## 5. Corpus Cross-Check

`CTRY.FLM` sets variables 0–3 to 8192, var 11 to 300, var 13 to 45, and vars 14 and 15 to 32768 at tick 0. Var 10 then climbs through the film, and var 11 drifts and drops to 128 at tick 834. Var 14 is ramped down in 34 `var_set` keys from tick 993 (32700) to tick 1333 (0).

Predicting each capture's brightness from var 14 (`BL / 64`) and comparing it with the measured fade level (divided by the no-fade level 1.011) gives a mean absolute error of 0.016 at the capture's `film_tick`, and 0.006 at `film_tick - 6`:

| `film_tick` | Measured | Predicted (`t`) | Predicted (`t - 6`) |
|---:|---:|---:|---:|
| 1052 | 0.814 | 0.797 | 0.812 |
| 1150 | 0.546 | 0.531 | 0.547 |
| 1205 | 0.373 | 0.375 | 0.375 |
| 1271 | 0.204 | 0.172 | 0.203 |
| 1326 | 0.034 | 0.016 | 0.031 |
| 1337 | 0.000 | 0.000 | 0.000 |

The lag is consistent with the palette being built from film state a few ticks before the capture trap reads the clock (`# [MEM-FLM-TICK]` notes the film clock running 5 ticks ahead of the global tick). The lag is `[Bounded Observation]`.

The variables are common across the corpus. Of 561 films that decode, 407 lower var 14 below 32768 at some point (fade-ins as well as fade-outs), 108 lower var 15, and 224 drive var 13 past `0x2000`. No film sets var 14 or 15 above 32768. Three films never set var 14 (`EXIT.FLM` and `EXIT2.FLM` in `MultiFLM/Collage4`, `CPU_CRED.FLM`).

## 6. Open Points

* The meaning of variables 0–3, 10 and 11 is not established. Var 10's steady climb suggests a time or progress value (`[Hypothesis]`).
* `PLAYONE` zeroes all live variables at `0x3723`, so a film that never sets var 14 would play black. The renderer starts vars 14 and 15 at 32768 instead, keeping those three films visible; what `PLAYONE` shows for them is unchecked.
* The 6-tick lag (section 5) is not modelled: the renderer applies the variables at the authored tick.
* The renderer applies vars 13–15 through `PaletteControls::film_palette` in `stunt-core` ([`contracts/palette.rs`](../../crates/stunt-core/src/contracts/palette.rs)). It clamps brightness and saturation above 32768 to full, which no corpus film reaches.
