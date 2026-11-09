# Spec: captures play with the archive's sound samples stubbed

Issue [#305](https://github.com/neilsh/stunt-reel/issues/305). Design agreed 2026-11-09.

## Intent

**Goal.** Make recapture noise zero on the reference films, so the regression verdict (`--compare-test`) can treat any nonzero Δ as the render's, and the headline score of a film no longer moves when it is recaptured.

**Why this way.** Two captures of `BALLOON.FLM` from `MAKEONE`'s archive differ on 26 of 102 pages; with its one sound sample stubbed they agree on 108 of 108, and the demo's `CTRY.ALL`, which ships its samples stubbed, replays identically on both builds ([journal](journal.md#2026-11-09-sound-samples-in-the-archive-make-replays-differ); [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4). Removing the cause replaces the consensus capture proposed on the issue: no N-fold runs, no majority pages, no change to ADR 0028's one capture per film.

**Accepted cost.** A stubbed capture is a different recording of the film, not a cleaner copy: the stubbed `BALLOON` capture differs from the with-sound reference on 66 of 96 pages. All seven references are recaptured and repinned once, and their headline scores move.

**Out of scope.** Whether a page shows its labelled tick (open question 15 of the capture note) and whether `COUNT.FLM` varies for the same reason (open question 5). Both stay open.

## 1. Components

### 1.1 `stub_sound`

`stub_sound(archive: bytes) -> bytes` in [`python/stunt_reel/all_archive.py`](../../../python/stunt_reel/all_archive.py):

- Parses the header per [`all.ksy`](../../../research/formats/all.ksy): `u16` count, `u16` ids, `count + 1` `u32` offsets ending in the EOF sentinel.
- Replaces the payload of every chunk whose id is in `0xC000`–`0xCFFF` (sound effects, [`all.md`](../../../research/formats/all.md) § 3.3) with the single byte `0x04`, the stub the demo's `CTRY.ALL` holds in `0xC302`.
- Keeps ids and their order; every other payload byte-identical; rebuilds the offsets from the new payload lengths, with the header length unchanged.
- An archive with no sound chunk comes back byte-identical.
- A header that runs past the data, or offsets that decrease or pass the end, raise `ArchiveError` naming the problem.
- Pure: bytes in, bytes out.

### 1.2 Staging

`staging.stage_play(film, archive, engine_root=None, *, sound: Sound = "stubbed")` in [`python/stunt_reel/tac/staging.py`](../../../python/stunt_reel/tac/staging.py), where `Sound = Literal["stubbed", "kept"]`. With `"stubbed"` it writes `stub_sound(archive.read_bytes())` as the mount's `<film stem>.ALL`; with `"kept"` it copies the archive as today. `capture_run.staged_play` and `staged_film` take and pass `sound`, so frame capture, video capture and the batch survey share the one path.

### 1.3 Options and metadata

- `capture-ref` and `capture-video` take `--sound stubbed|kept`, default `stubbed`; the batch survey uses the default.
- A capture's `meta.json` gains `"sound": "stubbed"` or `"kept"`. A capture without the field played with sound (every capture before this change).
- `all_sha256` stays the hash of the archive as resolved (the row's pin), not of the staged stub, so ADR 0037's resolution and `parity`'s check of the capture's archive against the row are unchanged. The played archive is a function of the pin and `sound`.
- `references.toml` gains no field: the row's `sha256` pins the capture, and the capture's meta records how it played.

### 1.4 Decision record

ADR 0043, "Captures play with the archive's sound samples stubbed": the evidence (§ 4.4 of the capture note), the picture change, the default, and `--sound kept` for a with-sound recording. ADR 0028 and ADR 0037 stand unchanged.

## 2. Recapture and verification

1. **Determinism.** For each of the seven reference films, two `capture-ref` runs with the default sound setting, the second started 0.1 s after the first, into `<data root>/bench/<slug>/recapture` and a second `--out` beside it; pages compared pixel for pixel. Expected: 0 differing pages. A film that still differs has its count recorded in `method.md` § 2.2.1 and does not block the others.
2. **Promote.** The first run of each pair replaces the stored capture (ADR 0028 swap); `mise run capture-digest -- <slug>` prints each row's new `sha256`. `all_sha256` does not change.
3. **Re-measure.** `mise run parity` on all seven films; each row's `expected.gpu` table is re-measured, and the journal records each film's headline before and after.
4. **`noise_sigma`.** Removed from `vault-location`'s row. With identical recaptures the verdict's rule without a σ, that only a Δ of exactly 0 is within noise, is the right one.
5. **Metric bench.** `parity-bench run --recapture` gets σ 0 on these films; `_entry` in [`bench/run.py`](../../../python/stunt_reel/bench/run.py) already calls a fault detected then when its mean falls at all. The 0.002 adoption floor stays as policy. No bench code changes.

## 3. Testing

All offline, on synthetic fixtures ([`tests/fixtures/README.md`](../../../tests/fixtures/README.md)):

- `tests/test_all_archive.py`: an in-memory archive of two non-sound chunks around two `0xC3xx` chunks, one of them empty, gives the same ids in order, `b"\x04"` for each sound payload, the non-sound payloads byte-identical, and offsets and sentinel that re-parse; an archive with no sound chunk comes back unchanged; a truncated header and a decreasing offset raise `ArchiveError`; `link_film.all` and `synthetic_minimal.all` keep their non-sound chunks.
- `tests/test_tac_staging.py`: the staged `.ALL` equals `stub_sound(source)` with `"stubbed"` and the source byte for byte with `"kept"`.
- A `capture_run` test: `meta.json` carries `"sound"`, and `all_sha256` is the unstubbed archive's hash.

## 4. Records

- [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4: captures stub the samples by default, with the seven films' determinism results.
- [`method.md`](../../../research/parity/method.md) § 2.2.1 rewritten with the stubbed recapture table; § 1 step 5's caveat on σ as a lower bound shrinks to the films that still differ, if any.
- [`all.md`](../../../research/formats/all.md): the demo's `CTRY.ALL` ships its sound chunks as stubs.
- [`GLOSSARY.md`](../../../GLOSSARY.md): "stubbed sound", if no existing term fits.
- Journal entries in this folder; the finishing PR writes this README's `outcome` and closes #305.

## 5. Shipping

One PR from `claude/reduce-capture-noise-8aa03a`, on top of the findings commit: code and tests first, then the recapture, repins and notes. It changes rendered-against references, so it carries the before-and-after capture-beside-render picture ([Evidence for a rendering PR](../../../.agents/skills/improving-render-parity/pr-evidence.md)).

## Done when

- `mise run check` passes with the new tests.
- All seven reference films are recaptured with stubbed sound, each pair's differing-page count is recorded, and rows carry the new `sha256` and `expected.gpu`.
- `noise_sigma` is gone from `references.toml`, or kept only on a film whose stubbed pair still differs, with the reason in § 2.2.1.
- ADR 0043 and the notes in § 4 are committed.
