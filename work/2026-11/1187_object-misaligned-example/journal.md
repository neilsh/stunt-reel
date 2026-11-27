# Journal

## 2026-11-27: an object-misaligned example from a second model

`[Bounded Observation]`, 2026-11-27, the TRAINTNL readout sheets of the 2026-11-27 baseline (`errors-make --film traintnl`, seed 1, at `919ecae`; render digest `613ec855…`, equal to the baseline's), cloud session.

#1110 left `object-misaligned` with no example: both Haiku passes graded TRAINTNL 232 3 there, and no second model had graded it.
One Sonnet subagent graded all 12 TRAINTNL sheets from `brief.md` alone, not told which sheet was in question, writing [`traintnl-grades-sonnet.txt`](traintnl-grades-sonnet.txt).
It graded TRAINTNL 232 (sheet `3b93533543fd`) 2 in `object-misaligned`, its only sheet at 2 or more in that category, with the note "train body shading differs from capture"; it graded five other sheets 1 there.
So two models graded the sheet 2 or more, and `errors-example --film traintnl --tick 232 --category object-misaligned` added `traintnl-0232`, byte-identical to the graded sheet.
