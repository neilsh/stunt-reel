# Comparing a candidate reference

Part of the [`improving-render-parity`](SKILL.md) skill.

A new capture becomes a film's reference only through a reviewed commit of `research/parity/references.toml` plus a journal entry. To decide whether to promote one, score the candidate and the current reference with the same binary:

```
- [ ] 1. mise run capture-digest -- <slug> <run>   (prints sha256 and the [film] entry to paste)
- [ ] 2. Copy research/parity/references.toml to build/scratch/references.toml, then paste the entry into the working tree's copy
- [ ] 3. mise run parity -- --films <film> --no-build   (renders and scores the candidate)
- [ ] 4. Copy build/scratch/references.toml back over research/parity/references.toml
- [ ] 5. mise run parity -- --films <film> --no-build   (renders and scores the current reference)
- [ ] 6. Compare the two scored lines; promote only in a commit of its own, with the journal entry
- [ ] 7. The new sha256 makes the film's expected entries read "reference pin changed": re-measure on the promoting commit and update [<film>.expected.<class>] (scores, its sha256 and all_sha256, and crates from git rev-parse HEAD:crates, with crates/ clean and HEAD the commit you rendered)
```

Restore from the copy rather than with `git checkout`, which would also discard any edit to the file that was there before step 2. Leave out `--no-render` on the second run. A render covers only the ticks its own capture tagged, so the `_current` tree from step 3 has no frames at the other reference's ticks. `--no-build` is what keeps the binary the same, so the two scores differ only by the reference.

## Moving a film to another build

The capture tools refuse a build the film's row does not name, and an archive that does not hash to its `all_sha256` ([ADR 0029](../../../docs/adr/0029-references-name-each-films-builds-and-reference.md)), so the row changes first:

```
- [ ] 1. In references.toml, set the row's makeone and playone to the new build (drop reason if it no longer applies)
- [ ] 2. mise run make-all -- --film corpus/stuntisl/VAULT/<FILM>.FLM --game-root <data root>/builds/<build>
- [ ] 3. Set the row's all_sha256 to the one make-all wrote in manifests/all/<slug>.toml
- [ ] 4. mise run capture-ref -- --film corpus/stuntisl/VAULT/<FILM>.FLM --game-root <data root>/builds/<build>
- [ ] 5. Score it as a candidate: the checklist above from step 1, then re-measure the expected tables
```

`CTRY` and `INTRO` are rebuilt from `corpus/stuntisl/VAULT`, whose films are byte-identical to the demo's and have no sibling `.ALL`. From `corpus/stisldem/VAULT` the demo's own `.ALL` is played instead.
