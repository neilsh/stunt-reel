# Comparing a candidate reference

Part of the [`improving-render-parity`](SKILL.md) skill.

A new capture becomes a film's reference only through a reviewed commit of `research/parity/references.toml` plus a `log.md` row. To decide whether to promote one, score the candidate and the current reference with the same binary:

```
- [ ] 1. mise run capture-digest -- <slug> <run>   (prints sha256 and the [film] entry to paste)
- [ ] 2. Copy research/parity/references.toml to build/scratch/references.toml, then paste the entry into the working tree's copy
- [ ] 3. mise run parity -- --films <film> --no-build   (renders and scores the candidate)
- [ ] 4. Copy build/scratch/references.toml back over research/parity/references.toml
- [ ] 5. mise run parity -- --films <film> --no-build   (renders and scores the current reference)
- [ ] 6. Compare the two scored lines; promote only in a commit of its own, with the log row
```

Restore from the copy rather than with `git checkout`, which would also discard any edit to the file that was there before step 2. Leave out `--no-render` on the second run. A render covers only the ticks its own capture tagged, so the `_current` tree from step 3 has no frames at the other reference's ticks. `--no-build` is what keeps the binary the same, so the two scores differ only by the reference.
