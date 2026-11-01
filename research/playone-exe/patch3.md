# Patch #3: The Patched Build of `PLAYONE.EXE` and `MAKEONE.EXE`

Disney's "Sound Blaster Update" for Stunt Island (`corpus/patches`, Patch #3, archives dated 1993-09-06, wrapper 1994-03-18) replaces every executable the game ships. This note records what it changes, where the patched `PLAYONE.EXE` keeps what the capture harness reads, and which build each tested film needs. `mise run game-builds` ([`game_builds.py`](../../python/scripts/game_builds.py), [`stunt_reel/game_builds.py`](../../python/stunt_reel/game_builds.py)) builds both trees under `<data root>/builds/` and writes `builds/patch3-manifest.json`; `capture-ref`, `play` and `make-all` take `--game-root <data root>/builds/patched` to run the patched programs.

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

The first `0xA4` bytes of the two entry routines are the same instructions; only operands differ. Data at `DS:0x2200` and above moved down by `0x67A` (`0x22C4`, `0x22CE`, `0x22D0`, `0x2263` to `0x2268`, `0x56A2`, `0x5786`), the strings near `0x0600` moved up by `0x7C` (`game.cfg` `0x05AC` → `0x0628`, `install.exe` `0x05BE` → `0x063A`), and one word moved by `0x67E` (`0x14CC` → `0x0E4E`), so the data segment was not shifted as a whole. For each instruction of the unpatched image that names `DS:0x4896`, `0x22B8`, `0x2768` or `0x22C4`, the bytes on each side (up to 12, address wildcarded) were searched in the patched image and kept when exactly one place matched. Every unique match gave the same shift, `-0x67A`: `0x4896` → `0x421C` (2 of 17 references matched uniquely), `0x22B8` → `0x1C3E` (2 of 4), `0x2768` → `0x20EE` (7 of 10), `0x22C4` → `0x1C4A` (1 of 3, and the entry routine itself). References that did not match uniquely sit beside other shifted addresses, so a byte match cannot see them; none matched elsewhere. The rows are in [`memory-map.md` § 1.1](memory-map.md#11-patch-3-build).

Live check: `CTRY.FLM` with its shipped `.ALL` on the patched tree, `mise run capture-ref -- --game-root <data root>/builds/patched` (the harness picks the offsets by the executable's hash, [`playone.py`](../../python/stunt_reel/tac/playone.py) `layout_for`). The film clock at `0x0E66:0x421C` and the global tick at `0x0E66:0x1C3E` rose together from 27 (one kept frame per 11 ticks, film tick equal to global tick, as on the unpatched build), and at the three film ticks shared with the unpatched reference `captures/vault-ctry/frames/002` the working palette read at `0x20EE` was identical to the unpatched one at `0x2768`.

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
* **`MAKEONE` does not always return to DOS.** It wrote `COUNT.ALL` within a minute but neither build left graphics mode in 15 minutes. The patched build never returned on `EXIT` or `EXIT2` (4 runs, the archive complete and unchanged for 60 s); the unpatched one returned on `EXIT` (27 s) and on one of two `EXIT2` runs (29 s). Both returned on `BIGMAN` (476 s, 514 s). `make-all` waits for text mode, so it reports these as timeouts and discards a good archive ([`../makeone-exe/driving.md`](../makeone-exe/driving.md) § 9).

* **Two retail films play only on the unpatched build with their shipped archive.** `[Bounded Observation]`, 2026-11-01. `siarchive/Films/NewPLAY/` ships the patched `PLAYONE.EXE`, which the batch survey runs for every film in that folder. With the folder's own `TOD.ALL` and `INTRO.ALL` it stalls (`TOD.FLM`'s clock falls to 0 near tick 200; `INTRO.FLM` holds its title card); the unpatched build plays both archives, and the patched build plays the demo's `INTRO.ALL` and a patched-`MAKEONE` `TOD.ALL` ([`capture-dosbox-automation.md` § 4.7](capture-dosbox-automation.md#47-the-instruction-budget-and-three-retail-archives)).

SI Central's advice that some older films play only on the unpatched `PLAYONE` and most newer ones need the patched build is not borne out by these four. Its likeliest mechanism is the one `BIGMAN` shows: a `.ALL` built by one `MAKEONE` played on the other `PLAYONE`.

---

### 3.1 Composed Pages

`[Bounded Observation]`, 2026-10-31. The patched build's composed-page words were taken as `0x1C50` and `0x1C52`, the unpatched `0x22CA`/`0x22CC` less `0x67A`. A `CTRY.FLM` capture on the patched tree (`mise run capture-ref -- --game-root <data root>/builds/patched`) traced 1,906 frames and flagged 72 torn (3.8%), against 66 of 1,908 on the unpatched build; a torn flag needs bands that match only one buffer and others only the other, which words naming other memory could not produce. See [`capture-dosbox-automation.md` § 4.5](capture-dosbox-automation.md#45-torn-pages-and-the-dac-lag).

## Ruled out

- **Running `PATSI.BAT` itself.** It ends in the interactive `SETUP`, and writing the corpus is not allowed (ADR 0022); the build applies the same deletions and extractions to a copy.
- **A patched tree without `GAME.CFG`.** `PLAYONE` would try to run `install.exe` at start (§ 1.1).

## Open questions

1. The other `DGROUP` rows of [`memory-map.md`](memory-map.md) (camera rig, actor table, sound flags, the work-segment pointer `probe-light` reads) are not mapped for the patched build. A Capstone decode of both images that pairs instructions by function, rather than the byte match of § 2, would map them all.
2. Why does `BIGMAN` replay a tick apart from boot to boot, when `CTRY` does not? Candidates: its size (900 KB of `.FLM`, 1.4 MB of `.ALL`) makes `PLAYONE` read the disk mid-film, or its sounds. A survey of more films on both builds would show whether long films in general jitter.
3. Which films, if any, play on one `PLAYONE` build only when given the archive that build's `MAKEONE` writes? Generating both archives for the films whose resources the patch replaced (sprites, the two sound banks) would test SI Central's claim directly.
4. What `MAKEONE` waits for when it stays in graphics mode after writing the archive (`COUNT`, `EXIT` patched). A screen read at that point would show whether it is a prompt; `make-all` could then also accept an archive that has stopped changing.
5. Does the Easy/Hard flight model change how a film plays back? `SINEW.TXT` describes it as a flying change; whether `PLAYONE` replays recorded positions (no effect) or re-simulates (an effect) decides whether film choice by build is about physics or about something else.
6. The batch survey has no `--game-root`, but it already runs the patched build for every `siarchive/Films/NewPLAY/` film, whose folder ships Patch #3's `PLAYONE.EXE` (`staging._engine_root` takes a film's own tree); it cannot choose a build per film, and its list of capture stalls (`KNOWN_CAPTURE_STALLS`) awaits a re-survey under dosbox-automation on both builds.
7. `captures/<film>/archives/<run>` and `frames/<run>` record the build only in `meta.json`, so a run name says nothing about which `PLAYONE` or `MAKEONE` made it. Whether the store should file runs by build is open.
