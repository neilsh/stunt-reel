# Error readout

Part of the [`improving-render-parity`](SKILL.md) skill.

Run it on every film after a batch of render PRs, not after each one: a run costs about 14 Haiku passes and the tie-breaks.
It says which kinds of error the render makes and on how many frames; it cannot see misregistration, which the metrics cover.
The categories are `research/parity/error-categories.toml`.

```
- [ ] 1. Render the film on lavapipe (`mise run parity -- --software-only`, [`render-on-lavapipe.md`](../../../docs/howto/render-on-lavapipe.md)); a GPU render is not the baseline's class
- [ ] 2. mise run parity-bench -- errors-make --film <film>   (12 sheets, brief.md and brief-2.md)
- [ ] 3. Dispatch two fast-tier subagents at once (`Haiku` on Claude Code, `Gemini 4 Hydrogen` / `flash` on Antigravity), one per brief; each one's whole prompt: "Read build/parity/bench/<film>/errors/<brief>: it is your whole instruction"
- [ ] 4. mise run parity-bench -- errors-disputes --film <film>
- [ ] 5. If it names disputed sheets, dispatch one tie-break subagent (`Sonnet` on Claude Code, `inherit` on Antigravity) the same way on brief-tiebreak.md
- [ ] 6. mise run parity-bench -- errors-score --film <film> --against research/parity/readouts/<film>.json
- [ ] 7. When refreshing the baseline: copy each film's build/parity/bench/<film>/errors/readout.json over research/parity/readouts/<film>.json and update baseline.toml (commit, adapter, render_digest, disputed), in its own PR
```

The previous readout is the committed baseline, `research/parity/readouts/<film>.json`, with the commit and adapter it came from in [`baseline.toml`](../../../research/parity/readouts/baseline.toml).
`errors-score` refuses it when the render picked other ticks or the categories changed; then refresh the baseline.
Refresh all seven films together, per batch of render PRs (for example with the class-agreement batch), as step 7 says.

`errors-score` lists the categories whose count of sheets graded 2 or more moved by `min_change` or more (4 in `error-categories.toml`) as `changes since …`, then the smaller moves on one `below min_change (4): …` line (`none` when no count moved).
`changes since …: none` alone does not say the grades are unchanged, and both lines reading `none` does not either: grades can differ at equal counts.

Haiku misreads a frame now and then, a different frame each pass, so two fast passes that agree are trusted and the tie-break pass grades only the sheets where they disagree whether some category is clear (2 or more).

For batch films, print the `batch.md` readout table with `mise run parity-bench -- errors-table --films <slugs>` and paste it whole (it reads `build/parity/batch/<film>/report/report.json`, so for the reference films copy `build/parity/report/<film>_current/report.json` there first); write the prose under it from that table.

Skip `--against` for a film with no baseline file (a newly pinned reference) or for a calibrating run: a calibration grades only ticks the recapture holds, so `compare` refuses it.

Calibrate (`errors-make --calibrate`, 42 sheets, then `errors-score`) only when the categories, the sheet layout or the grading model change; it must print `calibration PASS`.
When `other` names the same new kind of error on two or more frames, add a `[[category]]` block, give it an example with `errors-example --film <film> --tick <tick> --category <id>`, and calibrate.
