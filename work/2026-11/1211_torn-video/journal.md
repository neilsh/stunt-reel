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
* The neighbour-frame test of the video alone separates nothing: 1,634 of 1,905 frames hold rows equal to neither neighbour, 26 of 31 whole frames and 82 of 90 torn ones among them.

**Verdict.** The strip explanation is rejected; a tear's row follows when the guest copy meets the beam, and a band spans many rows.
`debugmsg` works as a sink; the heap cap does not apply to what it writes.

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` §§ 1, 4.6 and Ruled out.

## 2026-11-27: Streaming the composed buffers of CTRY through debugmsg

**Question.** Does a per-frame stream of both composed buffers through `dosbox.debugmsg` give a whole picture for every pinned `CTRY` page, leave the recording unchanged, and fit the Lua budget? (#1211, Phase B step 1, the probe.)

**Method.** Patch 3, stubbed samples, `capture` profile, dosbox-automation 0.85.1, scratch scripts in the project files folder (`1211-torn-video/b1_probe.py`, `b1_stats.py`, `b1_gate.py`, `b1_palette.py`, `b1_spin_calibrate.py`); every figure is in [`b1-probe-summary.txt`](b1-probe-summary.txt).
`capture-video` ran with `luagen.video_script` patched to log, at each frame's row, both segment words (`layout.composed_pages`), whether `A000` rows 0..191 equal each buffer, and each buffer's rows 0..191 as hex, loaded with `?debug=true`.
The pinned pages' rows 0..184 were compared as palette indices with the streamed buffers at `emu_frame - 8 .. + 8`.

**Result.**

* Every one of the 121 pinned pages equals a streamed buffer at offset 0: 119 the word the harness reads second (`word1`), 2 the other word (frames where `A000` equals it).
  `A000` equals `word1` alone on 1,786 of 1,907 frames, `word0` alone on 31, both on 5.
  The working palette rebuilt from the run's `meta.json` equals the page's palette on 121 of 121 pages at the same frame.
  In the video the same pages were exact on 31 of 121 (Phase A).
  The match holds by construction: the harness keeps a page only when `A000` rows 0..191 equal a composed buffer (`luagen.py`), so it shows the stream is read at the right frame and replays, and that a whole picture is present on the 90 pages where the video is torn, not that it is whole on frames the harness skips.
* `A000` equals neither buffer on 85 frames (4.5%), the frames the harness would count as torn (`TRACE_TORN`); none of the 121 pinned frames is among them (all 119 are `(0,1,0)`, 2 are `(1,0,0)`), so they are not the video's 90 torn pages, whose pictures the stream holds at frames where `A000` was whole.
* The stream leaves the recording alone: `capture.avi` and `meta.json` equal the stream-off run's, and two stream runs have equal payloads.
* Cost: about 71 more Lua instructions a frame (estimate from a spin counter, one run each; the planner's 25 to 35 was too low).
  The stream-off run used about 126,000 instructions, boot included, so one script holds between about 7,300 frames (all of that is per-frame) and about 12,300 (all boot); `LOCATION.FLM` (11,616 frames) may need two passes unless the row is lightened.
  Wall time stayed 46 to 49 s across a stream, a stream-plus-spin and a spin-only run; the log is 469 MB for the two buffers.

**Verdict.** Go on step 2 for `CTRY`.
The front rule is open: "the word `A000` equals" matches all 121 pages by construction; which word is the newest finished picture on frames where `A000` equals neither, and whether each streamed picture is whole in `A000` at some frame, were not measured.
The instruction cost is high enough that the row should be lightened (one buffer, one `debugmsg` a frame) before step 2 counts frames a script.

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.

## 2026-11-28: Step 2, the stream inside capture-video

**Question.** Does `capture-video --stream` (one `debugmsg` line a frame: the buffer `A000` equals, else the second) leave the recording unchanged, keep every pinned `CTRY` page, and cost less than the probe's three lines?

**Method.** Patch 3, stubbed samples, `capture` profile, dosbox-automation 0.85.1; `mise run capture-video -- --film corpus/stisldem/VAULT/CTRY.FLM --game-root <data root>/builds/patch3 --out <dir> --stream`, built by a Haiku worker and checked here.
Scratch scripts in the project files folder: `s2_gate.py` (pinned pages against the `p` lines at their frame and one either side) and `s2_spin.py` (the spin counter of the probe, calibrated at 3.01 instructions an iteration).

**Result.**

* 1,907 frames, ends `hold`, 234,901,293-byte `stream.log`, 1,907 `p` lines and the `e` trailer; `capture.avi` sha256 equals the stream-off recording's (`e1e8cd339069...`), and `meta.json` differs only in `captured_on`.
* Each of the 121 pinned pages equals the logged picture at its own frame (110 at that frame only, 11 also at the next); the flags are 2 on 1,786 frames, 1 on 31, 3 on 5 and 0 on 85, as the probe's.
* The stream-plus-spin run reached 259,000 spin iterations, the no-stream run (probe) 290,000: about 93,000 more instructions, 49 a frame, about 115 a frame with the stream and boot.
  One script then holds between about 8,700 frames (the no-stream 126,000 all per-frame) and about 17,800 (all boot); `LOCATION.FLM` (11,616 frames) fits unless about half or more of the no-stream cost is per-frame.
* The emulator appends `script completed` lines after the trailer, so the check looks for the trailer after the last `p` line, not as the last line (the first attempt failed on that).

**Verdict.** Go on step 3 (decode and encode).

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.

## 2026-11-28: Step 3, decoding the stream log to an index video

**Question.** Does `stream.log` encode to a small lossless file that decodes back to the same index pictures, and does the decoded picture at each pinned `CTRY` page's frame equal the page?

**Method.** A copy of the `stream.log` of the step 2 run (`/home/user/s2`, 1,907 frames; the encode ran in `/home/user/s3`, so the original log stays) through `mise run stream-encode -- <dir> --delete-log` (a Haiku-built module, `stunt_reel.tac.stream`): the pictures piped as raw 320x192 gray8 into `ffmpeg -c:v ffv1 -level 3`, decoded back and compared by SHA-256, then `stream.json` written and the copy's log deleted.
`s3_gate.py` (project files folder) decoded `stream.mkv` and compared rows 0..184 at each pinned page's `emu_frame`.

**Result.**

* 1,907 pictures, 117.2 MB raw, 235 MB of log hex, `stream.mkv` 8,450,448 bytes (about 14 times smaller than the raw pictures, 28 times smaller than the log); encoding took about 2 s in all, with no split between ffmpeg and the parsing.
  Round trip: raw and decoded SHA-256 equal (`afbdd910d785...`).
* 121 of 121 pinned pages equal the decoded picture at their own frame, as they equalled the log's.
* `stream.json` records file, both hashes, frame count, first frame 1276, size, flag counts (0: 85, 1: 31, 2: 1,786, 3: 5), layout `patch3` and end `hold`; a `stream` field in `meta.json` was left out (it needs the Rust parity structs and their schema).
* After #1218's front-rule finding, `stream.json` also lists the frames with flags 0 as `held` (85 on this run), so a consumer repeats the last picture of flags 1 to 3 there; the video keeps every logged picture.
* The log's trailer is `exhold`, not `ehold`, because the script's strings carry an `x` prefix; the parser accepts both.

**Verdict.** Go on step 4 (consumers).

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.

## 2026-11-28: The front rule on frames where A000 equals neither buffer

**Question.** Which composed buffer holds the newest whole picture on frames where `A000` equals neither, so a decoder of `capture-video --stream` knows what to show there? (#1211, step 3 input.)

**Method.** The step 1 probe (`1211-torn-video/b1_probe.py` in the project files folder) rerun on `CTRY.FLM` (Patch 3, stubbed samples, `capture` profile), then a scratch analysis of its log hashing each buffer per frame (not committed).

**Result.** `[Bounded Observation]`, one run.

* The flags repeat step 1: `A000` equals the second word only on 1,786 frames, the first only on 31, both on 5 and neither on 85; the words swap 696 times.
* On the 85 frames, neither buffer's picture appears whole in `A000` in the 4 frames before; the second word's appears in the 4 after on 5 of 85, the first word's on none.
* The second word's buffer changed with no word change on 967 frames, and 107 of its 1,623 distinct pictures never appear whole in `A000`: a buffer can be read mid-compose, so the second buffer logged on a neither frame could be a picture never shown whole.

**Verdict.** Step 3 should treat a `p` line with flags 0 (neither) as held: repeat the last picture with flags 1 to 3, and count the held frames (85 of 1,907, 4.5%, on `CTRY`).

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.

## 2026-11-28: Step 4, the stream in video-derive

**Question.** Does a recording's stream reproduce the pinned `CTRY` pages by palette index, replay equal across two runs, and change what the ADR 0057 key test says about run-end pictures?

**Method.** `reference-check ctry --stream`, `replay` and `pairing --stream` (new, built by a Haiku worker and checked here) on two stream recordings of `CTRY.FLM` (Patch 3, stubbed samples, `capture` profile; encoded with `stream-encode`), and `pairing` on the video of the first for comparison.
`reference-check --stream` writes nothing; the stream compares indices, so it needs no palette mapping.
`pairing --stream` takes each run-end row's picture from the stream, leaves out rows on held frames and keeps the palette-lag exclusion.

**Result.** `[Bounded Observation]`, two recordings.

* 121 of 121 pages equal the stream picture at offset 0; none is on a held frame; the working palette at that frame equals the page's on 121 of 121.
* Two recordings: `capture.avi`, `meta.json` and the stream's raw SHA-256 equal.
* Keys, last row of a run, run ends compared 1,031 on the stream (69 on held frames left out) and 1,100 on the video: `render_tick` 256 of 256 shared keys name more than one picture (video 296 of 296), `film_tick` 141 of 141 (video 180 of 180).
  First row: `render_tick` 164 of 164 (video 179 of 179), `film_tick` 65 of 65 (video 78 of 78).
* Not run: the render-SSIM half of `pairing` on the stream (no render store at hand), other films.

**Verdict.** The ADR 0057 rule is neither confirmed nor changed: the key test still fails on whole pictures, so tears are not its cause; no adopted rule or score is touched.

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.

## 2026-11-28: Step 5, segmented stream passes

**Question.** Can a film that does not fit one script (`LOCATION.FLM`, which fails with `--stream`: "instruction limit exceeded" after about 157 s on the Legion recording, its stream-off recording succeeding) be streamed whole by replaying it in segments, with segments that agree on their shared frames?

**Method.** `capture-video --stream --stream-segment N` (new, built by a Haiku worker and checked here): the stream-off recording first, then one emulator run per segment (the same boot keys and `capture_start()`, a chunked `wait_frames` skip to the frame before the segment's first, then the stream lines only), merged into `stream.log`.
`CTRY.FLM` with N = 700 (three segments) against the single-pass run in the project's scratch folder; `LOCATION.FLM` with N = 6,000, then `stream-encode` and `video-derive reference-check location --stream`.

**Result.** `[Bounded Observation]`, one run each.

* `CTRY.FLM`, 700-frame segments (frames 1276 to 1975, 1975 to 2674, 2674 to 3182): `capture.avi`, `meta.json` and the stream's raw SHA-256 (`afbdd910d785...`) equal the single-pass run's.
* `LOCATION.FLM`, 6,000-frame segments (1276 to 7275, 7275 to 12891): 11,616 frames, `hold`, 118 palette changes, `stream.log` 1.43 GB, `stream.mkv` 52.4 MB for 713.7 MB raw in about 11 s of encoding; flags 0: 608, 1: 203, 2: 10,654, 3: 151.
  The merge accepted the shared frame 7275 (byte-identical in both runs).
* 745 of 745 pinned `LOCATION` pages equal the stream picture at offset 0, none on a held frame, working palette equal on 745 of 745.

**Verdict.** Segmented passes work on the two films tried; step 5 is done. Films past about 11,616 frames and a larger segment length are untried.

**Lives in.** `research/playone-exe/capture-dosbox-automation.md` § 4.6.
