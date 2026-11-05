# Patch #3: The Patched Build of `PLAYONE.EXE` and `MAKEONE.EXE`

Disney's "Sound Blaster Update" for Stunt Island (`corpus/patches`, Patch #3, archives dated 1993-09-06, wrapper 1994-03-18) replaces every executable the game ships. This note records what it changes, where the patched `PLAYONE.EXE` keeps what the capture harness reads, and which build each tested film needs. `mise run game-builds` ([`game_builds.py`](../../python/scripts/game_builds.py), [`stunt_reel/game_builds.py`](../../python/stunt_reel/game_builds.py)) builds both trees under `<data root>/builds/` and writes `builds/patch3-manifest.json`; `capture-ref`, `play` and `make-all` take `--game-root <data root>/builds/patch3` to run the patched programs.

---

## 1. What the Patch Changes

`[Established]`, from `PATSI.BAT` and the archives themselves. `p3-si.exe` is the wrapper (it holds `PATSI.BAT`, `P3-SI1.EXE`, `README.TXT` and `SINEW.TXT`); `PATSI.BAT` checks that `STUNT.EXE` and all five `P3-SI*.EXE` are present, deletes eleven files, runs each archive with `-d` (PKLITE self-extracting zips; Python's `zipfile` opens them), and finally runs `SETUP` (`install -s`) so the user picks the sound card again.

| Path | Action | Unpatched bytes | Patched bytes | Archive |
|---|---|---|---|---|
| `GAME.CFG` | deleted, then rewritten by `SETUP` | 7 | 7 | — |
| `INSTALL.CFG` | replaced | 631 | 653 | `p3-si5` |
| `INSTALL.EXE` | replaced | 46,347 | 48,379 | `p3-si5` |
| `MAKEONE.EXE` | replaced | 103,247 (`2963e088…`) | 98,000 (`426111d9…`) | `p3-si5` |
| `PLAYONE.EXE` | replaced | 102,703 (`3c93493c…`) | 97,790 (`fc532c94…`) | `p3-si5` |
| `STUNT.EXE` | replaced | 138,318 | 134,784 | `p3-si5` |
| `WSTUNT.EXE` | added (Windows 3.1 launcher) | — | 7,680 | `p3-si5` |
| `RES/MUSIC1.ESS` | replaced | 591,990 | 849,994 | `p3-si2` |
| `RES/MUSIC2.ESS` | replaced | 1,016,750 | 1,252,010 | `P3-SI1` |
| `RES/SPRITES.RES` | replaced | 968,055 | 958,653 | `p3-si3` |
| `RES/COMMNSND.SMP` | replaced | 309,686 | 310,668 | `p3-si4` |
| `RES/SNDFX2.SMP` | replaced | 946,478 | 975,651 | `p3-si4` |

Nothing else in the tree changes: `DRIVER1.BIN` to `DRIVER3.BIN`, `VDATA.BIN`, `PFONT.BIN`, the other `RES` files, `VAULT`, `SETS` and `PILOTS` are the shipped ones. The demo (`corpus/stisldem`) ships the unpatched `PLAYONE.EXE`, byte for byte the full game's.

The patch's own notes (`README.TXT`, `SINEW.TXT`) say what the new executables do: sound no longer breaks up with EMS present, 486 lock-ups are fixed, Tandy and CGA graphics and the Tandy DAC and PS/1 sound are dropped, MS-DOS 6.0 is supported, and in Stunt Island the Cessna and Beechcraft elevator was made easier, an Easy/Hard flight model was added (Alt-P, Easy removes inertia) and rudder pedals are supported. All four executables are LZEXE 0.91 packed, like the originals.

### 1.1 `GAME.CFG`

`[Bounded Observation]`, 2026-10-30, dosbox-automation 0.85.1. `PATSI.BAT` deletes `GAME.CFG` and `SETUP` writes it again; without it `PLAYONE.EXE` runs `install.exe` (the EXEC at image `0x0CBD`, [`memory-map.md` § 1](memory-map.md#1-dgroup-memory-reference-table)), which a capture stage does not hold. Both `INSTALL.EXE` builds were run with `install -s` on a copy of their tree without `GAME.CFG` and given one Enter on "Install with the above configuration" (defaults: Mouse, Sound Blaster, Roland MT-32). Both wrote the same 7 bytes, `01 01 20 02 07 00 00`, the layout of the shipped file (`01 01 20 02 07 00 01`, whose last byte picks AdLib/Sound Blaster music, as in `sb16/GAME.CFG`; `mt32/` has `00`, `SS/` has `05`). The setup menus list the same devices in both builds. So the patched tree keeps the shipped `GAME.CFG`, and the manifest lists it as `restored`.

---

## 2. Patched `PLAYONE.EXE` Offsets

`[Supported Inference]` for the moved rows, from a static match and one live capture. Both images were unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py):

| Attribute | Unpatched | Patched |
|---|---|---|
| Unpacked image | 200,524 bytes | 192,028 bytes |
| Entry `CS:IP` | `0000:0C5E` | `0000:0D70` |
| `DGROUP` (`mov ax, imm` at entry + `0x15`) | `0x0D51` | `0x0C71` |
| Runtime `DS` under dosbox-automation (load paragraph `0x01F5` + `DGROUP`) | `0x0F46` | `0x0E66` |
| Stored PSP (`mov [imm], es` at entry + `0x1A`) | `DS:0x22C4` | `DS:0x1C4A` |

The first `0xA4` bytes of the two entry routines are the same instructions; only operands differ. Data at `DS:0x2200` and above moved down by `0x67A` (`0x22C4`, `0x22CE`, `0x22D0`, `0x2263` to `0x2268`, `0x56A2`, `0x5786`), the strings near `0x0600` moved up by `0x7C` (`game.cfg` `0x05AC` → `0x0628`, `install.exe` `0x05BE` → `0x063A`), and one word moved by `0x67E` (`0x14CC` → `0x0E4E`), so the data segment was not shifted as a whole. For each instruction of the unpatched image that names `DS:0x4896`, `0x22B8`, `0x2768` or `0x22C4`, the bytes on each side (up to 12, address wildcarded) were searched in the patched image and kept when exactly one place matched. Every unique match gave the same shift, `-0x67A`: `0x4896` → `0x421C` (2 of 17 references matched uniquely), `0x22B8` → `0x1C3E` (2 of 4), `0x2768` → `0x20EE` (7 of 10), `0x22C4` → `0x1C4A` (1 of 3, and the entry routine itself). References that did not match uniquely sit beside other shifted addresses, so a byte match cannot see them; none matched elsewhere. The rows are in [`memory-map.md` § 1.1](memory-map.md#11-patch-3-build). § 4 pairs the instructions by function instead, maps every row, and agrees with each of these.

Live check: `CTRY.FLM` with its shipped `.ALL` on the patched tree, `mise run capture-ref -- --game-root <data root>/builds/patch3` (the harness picks the offsets by the executable's hash, [`playone.py`](../../python/stunt_reel/tac/playone.py) `layout_for`). The film clock at `0x0E66:0x421C` and the global tick at `0x0E66:0x1C3E` rose together from 27 (one kept frame per 11 ticks, film tick equal to global tick, as on the unpatched build), and at the three film ticks shared with the unpatched reference `captures/vault-ctry/frames/002` the working palette read at `0x20EE` was identical to the unpatched one at `0x2768`.

---

## 3. Which Build Each Film Needs

`[Bounded Observation]`, 2026-10-30/31, dosbox-automation 0.85.1, the committed harness (`core = dynamic`, 45,000 cycles for `PLAYONE`; `core = dynamic`, `max` for `MAKEONE`; the `capture` profile since `efb6009`), into scratch directories rather than the captures store. These are the four films the DOSBox-X survey left as capture stalls ([`../parity/batch.md`](../parity/batch.md)). Film lengths are the authored totals from `mise run flm-events`.

| Film | Ticks | Unpatched `PLAYONE` | Patched `PLAYONE` | Needs |
|---|---|---|---|---|
| `flmonly-count` (`FLMOnly/COUNT.FLM`) | 92 | 9 frames to tick 91 | 8 frames to tick 82, same countdown picture at each tick | either |
| `collage4-exit` (`MultiFLM/Collage4/EXIT.FLM`) | 565 | 51 frames to tick 555, shipped and generated `.ALL` alike | 51 frames to tick 557, both `.ALL` | either |
| `collage4-exit2` | 565 | 51 frames to tick 555 | 51 frames to tick 555 | either |
| `flmonly-bigman` (`FLMOnly/BIGMAN.FLM`) | 57,043 | traced; capture fails (dump pass 3 ticks off the trace) | crashes the emulator with the unpatched `.ALL` (2 of 2 runs, about 3 min in); plays with the patched `MAKEONE`'s `.ALL` (40 frames) | a matching `.ALL`; no build captures it |

* **None of the four needs the patched build to play.** The DOSBox-X stalls were the old debugger harness, not the films. `COUNT`'s clock "stopping at tick 92" is its end: the film is 92 ticks long.
* **The builds draw the same picture.** At the 50 film ticks shared by the two `EXIT2` captures every working palette is identical and 99.8% of page bytes match. The roughly 130 pixels that differ are the mouse pointer, which the patched build leaves over the first control-bar button and the unpatched one at the screen centre. On the same emulated frame the patched build's film clock is 0 to 2 ticks ahead (`COUNT`: tick 5 against 3 at frame 1276).
* **An archive is tied to its `MAKEONE` build when the film uses a replaced resource.** `BIGMAN.ALL` from the patched `MAKEONE` is 1,429,089 bytes (`45976640…`) against the unpatched 1,425,743 (`8581068d…`, equal to the stored DOSBox-X archive). The patched `PLAYONE` crashes dosbox-automation on the unpatched archive (the process exits with no shutdown log) and plays the patched one. The archive bundles the resources the film uses, and the patch replaced `SPRITES.RES` and two sound banks; that this is the cause is untested. `COUNT` (`785090c5…`, 3,312 bytes) and `EXIT`/`EXIT2` (`ea401728…`, 11,004 bytes; the two films get the same archive) come out byte-identical from both `MAKEONE` builds.
* **`BIGMAN` replays differently from boot to boot on both builds.** Two trace passes run side by side diverge by one tick from film tick 484 (unpatched) and 633 (patched), so a dump pass cannot land on the frames its trace picked. `CTRY.FLM` replays bit for bit ([`capture-dosbox-automation.md`](capture-dosbox-automation.md) § 2). The trace window also covers only about 8,300 (unpatched) or 8,550 (patched) of its 57,043 ticks. It stays in `KNOWN_CAPTURE_STALLS` ([`batch_stages.py`](../../python/stunt_reel/batch_stages.py)); the other three were removed.
* **The shipped `EXIT.ALL` and `EXIT2.ALL` are one file** (50,538 bytes, `7f557bc7…`), four and a half times what `MAKEONE` writes for either film; `PLAYONE` plays both films with it.
* **`MAKEONE` does not always return to DOS.** It wrote `COUNT.ALL` within a minute but neither build left graphics mode in 15 minutes. The patched build never returned on `EXIT` or `EXIT2` (4 runs, the archive complete and unchanged for 60 s); the unpatched one returned on `EXIT` (27 s) and on one of two `EXIT2` runs (29 s). Both returned on `BIGMAN` (476 s, 514 s). `make-all` waits for text mode, so before the hang policy it reported these as timeouts and discarded a good archive ([`../makeone-exe/driving.md`](../makeone-exe/driving.md) § 9).

* **Two retail films play only on the unpatched build with their shipped archive.** `[Bounded Observation]`, 2026-11-01. `siarchive/Films/NewPLAY/` ships the patched `PLAYONE.EXE`, which the batch survey runs for every film in that folder. With the folder's own `TOD.ALL` and `INTRO.ALL` it stalls (`TOD.FLM`'s clock falls to 0 near tick 200; `INTRO.FLM` holds its title card); the unpatched build plays both archives, and the patched build plays the demo's `INTRO.ALL` and a patched-`MAKEONE` `TOD.ALL` ([`capture-dosbox-automation.md` § 4.7](capture-dosbox-automation.md#47-the-instruction-budget-and-three-retail-archives)).

SI Central's advice that some older films play only on the unpatched `PLAYONE` and most newer ones need the patched build is not borne out by these four. Its likeliest mechanism is the one `BIGMAN` shows: a `.ALL` built by one `MAKEONE` played on the other `PLAYONE`.

---

### 3.1 Composed Pages

`[Bounded Observation]`, 2026-10-31. The patched build's composed-page words were taken as `0x1C50` and `0x1C52`, the unpatched `0x22CA`/`0x22CC` less `0x67A`. A `CTRY.FLM` capture on the patched tree (`mise run capture-ref -- --game-root <data root>/builds/patch3`) traced 1,906 frames and flagged 72 torn (3.8%), against 66 of 1,908 on the unpatched build; a torn flag needs bands that match only one buffer and others only the other, which words naming other memory could not produce. See [`capture-dosbox-automation.md` § 4.5](capture-dosbox-automation.md#45-torn-pages-and-the-dac-lag).

## 4. Function Pairing: the Whole Map

`[Supported Inference]`, static, 2026-11-03, the tier § 2 gave its byte match: each patched offset is an operand in the patched machine code, and the inference is that it names the same variable as the paired unpatched operand. Identical initialised bytes corroborate the data rows, and live captures confirm `0x1C3E`, `0x1C50`/`0x1C52`, `0x20EE` and `0x421C` (§ 2, § 3.1). `mise run pair-builds` ([`pair_builds.py`](../../python/scripts/pair_builds.py), [`build_pairing.py`](../../python/scripts/build_pairing.py)) pairs the two images' instructions function by function. It maps every row of [`memory-map.md`](memory-map.md), not only the four that § 2's byte match reached; the rows are in [`memory-map.md` § 1.1](memory-map.md#11-patch-3-build). Every offset § 2 found comes out the same.

The map was produced by these three runs, which print the summary and shift runs, the dispatch slots, and one line per row:

```bash
mise run pair-builds
mise run pair-builds -- --slots 0x824
mise run pair-builds -- --ds 0x0542,0x05AC,0x05B5,0x05BE,0x05CA,0x05D4,0x05DB,0x065D,0x069B,0x09DE,0x09EA,0x09F0,0x09F6,0x0A58,0x0A62,0x0AAB,0x0C10,0x0C50,0x0CA0,0x0C60,0x10A4,0x2240,0x225A,0x2263,0x2264,0x2265,0x2272,0x2275,0x227A,0x227B,0x227C,0x227D,0x2294,0x2296,0x2298,0x229A,0x229C,0x229E,0x22A4,0x22B6,0x22B8,0x22BC,0x22C4,0x22CA,0x22CC,0x22CE,0x22D0,0x2468,0x2768,0x474A,0x47C8,0x47E2,0x47E4,0x47E6,0x4758,0x4764,0x4778,0x4888,0x4896,0x48A2,0x48B6,0x4906,0x49C6,0x49EC,0x49EE,0x49F0,0x4F02,0x19A8@0x824,0x41B8@0x824,0x41C8@0x824,0x41CA@0x824,0x41D4@0x824,0x41D8@0x824,0x4450@0x824,0x7468@0x824,0x806C@0x824,0x806E@0x824,0x806F@0x824,0x8070@0x824,0x8072@0x824,0x8078@0x824,0x8082@0x824,0x8084@0x824,0x8086@0x824,0x8088@0x824,0x80C0@0x824,0x80CA@0x824,0x8108@0x824,0x810A@0x824,0x810C@0x824,0x8120@0x824,0x8126@0x824,0x8108@0:es,0x8120@0:es,0x8122@0:es,0x8126@0:es,0x8128@0:es,0x8078@0:es --code 0x0C5E,0x0C78,0x0C90,0x0C94,0x0C98,0x0CBD,0x0CC4,0x0CC8,0x0CD2,0x0CF2,0x0CFA,0x0EE6,0x0EE9,0x0F84,0x58D0,0x0FD2,0x11F8,0x11FC,0x122E,0x1238,0x123D,0x12DC,0x12E3,0x12F8,0x136F,0x196C,0x1D96,0x39B0,0x39D0,0x3D54,0x3D7F,0x42F5,0x4A29,0x4A32,0x4A35,0x6E1B,0x737B,0x7B70,0x7B79,0x843E,0x8A1C,0x8C45,0x908E,0x9100,0x9106,0xA9DC,0xAD88,0xAE66,0xB85D,0x1E451,0x995C,0x9481,0x965F,0xA56C
```

**Method.**

1. Unpack both images with [`unlzexe.py`](../../python/scripts/unlzexe.py). A code segment is one that a relocated far call lands in, or the entry segment; it ends where the next segment named by a relocation (or the stack segment) begins.
2. Decode each code segment with iced-x86 in 16-bit mode, as a linear sweep in which an invalid encoding counts as one instruction, and split it into functions at every near and far call target. The first run used Capstone with `skipdata`; iced-x86 gives the same offset for every row.
3. Reduce each instruction to a shape: mnemonic, registers, and constants and displacements below `0x100`. Addresses, larger immediates and branch targets become wildcards, and their values are kept.
4. Pair functions. Shape sequences unique in both builds, and in the same order (the longest increasing run), anchor the pairing; the functions between two anchors are aligned in order by shape similarity (`difflib` ratio at least 0.5).
5. Align the instructions of each pair (`difflib`). Every aligned pair maps a code address, and every wildcard in it is a vote on what that value became. Where two paired functions differ, a run of four or more repeats of a pattern up to four instructions long is left out: the aligner cannot tell which repeat is missing (§ 4.1).
6. Map a data offset by the absolute memory operands that name it; failing those, by displacements equal to it (`[bx + 0x4F02]`, a table base); failing those, by the immediates equal to it (`mov si, 0x2768`); failing those, by the shift its nearest named neighbours share ("bracketed"). An operand formed from `BP` without a prefix is in the stack segment and votes there, not in `DS`.

**Segments.** Both builds have four code segments, paired in order. Relocated immediates (`mov ax, seg`) pair the data segments: `DGROUP` `0x0D51` → `0x0C71` (37 immediates), the work segment `0x15D4` → `0x14BF` (22), `0x1DE7` → `0x1CD2`, and the mixer's data, inside `0x1DEA` before, has its own segment `0x1F57`.

| Code segment | Bytes | Functions | Identical | Paired | Instructions aligned |
|---|---|---|---|---|---|
| `0x0000` → `0x0000` (main program; `DS` is `DGROUP`) | `0x8240` → `0x7540` | 247 → 240 | 207 | 235 | 11,619 |
| `0x0824` → `0x0754` (display-list VM; `DS` is the work segment) | `0x52D0` → `0x51D0` | 72 → 72 | 69 | 72 | 8,435 |
| `0x1DEA` → `0x1CD5` (resident PCM mixer) | `0x30C0` → `0x0F20` | 30 → 28 | 0 | 2 | 27 |
| `0x20F6` → `0x1DC7` (far-called, `CS`-relative data) | `0x1900` → `0x1900` | 49 → 49 | 38 | 49 | 2,161 |

* **The main program pairs but for the dropped display drivers.** The 12 unpaired unpatched functions are `0x0568` and eleven at `0x6326..0x6DCB`, which write the VGA sequencer and graphics controller (`0x3C4`, `0x3CE`) and hold the alternate video-mode path at `0x6E1B`; the patch notes say Tandy and CGA graphics were dropped (§ 1). Five patched functions are new: `0x00DC`, `0x05DF`, `0x061A`, `0x06F2`, `0x4C4D`.
* **The votes never disagree.** Segment-0 memory operands name 371 distinct `DS` offsets, the VM segment 165 and segment-0 `ES` operands 50; each offset gets one answer from all its references. All 17 references to the film clock `0x4896` pair (§ 2's byte match found 2).
* **`DGROUP` moved by 12 different shifts, not one:** ten runs and two single offsets, `0x02E5` (`-0x1E7`) and `0x0C10` (`+0x112`). From the summary of `mise run pair-builds`:

  | Unpatched `DS` offsets | Shift | Offsets |
  |---|---|---|
  | `0x0000..0x0008` | `0` | 4 |
  | `0x018C..0x0250` | `-0x170` | 5 |
  | `0x02E5..0x052A` | `-0x1E6` (`0x02E5`: `-0x1E7`; `0x0300`: `0`) | 18 |
  | `0x0542..0x072A` | `+0x7C` | 26 |
  | `0x07F8..0x0A36` | `+0x84` | 27 |
  | `0x0BD4..0x0D98` | `+0x74`; `0x0C10`, named only by immediates, moved `+0x112` | 47 |
  | `0x10C6..0x10CA` | `-0x27E` | 3 |
  | `0x210C..0x2235` | `-0x67E` | 24 |
  | `0x2237..0x223B` | `-0x67C` | 3 |
  | `0x223D..0x8044` | `-0x67A` | 205 |

  The rest are not `DGROUP` data: `0x8830..0x8832` (`-0x350`) is the work segment's start seen through `DGROUP` (`0x15D4 - 0x0D51` paragraphs, `0x14BF - 0x0C71` patched), and `0x1952`, `0x41E8`/`0x41EA`, `0x806C` and `0x8CC0..0xF600` (shift 0) are read while `DS` is another segment. Objects are interleaved even inside a run: `0x0C10` moved `+0x112` among `+0x74` neighbours. A bracketed offset is therefore the weakest answer, and the map marks it.
* **The work segment's offsets did not change**, though its paragraph did (`0x15D4` → `0x14BF`). All 164 offsets the VM segment names through `DS` while `DS` is the work segment, and all 50 the main program names through `ES`, pair with themselves. The segment is `0x8130` bytes in both images, and its initial bytes are identical except 12 at `0x1952..0x195D`.
* **The lighting rows the #65/#66 probes read** pair instruction for instruction: the work-segment pointer `DS:0x0542` → `0x05BE` (13 of 13 references), the light copy `DS:0x49EC..0x49F0` → `0x4372..0x4376` (4 each), the var-13 handler `0x196C` → `0x1A7F`, the sun projection `0x908E` → `0x8385`, and the light setup entries `0x9100`/`0x9106` → `0x83F7`/`0x83FD`, whose work-segment stores (`0x8072`..) are unchanged.

### 4.1 The Patched Build Has One Dispatch Slot Fewer

`[Supported Inference]`, static. `mise run pair-builds -- --slots 0x824` reads the 9-byte dispatch slots at the start of each VM segment ([`sod-vm.md`](sod-vm.md) section 1) and pairs them through their handlers. The unpatched image has 108 slots (opcodes `0x0000..0x03C3`), the patched 107 (`0x0000..0x03BA`). Slots 0–91 (opcodes up to `0x0333`) jump to paired handlers at the same index. Unpatched slot 92, opcode `0x033C`, jumps to `0x988F` (`cmp byte [0x806B], 0` / `cmp byte [0x806C], 0` / `call [0x8080]`), and no patched slot jumps to code paired with it. Every later unpatched slot `k` pairs with patched slot `k - 1`. So an opcode word from `0x0345` up names a different handler on each build: unpatched `0x0345 + 9k` is patched `0x033C + 9k`.

[`sod-opcodes.md`](../formats/sod-opcodes.md) lists 107 opcodes, the patched count, and names `0x033C` `OP_VECELLIPSE` and `0x0345` `OP_VECELLSL`. Its names come from `SOD.H`, not from either binary, so neither build is known to be the one it numbers. Below `0x033C` it holds for both builds. From `0x033C` up, the unpatched build's opcode `n` is the patched build's `n - 9`, and which names belong to which build is Open question 1. The opcodes from `0x033C` up are the 2D ones (ellipses, letters, 2D vectors, circles). `SPRITES.RES` is the shape resource the patch replaced (§ 1); whether it re-encodes those opcodes is untested.

A jump table defeats instruction alignment: every slot has the same shape, so a missing slot can be placed anywhere in the run. Before step 5 left periodic runs out, the aligner paired unpatched slot 56 (`0x843E`) with patched slot 55. The slot rows of the map come from the handler pairing instead.

### 4.2 The Mixer Was Rewritten

`[Supported Inference]`, static. Two of the mixer segment's 30 functions pair, consistent with the patch's EMS sound fix (§ 1). The one far call from the main program into the mixer that pairs is the var-11 setter call at `0x0F3A` → `0x104B`. Unpatched, it loads `DX` from the film variable (`[bx + 0x94]`, `0x7E + 2 × 11`), sets `AX = 1` and calls `0x1DEA:0x05B1`, which stores `DX` in `cs:[0x49]` ([`memory-map.md`](memory-map.md) `[MEM-PALETTE]`). Patched, it loads `AX` from the same variable, sets `BX = 0` and calls `0x1CD5:0x0B67`, which stores `AX` at `+0x12` of the record that `0x1F57:[0x11B6 + 2 × BX]` points to: a per-channel record replaces the code-segment field.

---

## Ruled out

- **Running `PATSI.BAT` itself.** It ends in the interactive `SETUP`, and writing the corpus is not allowed (ADR 0022); the build applies the same deletions and extractions to a copy.
- **A patched tree without `GAME.CFG`.** `PLAYONE` would try to run `install.exe` at start (§ 1.1).
- **The byte match of § 2 for the other rows.** A reference whose neighbouring bytes hold other shifted addresses matches nowhere; it reached 2 of the film clock's 17 references, where function pairing reaches all 17 (§ 4).
- **One shift, or a shift per region, for `DGROUP`.** It moved by 12 shifts, and objects are interleaved inside a region: `0x0C10` moved `+0x112` among `+0x74` neighbours (§ 4).
- **Aligning a jump table instruction by instruction.** Every dispatch slot has one shape, so the aligner placed the dropped slot wrongly; slots pair through their handlers (§ 4.1).

## Open questions

1. Which opcode numbering do the shipped shapes use above `0x0333`? Unpatched `PLAYONE` has a slot at `0x033C` that the patched build dropped, so opcode words from `0x0345` up dispatch differently (§ 4.1). Counting the opcode words of every `.SOD` stream in the unpatched and patched `SPRITES.RES`, and in the resources the patch did not replace, would show whether the patch re-encoded them and which numbering [`sod-opcodes.md`](../formats/sod-opcodes.md) and the renderer follow.
2. Why does `BIGMAN` replay a tick apart from boot to boot, when `CTRY` does not? Candidates: its size (900 KB of `.FLM`, 1.4 MB of `.ALL`) makes `PLAYONE` read the disk mid-film, or its sounds. A survey of more films on both builds would show whether long films in general jitter. ([#77](https://github.com/neilsh/stunt-reel/issues/77))
3. Which films, if any, play on one `PLAYONE` build only when given the archive that build's `MAKEONE` writes? Generating both archives for the films whose resources the patch replaced (sprites, the two sound banks) would test SI Central's claim directly.
4. What `MAKEONE` waits for when it stays in graphics mode after writing the archive (`COUNT`, `EXIT` patched). A screen read at that point would show whether it is a prompt; `make-all` now accepts an archive unchanged for 60 s after the timeout (a MAKEONE hang) and records `returned_to_dos: false`, so the cause no longer blocks it. ([#76](https://github.com/neilsh/stunt-reel/issues/76))
5. Does the Easy/Hard flight model change how a film plays back? `SINEW.TXT` describes it as a flying change; whether `PLAYONE` replays recorded positions (no effect) or re-simulates (an effect) decides whether film choice by build is about physics or about something else.
6. The batch survey runs the patched build for every `siarchive/Films/NewPLAY/` film, whose folder ships Patch #3's `PLAYONE.EXE` (`staging._engine_root` takes a film's own tree), except the films in `UNPATCHED_CAPTURES` (`vault-intro`, `vault-tod`), which it captures with `--game-root builds/unpatched` ([`capture-dosbox-automation.md`](capture-dosbox-automation.md) § 4.7). Which other films need that awaits a survey on both builds. The list of capture stalls (`KNOWN_CAPTURE_STALLS`) is answered: on either build only `flmonly-bigman` still fails ([#29](https://github.com/neilsh/stunt-reel/pull/29), [#45](https://github.com/neilsh/stunt-reel/pull/45), [#77](https://github.com/neilsh/stunt-reel/issues/77)).
7. `captures/<film>/archives/<run>` and `frames/<run>` record the build only in `meta.json`, so a run name says nothing about which `PLAYONE` or `MAKEONE` made it. Whether the store should file runs by build is open. ([#79](https://github.com/neilsh/stunt-reel/issues/79))
8. What are the 12 work-segment bytes at `0x1952..0x195D` that differ between the builds' initial images (§ 4)? Patched VM code reads a word there (`mov si, [0x1952]` at `0x8B52`).
