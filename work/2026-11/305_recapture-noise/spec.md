# Spec: captures play with the archive's sound samples stubbed

Issue [#305](https://github.com/neilsh/stunt-reel/issues/305). Design agreed 2026-11-09, then grilled (decisions Q1 to Q15, below).

## Intent

**Goal.** Make recapture noise zero on the reference films, so the regression verdict (`--compare-test`) can treat any nonzero Δ as the render's, and the headline score of a film no longer moves when it is recaptured.

**Why this way.** Two captures of `BALLOON.FLM` from `MAKEONE`'s archive differ on 26 of 102 pages; with its one sound sample stubbed they agree on 108 of 108, and the demo's `CTRY.ALL`, which ships its samples stubbed, replays identically on both builds ([journal](journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ); [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4). Removing the cause replaces the consensus capture proposed on the issue: no N-fold runs, no majority pages, no change to ADR 0028's one capture per film.

**Accepted cost.** A stubbed capture is a different recording of the film, not a cleaner copy: the stubbed `BALLOON` capture differs from the with-sound reference on 66 of 96 pages. All seven references are recaptured and repinned once, and their headline scores move. The move is recorded, not gated: a reference is chosen for being repeatable, not for scoring well (Q7).

**Also serves #301.** Issue [#301](https://github.com/neilsh/stunt-reel/issues/301) plays every arm of its superset-palette experiment with the samples stubbed, and builds on the archive tool of § 1.2 (Q1).

**Out of scope.** Whether a page shows its labelled tick (open question 15 of the capture note), whether `COUNT.FLM` varies for the same reason (open question 5), and recapturing the batch survey's existing captures (Q6).

## 1. Components

All in Python; nothing changes in `crates/stunt-core` or `stuntreel link`, since renders never read sound (Q13).

### 1.1 `stub_sound_samples`

`stub_sound_samples(archive: bytes, *, sound_ids_from: bytes | None = None) -> bytes` in [`python/stunt_reel/all_archive.py`](../../../python/stunt_reel/all_archive.py):

- Parses the header per [`all.ksy`](../../../research/formats/all.ksy): `u16` count, `u16` ids, `count + 1` `u32` offsets ending in the EOF sentinel.
- Replaces the payload of every chunk whose id is in `0xC000`–`0xCFFF` (sound effects, [`all.md`](../../../research/formats/all.md) § 3.3) with the single byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302` (Q3). No other chunk changes, including the ones `MAKEONE` adds that the demo lacks (Q4).
- With `sound_ids_from`, adds a `0x04` chunk for each sound id of that archive that the input lacks (Q9). Sound ids of the input that `sound_ids_from` lacks stay, stubbed.
- Writes ids in ascending order, as every corpus archive keeps them ([`all.md`](../../../research/formats/all.md) § 2), and rebuilds the header and offsets from the new payloads. Without `sound_ids_from` the id list and its order are unchanged.
- An archive with no sound chunk, and no `sound_ids_from`, comes back byte-identical.
- A header that runs past the data, or offsets that decrease or pass the end, raise `ArchiveError` naming the problem.
- Pure: bytes in, bytes out.

**What the stub is known to do.** PLAYONE plays and replays identically a film whose samples are this byte, on `BALLOON.FLM` (stubbed here) and the demo's `CTRY.FLM` (stubbed as shipped). What it does with the byte (skips the sample, or plays a click) is not known; a zero-length payload or a minimal well-formed sample was not tried and is not used (Q3).

### 1.2 `mise run stub-sound-samples`

`mise run stub-sound-samples -- IN.ALL -o OUT.ALL [--sound-ids-from OWN.ALL]` writes `stub_sound_samples` of IN to OUT (Q1, Q9). `-o` is required; an OUT that is IN or already exists is refused (Q10). It prints the SHA-256 of IN and OUT, so a journal entry can quote both.

### 1.3 `mise run capture-compare`

`mise run capture-compare -- A B`, taken over from #301 (`c52dae5d` on `claude/grill-with-docs-301-74ba5b`), re-committed on this branch ([AGENTS.md](../../../AGENTS.md) § Committing rule 9) with its tests (Q15). It pairs two captures' pages by exact `film_tick` and reports identical pages, median and p90 differing pixels, and equal palettes. #301 drops its copy when it rebases.

### 1.4 Staging

`staging.stage_play(film, archive, engine_root=None, *, sound_samples: SoundSamples = "stubbed")` in [`python/stunt_reel/tac/staging.py`](../../../python/stunt_reel/tac/staging.py), where `SoundSamples = Literal["stubbed", "kept"]`. With `"stubbed"` it writes `stub_sound_samples(archive.read_bytes())` as the mount's `<film stem>.ALL`; with `"kept"` it copies the archive as today. `capture_run.staged_play` and `staged_film` take and pass `sound_samples`, so frame capture, video capture and the batch survey share the one path.

### 1.5 Options and metadata

- `capture-ref` and `capture-video` take `--sound-samples stubbed|kept`, default `stubbed` (Q5); the batch survey uses the default. The default holds from PR 1, before the references are recaptured: a recapture in between hashes differently from its row's `sha256`, which `parity` already refuses (Q12).
- A capture's `meta.json` gains `"sound_samples": "stubbed"` or `"kept"`. A capture without the field played with its samples (every capture before this change, Q6).
- `all_sha256` stays the hash of the archive as resolved (the row's pin), not of the staged stub, so ADR 0037's resolution and `parity`'s check of the capture's archive against the row are unchanged. The played archive is a function of the pin and `sound_samples`.
- `references.toml` gains no field: the row's `sha256` pins the capture, and the capture's meta records how it played.

### 1.6 Decision record

ADR 0043, "Captures play with the archive's sound samples stubbed": the evidence (§ 4.4 of the capture note), the picture change, the default, and `--sound-samples kept` for a with-sound recording. ADR 0028 and ADR 0037 stand unchanged.

## 2. Recapture and verification (PR 2)

1. **Back up.** The seven current reference captures move to `<data root>/backup/pre-305/<slug>/frames` before any swap, as `pre-300` did (Q8).
2. **Determinism.** For each film, two `capture-ref` runs with the default, the second started 0.1 s after the first, into `<data root>/bench/<slug>/recapture` and a second `--out` beside it; `capture-compare` on the pair. Expected: 0 differing pages. A film that still differs has its count recorded in `method.md` § 2.2.1 and does not block the others.
3. **Promote.** The first run of each pair replaces the stored capture (ADR 0028 swap); `mise run capture-digest -- <slug>` prints each row's new `sha256`. `all_sha256` does not change.
4. **Re-measure.** `mise run parity` on all seven films; each row's `expected.gpu` table is re-measured, and the journal records each film's headline before and after (Q7).
5. **`noise_sigma`.** Removed from `vault-location`'s row. With identical recaptures the verdict's rule without a σ, that only a Δ of exactly 0 is within noise, is the right one.
6. **Metric bench.** `parity-bench run --recapture` gets σ 0 on these films; `_entry` in [`bench/run.py`](../../../python/stunt_reel/bench/run.py) already calls a fault detected then when its mean falls at all. The 0.002 adoption floor stays as policy. No bench code changes.

## 3. Testing

All offline, on synthetic fixtures ([`tests/fixtures/README.md`](../../../tests/fixtures/README.md)):

- `tests/test_all_archive.py`, on an in-memory archive of two non-sound chunks around two `0xC3xx` chunks, one of them empty:
  - the same ids in order, `b"\x04"` for each sound payload, the non-sound payloads byte-identical, and offsets and sentinel that re-parse;
  - an archive with no sound chunk comes back unchanged;
  - `sound_ids_from` adds the missing sound ids as `0x04` chunks in ascending id order, keeps the input's own, and on an input that already holds them gives the same bytes as without it;
  - a truncated header and a decreasing offset raise `ArchiveError`;
  - `link_film.all` and `synthetic_minimal.all` keep their non-sound chunks.
- The `stub-sound-samples` script: refuses a missing `-o`, an existing OUT and OUT equal to IN; prints both hashes.
- `capture-compare`: #301's tests, carried over.
- `tests/test_tac_staging.py`: the staged `.ALL` equals `stub_sound_samples(source)` with `"stubbed"` and the source byte for byte with `"kept"`.
- A `capture_run` test: `meta.json` carries `"sound_samples"`, and `all_sha256` is the unstubbed archive's hash.

## 4. Records

- [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4: captures stub the samples by default; the stub's byte and what is and is not known about it (§ 1.1), which #301 cites; in PR 2, the seven films' determinism results.
- [`method.md`](../../../research/parity/method.md) § 2.2.1 rewritten in PR 2 with the stubbed recapture table; § 1 step 5's caveat on σ as a lower bound shrinks to the films that still differ, if any.
- [`all.md`](../../../research/formats/all.md) § 3.3: the demo's `CTRY.ALL` ships its sound chunks as one-byte to 1,839-byte stubs.
- [`GLOSSARY.md`](../../../GLOSSARY.md): "stubbed sound samples", if no existing term fits.
- [`docs/development.md`](../../../docs/development.md) or the task list: `stub-sound-samples` and `capture-compare`.
- Journal entries in this folder; the finishing PR writes this README's `outcome` and closes #305.

## 5. Shipping

A `gh stack` from `claude/reduce-capture-noise-8aa03a` ([AGENTS.md](../../../AGENTS.md) § Committing rule 8, Q2):

- **PR 1**: the findings commit `1d71ab35`, this spec, §§ 1.1 to 1.6 with their tests, and the § 4 note changes that do not depend on the recapture (Q11). #301 rebases onto it and is told its link (Q14).
- **PR 2**: § 2 and the rest of § 4. It changes the references renders are scored against, so it carries the before-and-after capture-beside-render picture ([Evidence for a rendering PR](../../../.agents/skills/improving-render-parity/pr-evidence.md)).

## Done when

- `mise run check` passes with the new tests (PR 1).
- `mise run stub-sound-samples` and `mise run capture-compare` exist, and `capture-ref` and `capture-video` stub by default (PR 1).
- All seven reference films are recaptured with stubbed samples, each pair's differing-page count is recorded, and rows carry the new `sha256` and `expected.gpu` (PR 2).
- `noise_sigma` is gone from `references.toml`, or kept only on a film whose stubbed pair still differs, with the reason in § 2.2.1 (PR 2).
- ADR 0043 and the notes in § 4 are committed.

## Decisions

| # | Decision |
|---|---|
| Q1 | This branch ships `stub-sound-samples`, with `--sound-ids-from`, for #301 too. |
| Q2 | Two stacked PRs: tools and staging, then recapture. |
| Q3 | The stub is the demo's single byte `0x04`; its limits are stated in the note. |
| Q4 | Only ids `0xC000`–`0xCFFF` are stubbed. |
| Q5 | `capture-video` stubs by default as well. |
| Q6 | Existing survey captures stay; no field means `kept`. |
| Q7 | Stubbed references are adopted whatever their headline move; the move is recorded. |
| Q8 | Outgoing references move to `backup/pre-305/`. |
| Q9 | `--sound-ids-from` adds the missing sound ids as stubs, ids ascending. |
| Q10 | `-o` required; an existing OUT or OUT equal to IN refused; both hashes printed. |
| Q11 | PR 1 carries the findings and spec commits. |
| Q12 | The default is `stubbed` from PR 1. |
| Q13 | Python only. |
| Q14 | #301 gets the branch and interface now, the PR link when PR 1 opens. |
| Q15 | PR 1 adopts #301's `capture-compare`. |
| | Every name says it is sound samples that are stubbed. |
