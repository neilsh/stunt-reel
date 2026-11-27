# Journal: torn video frames

## 2026-11-27: Where tears fall, and debugmsg as a sink

**Question.** Do the tears of the full-rate video fall on fixed strip-boundary rows, can a strip-row discontinuity find them, does `dosbox.debugmsg` write pages out without the 16 MB Lua heap, and is the AVI indexed? (#1211, phase A.)

**Method.** `main` at `f1cea15`, cloud session, dosbox-automation 0.85.1 (sources read at tag `v0.85.1`).
`mise run game-builds`, then `mise run capture-video -- --film corpus/stisldem/VAULT/CTRY.FLM --game-root <data root>/builds/patch3 --out <scratch>`; `mise run video-derive -- reference-check ctry --dir <scratch>`.
Row matching: each of the 121 pinned `CTRY` pages' rows 0..184 against the frames `base-2 .. base+4` (`ROW_WINDOW`), with scripts in the project files folder (`1211-torn-video/`); every figure is in [`a2-ctry-summary.txt`](a2-ctry-summary.txt).
The probe: `a4_probe.py` loads a script with `POST /script/load?debug=true` at the DOS prompt (no game) and calls `dosbox.debugmsg` 500 times with a 128,000-character string; `a4b_pages.py` does the same with 500 real `mem_read(0xA000, 0, 64000):gsub(".", H)` pages.

**Result.**

* The recording ends `hold` at 1,907 frames.
  `CTRY` has 121 pinned pages, 31 exact, 28 split and 62 band; the 1,032, 503 and 340 of the issue are the sums over seven films.
* No fixed rows.
  Of 62 band pages, 34 start in rows 80..97 and the most common start (rows 92 and 82) holds 6 pages; the unmatched rows of all bands cover 171 of 185 rows.
  A band spans a median 20.5 rows (maximum 91).
  Of 28 split pages, 22 differ from their best video frame only on rows 179..184 (the HUD timer, rows 179 to 183), so they say nothing about the 3D rows, and 25 have a tear interval wider than 3 rows; three pin one down (ordinals 24, 27 and 89, at rows 181, 92 to 93 and 57 to 58).
  The gate (more than about 80% of tear rows on a few fixed rows) fails.
* In `vga_draw.cpp` at `v0.85.1`, `setup_drawing()` gives machine `vga` (the conf's `svga_s3`) in a mode below 640x480 `DrawMode::Scanline`: `VGA_DrawSingleLine` draws one row per PIC event and reads video memory then.
  The four strips (`parts_total = 4`) belong to `DrawMode::Part`, used for Hercules and for high-resolution VGA modes, so mode 13h has none.
* A3 found a weak detector at best (AUC 0.60; 21 of 90 torn frames caught, 1 of 31 whole ones flagged; summary file); the strip premise it rested on did not hold.
* `dosbox.debugmsg(s)` (`lua_api.cpp`, `LuaDebugMsg`): `luaL_checkstring`, then `DebugLog::TraceMessage` copies the string to a `std::string`, `vfprintf("%s")` into `<config dir>/logs/lua-debug-<time>-<script name>.log` (here `/root/.config/dosbox-automation/logs/`) and `fflush` per call, only when the script was loaded with `debug=true`; no size cap in the code, and the `const char*` becomes a `std::string`, which a NUL cuts.
  500 lines of 128,000 characters: 64,018,187-byte file, all 500 lines byte-identical to what the script built, whole script 0.2 s wall (frame 17); the line `"nul\0tail"` arrived as `nul`.
  500 real `A000` reads hex-encoded with `gsub`: 64,050,148 bytes, 1.2 s wall, no heap error; their content was not compared.
  Holding pages instead (the Lua heap cap, `DefaultMemoryCapBytes` 16 MB): 100 held of 128,000 characters ran, 140 died `not enough memory`.
  The instruction count and peak heap are not reported by the host and `collectgarbage` is removed from the sandbox, so neither was measured.
* `ffprobe capture.avi`: codec `zmbv`, `bgr0`, 320x200, 1,907 frames; not `pal8`.
* The neighbour-frame test of the video alone cannot find a tear: 1,634 of 1,905 frames hold rows equal to neither neighbour.

**Verdict.** The strip explanation is rejected; a tear's row follows when the guest copy meets the beam, and a band spans many rows.
`debugmsg` works as a sink; the heap cap does not apply to what it writes.

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` §§ 1, 4.5, 4.6 and Ruled out.
