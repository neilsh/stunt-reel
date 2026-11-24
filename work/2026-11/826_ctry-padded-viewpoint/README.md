---
title: "research: what moves the viewpoint on CTRY's padded-archive pages"
started: 2026-11-24
issue: 826
outcome: "The slots are placed by the fraction the film step sets from the clock before the render, and the HUD reads the clock after it (the slot pass and the angle bank read it in between; far, word-table and register calls not followed); under DOSBox-X that gap varies 1 to 5 ticks per frame and the camera's eye and angles carried no state in two runs; on 12 of CTRY's 23 padded-archive viewpoint pages (5 at an equal HUD clock) the own and padded captures' scenes are a tick apart at one tag on peaked score curves, 3 more on near-flat ones, so parity's t - 1 pairs at least one page of each such pair with a render a tick off; 6 pages are undecided, 2 unscored, and no page was dated absolutely. Part of #826: the rest stays on the issue."
---

# research: what moves the viewpoint on CTRY's padded-archive pages

The static reading, the two DOSBox-X runs and the page offsets are in the [journal](journal.md); the findings are in [`film-load.md`](../../../research/playone-exe/film-load.md) § 5, with [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) open question 15 and [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results).

## Handoff

Done: the film step's clock against the HUD's, read statically and logged per drawn frame on DOSBox-X (plan `tools/dosbox-x/plans/view-clock.toml`); #348's own and padded captures retaken and each page's render offset compared across them ([`page_offsets.py`](page_offsets.py), [`live_lag.py`](live_lag.py)).
Left, on #826: dating each captured page by the film step's clock inside the capture run, which would decide the 6 undecided and 3 near-flat pages and give each page's lag behind its tag; reading the frame's far, word-table and register calls for a clock read; whether the angle bank's later clock reading (`0x1DCA`) shows on the viewpoint pages ([`film-load.md`](../../../research/playone-exe/film-load.md) open question 1); the propeller pages stay with the angle bank's var 10 hypothesis.
Scratch (not committed): archives, stages, captures and runs in `<data root>/scratch/826/`; scored reports in `build/scratch/826/`.
