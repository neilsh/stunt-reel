# Error readout

Part of the [`improving-render-parity`](SKILL.md) skill.

Run it on every film after adopting a render change. It says which kinds of error the render makes and on how many frames; it cannot see misregistration, which the metrics cover. The categories are `research/parity/error-categories.toml`.

```
- [ ] 1. Copy build/parity/bench/<film>/errors/readout.json to build/scratch/<film>-readout.json (the previous readout)
- [ ] 2. mise run parity-bench -- errors-make --film <film>   (12 sheets, brief.md and brief-2.md)
- [ ] 3. Dispatch two Haiku subagents at once, one per brief; each one's whole prompt: "Read build/parity/bench/<film>/errors/<brief>: it is your whole instruction"
- [ ] 4. mise run parity-bench -- errors-disputes --film <film>
- [ ] 5. If it names disputed sheets, dispatch one Sonnet subagent the same way on brief-tiebreak.md
- [ ] 6. mise run parity-bench -- errors-score --film <film> --against build/scratch/<film>-readout.json
```

Haiku misreads a frame now and then, a different frame each pass, so two passes that agree are trusted and Sonnet grades only the sheets where they disagree whether some category is clear (2 or more).

For batch films, print the `batch.md` readout table with `mise run parity-bench -- errors-table --films <slugs>` and paste it whole; write the prose under it from that table.

Skip step 1 and `--against` when there is no previous readout or the previous run was a calibration: a calibration grades only ticks the recapture holds, so `compare` refuses it.

Calibrate (`errors-make --calibrate`, 42 sheets, then `errors-score`) only when the categories, the sheet layout or the grading model change; it must print `calibration PASS`. When `other` names the same new kind of error on two or more frames, add a `[[category]]` block, give it an example with `errors-example --film <film> --tick <tick> --category <id>`, and calibrate.
