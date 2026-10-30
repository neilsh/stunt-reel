# Batch Parity Survey: Every Distinct Corpus Film

`[Bounded Observation]`, 2026-10-30. The survey was stopped on purpose after **79 of 529** distinct films were scored (about 15%): enough to characterise the failure modes and the score spread, and the remaining films would cost tens of hours at 200 s per capture. The numbers below are the ledger at that point (`--summary` regenerates them); resuming is just `mise run batch-parity`. The plan is [`docs/process/plans/batch-parity-2026-10-30.md`](../../docs/process/plans/batch-parity-2026-10-30.md).

## 1. How to Run

```
mise run batch-parity                       # resumable: finished stages are skipped
mise run batch-parity -- --only SLUG,...    # named films
mise run batch-parity -- --limit N          # the first N films by slug
mise run batch-parity -- --retry-errors     # rerun stages whose latest record is an error
mise run batch-parity -- --jobs N            # N films at once (default 1)
mise run batch-parity -- --summary          # counts, failing films, lowest and highest SSIM
```

Each distinct film (579 `.FLM` files, 529 after de-duplication by sha256, [`batch_films.py`](../../python/stunt_reel/batch_films.py)) goes through four stages ([`batch_parity.py`](../../python/scripts/batch_parity.py), [`batch_stages.py`](../../python/stunt_reel/batch_stages.py)): `archive` (`MAKEONE` through `make_all`; skipped when a sibling `.ALL` exists, 260 films), `capture` (`capture_playone_reference`), `render` (`stuntreel --headless`) and `score` (`stuntreel parity`). The stages stop at a film's first error. A capture whose `meta.json` shows a stuck film clock (first and last `film_tick` equal) or fewer than 2 frames is recorded as `capture invalid: ...`, not ok. The append-only ledger is `build/parity/batch/ledger.jsonl` ([`batch_ledger.py`](../../python/stunt_reel/batch_ledger.py)), one record per stage run (`slug`, `stage`, `status`, `message`, `seconds`, `ssim`, `iou`); the latest record per slug and stage wins. Per film, `build/parity/batch/<slug>/report/` holds `report.json` and the contact sheets, copied to `frames/`; the rendered frames are deleted after a successful score because they run to 2 to 5 GB per film. With `--jobs N` each worker runs one film's stages in order; ledger appends and progress lines share one lock, `--max-renders M` (default 2) caps simultaneous renders, and a render waits, polling every 30 s, while less than `--min-free-gb` (default 8) is free under the batch root. Nothing here touches `references.toml`: the survey scores whatever capture it makes and pins nothing.

## 2. Results

By latest record per film and stage: archive 47 ok and 40 skipped (sibling `.ALL`), no errors; capture 80 ok and 5 errors; render and score 79 ok. 79 films scored.

* **Scores** (`[Bounded Observation]`, 79 films): median 0.68, 10th percentile 0.53, 90th percentile 0.79, range 0.004 to 0.924. 35 films score 0.70 or more; one reaches 0.88 (`vault-balloon`, 0.9236). 4 are below 0.1 and 7 below 0.5. For scale, the two pinned films score about 0.78 (CTRY) and 0.68 (INTRO) with the render tuned for them, so the untuned corpus lands in the same band; no film outside those two is near the 0.90 sign-off.
* **By family** (median, count): `flmonly` 0.73 (36), `desperat` 0.69 (3), `boz` 0.66 (3), `collage4` 0.63 (7), `collage5` 0.60 (9), `egalloc` 0.56 (11); `flmonly` is the best-behaved and `egalloc` the worst, but small families and noisy captures limit what that says.
* **Degenerate scores.** `vault-balloon` scored 0.9236 with IoU 0.0 and index agreement 0.0 over 3 frames, and its survey capture `frames/002` holds 3 frames at `film_tick` 0, the stuck-clock signature ([`../playone-exe/capture.md`](../playone-exe/capture-speed.md) § 1). Films below 0.05 (`collage4-elbarto` 0.0042, `flmonly-act5` 0.0071, `egalloc-egallo10` 0.0114, `flmonly-act1` 0.0196) had one scored frame with IoU about 0.83 and index agreement near 0. Neither group is parity evidence; the capture-validity check (§ 1) now rejects the stuck-clock case at capture time, but these scores predate it.
* **Capture stalls are intermittent.** `no new frame after 2001 trap hits (0 frame(s) captured, 6 to 9 indices on the page)` after the dialog settled. Five films still end in a capture error: `collage4-exit`, `collage4-exit2`, `flmonly-bigman`, `flmonly-count` (stalls) and `flmonly-colprt2` (`capture invalid: only 1 frame(s)`). But `amcrisis-ac`, `egalloc-egalloc0` and `egalloc-egalloc5` stalled on the first pass and captured fine on a retry (305 s, 146 s, 311 s), so a stall is not a property of the film. Each stall costs about 207 s. The driver skips a default list of known stalls (`--skip` adds slugs); given the intermittency, one retry is better than a permanent skip.
* **Archive timeouts** (`exit 124`, 900 s) hit films of 323 KB or more under the original `cycles = 8000` conf; `MAKEONE` plays in real time, so these were long films, not hangs. Under `core = dynamic` and `cycles = max` they were retried and none remains an error ([`../makeone-exe/driving.md`](../makeone-exe/driving.md) § 8).
* **Orphaned emulators.** A timeout killed only the direct Python child on Windows, so each left a `dosbox-x.exe` and a 12 MB stage directory. The runner now kills the process tree and `make_all` gets a 90 s head start on its own timeout.
* **Disk full.** The first full run died after 12 films (`WinError 112`): nothing deleted the render output. Fixed; see § 1.
* **`--capture-frames K`** (default 0, every frame) announces a stride but did not thin the frames on `vault-balloon` (112 frames either way, 10 to 11 ticks apart): guest time appears to follow the host clock through each debugger round trip, so skipped dumps do not widen the spacing ([`../playone-exe/capture.md`](../playone-exe/capture-speed.md) § 1).

## 3. Cost

Median stage times, from the ledger: archive 68 s (mixed settings; 7 to 27 s at `cycles = max`), capture 200 s (mean 229, 90th percentile 460, max 722), render 16 s, score 1.2 s. At the original settings archive generation was 44% of wall time and capture 52%; timeouts and failed captures were 37.5% of it. Capture is wall-paced (about 0.25 s per frame, 4 s of boot), and no DOSBox-X setting, `turbo` or frame sampling cut it, so serial capture over all 529 films would take about 36 hours. Eight captures at once on an idle machine finished in 64 s with the tick spread unchanged at 0 to 2 ticks ([`../playone-exe/capture.md`](../playone-exe/capture-speed.md) § 1); `--jobs 8` is therefore the lever, with renders capped by disk (2 to 5 GB each).

## Ruled out

- **De-duplicating by name.** The same film appears under several folders (`NewPLAY`, `OldPLAY`, `Morganroth`); only the content hash identifies it.
- **Keeping the rendered frames.** Gigabytes per film; the report and contact sheets are kept.

## Open questions

1. Rescore after rejecting stuck-clock and single-frame captures: how many of the 79 scored films survive the validity check? Rerun the suspects (`vault-balloon`, the four below 0.05) with the current harness.
2. Why do captures stall intermittently at the dialog (6 to 9 indices, the film never starts)? A stall that clears on retry points at timing in the dialog selection, not the film.
3. A scored single-frame film with IoU 0.83 and index agreement 0.001 suggests a palette or index-plane mismatch; look at one report's index planes.
4. A full `--jobs 8` survey has not run: the idle-machine test passed, but the heavy-load behaviour (the earlier -28 tick dips) is untested.
5. Resume to cover the remaining 450 films, or sample the families (`egalloc`, `collage4`, `collage5`) where scores are lowest.
