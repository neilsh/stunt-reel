# Journal: COUNT.FLM jitter

## 2026-11-13: COUNT.FLM with its sound sample stubbed

- **Question**: Does `COUNT.FLM` replay differently from boot to boot because of the sound sample in its archive, as `BALLOON.FLM` and `CTRY.FLM` do (#305)? If not, does `sbtype = sb16` with `oplmode = none`, `core = normal`, or no host-driven key after the film starts make the runs identical?
- **Method**: At `a032c45a` (`origin/main`), on the unpatched build (`<data root>/builds/unpatched`), one trace after the other, the `capture` profile (dynamic core, 45,000 cycles):
  1. `mise run make-all -- --film corpus/siarchive/Films/FLMOnly/COUNT.FLM --game-root <data root>/builds/unpatched --out <data root>/spike/179/makeall` built `COUNT.ALL` (3,312 bytes, sha256 `785090c5…`). It holds eleven chunks, one in `0xC000`–`0xCFFF`: `0xC31E`, 12 bytes, starting `02 00 88 88 88 88`.
  2. `mise run stub-sound-samples -- <makeall>/COUNT.ALL -o <data root>/spike/179/COUNT-stub.ALL` cut that chunk to the one byte `0x04` (3,301 bytes, sha256 `72cea511…`).
  3. Ten runs of `mise run capture-ref -- --film corpus/siarchive/Films/FLMOnly/COUNT.FLM --name spike179-stub --game-root <data root>/builds/unpatched --archive <data root>/spike/179/COUNT-stub.ALL --sound-samples kept --stride 1 --out <data root>/spike/179/stub-NN`. The control, ten runs of the same command with `--archive <makeall>/COUNT.ALL --name spike179-kept --out .../kept-NN`, shows whether this harness can see the jitter at all. `--sound-samples kept` stops staging from stubbing again, so the archive played is the one hashed.
  4. Comparison: `mise run capture-compare` refuses each pair (`unpaired: 10 shared film ticks, fewer than 20`), because the harness keeps 10 pages (`window pass 1/1: 10 windows`). So each run's pages, palettes and `(film_tick, emu_frame)` pairs were hashed (MD5 of the `.idx` and `.json` files, and one hash over a run's `frames/`) and counted by distinct value.
- **Result**:

  | Archive | Distinct runs of 10 | Pages differing from the most common run | `emu_frame` differing |
  |---|---|---|---|
  | stubbed | 1 (10 of 10 identical) | none | none |
  | sound kept | 5 (counts 5, 2, 1, 1, 1) | tick 9 in 3 runs, 1 pixel at (27, 180); tick 60 in 1 run, 300 pixels | tick 60 in 3 runs, 1354 for 1355 |

  - Every run, stubbed or kept, logged the same `film_tick` values in its own set: the kept runs' pages are labelled 9, 17, 26, 34, 43, 51, 60, 68, 77, 86 and the stubbed runs' 9, 18, 26, 35, 43, 52, 61, 69, 78, 86. So the sample moves which ticks the windows reach; no kept run labelled a page with another tick.
  - `torn_frames` (frames the harness skipped as torn) is 1 in 7 of the ten kept runs (02–07, 09), including all five of the most common run, and 0 in all ten stubbed runs. The tick-60 page that differs (kept-01 only) has its 300 pixels in rows 0–91, a top-band pattern that fits a tear; whether it is one was not checked, so the cause of that difference is open. `torn_frames` counts skipped frames, not the kept page.
  - The kept runs vary less than the old per-frame traces did (10 to 18 of 157 frames a tick apart, in five traces on 2026-10-30). The stubbed runs showing no variation against a control that varies is the evidence; the old trace was not re-run on the stubbed archive.
  - The three fallback setups were not run.
- **Verdict**: adopted for the 10-window capture; `[Bounded Observation]`, one archive, one build, ten runs each. That the old 157-frame clock jitter has the same cause is `[Supported Inference]`.
- **Lives in**: [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4, Ruled out and open question 5.
