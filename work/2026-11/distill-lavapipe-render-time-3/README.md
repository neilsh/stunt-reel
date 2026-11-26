---
title: "Distill research/parity/lavapipe-render-time.md, third pass"
started: 2026-11-26
outcome: "The note is split by subject: the world draws' cost, #1002's profile, #999 and #1090 went to lavapipe-world-draws.md, and thread scaling, workers and memory per worker to lavapipe-render-workers.md; section 3's five per-issue blocks were condensed with their long forms and the old summary moved to journal.md, and all three notes are under the 32 KiB budget"
---
# Distill `lavapipe-render-time.md`, third pass

The note was 56,110 bytes, over the 32 KiB budget for `research/` (`mise run doc-health`, 2026-11-26).
Two earlier passes, [`distill-lavapipe-render-time`](../distill-lavapipe-render-time/README.md) and [`distill-lavapipe-render-time-2`](../distill-lavapipe-render-time-2/README.md), left it over budget as current reference and named a split by subject as the fix; the daily gardening routine picked it again, and this pass makes that split.

- [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) keeps the changes that cut render time, the draws per frame, the loop's phases, startup and the timing noise of one binary against itself (`#1004`, `#1018`).
- [`lavapipe-world-draws.md`](../../../research/parity/lavapipe-world-draws.md) takes what the world's base and decal draws cost (`#920`, `#1000`), `#1002`'s stack profile, `#999`'s frame-stream sizes and `#1090`'s shared-slice count, with their Ruled out entries and open questions.
- [`lavapipe-render-workers.md`](../../../research/parity/lavapipe-render-workers.md) takes the old sections 4, 5 and 7 (thread scaling, in-process devices against child processes, `--workers`, memory per worker) and section 6's `#920` memory case.

Text moved between the notes is unchanged apart from section numbers and links.
[`journal.md`](journal.md) holds, verbatim, the five per-issue blocks of the old section 3 (`#1002`, `#1004`, `#999`, `#1018`, `#1090`), which the notes now state condensed, and the old `summary:`.
Links into the old sections 5 and 7 from code comments, how-tos, `evidence-limits.md` and `ARCHITECTURE.md` now point at `lavapipe-render-workers.md`; links in frozen work folders are left as they were.
