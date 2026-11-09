# Journal: why a superset archive's pages differ on `PLAYONE`

## 2026-11-09: no differing page is a timing shift

- **Question**: Are the superset's differing pages the own archive's pages drawn at a neighbouring film tick ([spec](spec.md), stage 1)?
- **Method**: `mise run capture-compare -- own-1 superset --shift 2` on #301's captures in `<data root>/bench/vault-ctry/301/unpatched/` and `vault-tod/301/unpatched/` (A is `own-1`). `--shift N` looks for each A page with no identical B page at its tick among B's pages at ticks `t-2`..`t+2`; only a pixel-identical page counts. For each tick only A holds, a one-off script also counted the pixels differing from B's nearest page.
- **Result**:

  | Film | A pages with no identical B page | Differing paired pages matched | Ticks only in A matched |
  |---|---|---|---|
  | CTRY | 49 | 0 of 40 | 1 of 9 (859 at 860) |
  | TOD | 20 | 0 of 7 | 2 of 13 (871 at 870, 1222 at 1223) |

  - No differing paired page, whole-view or small, has a pixel-identical B page within 2 ticks: every one of CTRY's 16 whole-view pages (736 to 8,580 pixels) and TOD's 5 (530 to 1,272) differs at its own tick and at the neighbouring ones.
  - The ticks the two captures keep differ by one or two (CTRY 14, 133, 177 against 12, 134, 178; TOD 100, 178, 211 against 101, 177, 210), but the pages at those ticks also differ: of the 22 A-only ticks, 3 match exactly, 2 by 6 and 3 pixels, the other 17 by 441 to 2,175 pixels against B's nearest page.
  - The small boxes stay as #301 found them (CTRY 24 pages of 1 to 104 pixels, 8 at columns 21 to 27, rows 179 to 183; TOD 2).
- **Verdict**: rejected: the superset's differing pages are not the own archive's pages drawn at another tick. What is drawn differs, and so do some of the ticks drawn. Stage 2 proceeds as planned.
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and Ruled out.

## 2026-11-09: inert padding alone changes CTRY's pages

- **Question**: Does `PLAYONE` play an own `CTRY.ALL` padded with inert chunks in an unused resource index, and does it draw it like the unpadded archive ([spec](spec.md), stage 2)?
- **Method**: `mise run make-all -- --film corpus/stuntisl/VAULT/CTRY.FLM --name 348-ctry --game-root <data root>/builds/unpatched --out own` in `<data root>/bench/vault-ctry/348/unpatched/` rebuilt the own archive (`cb0e26a8…`, byte-equal to #301's; TOD's `48ed440d…` also is). `mise run pad-all -- own/CTRY.ALL -o probe.ALL --inert 2529 4092524` added 2,529 zero-filled chunks, ids `0xF001` upward skipping item 0, 4,092,524 bytes in all: the count and bytes `pad-all --add-from superset-bare.ALL` adds to the same archive, so the probe is also stage 3's arm (b) for CTRY. One `capture-ref --archive probe.ALL --out probe` (sound stubbed by default), compared with #301's `own-1` by `capture-compare --shift 2` (`probe-compare.txt`).
- **Result**:
  - `PLAYONE` played it: 122 pages to tick 1,333, palettes byte-equal on all 111 paired ticks.
  - The pages differ more than the superset's did: 42 of 111 identical (superset 72 of 112), median 6 and 90th percentile 1,360 differing pixels. Counting a page whose differing pixels span at least 290 columns as whole-view, 22 are (276 to 8,680 pixels) and 47 are small (1 to 134 pixels); the superset's were 16 and 24.
  - None is a shift: 0 of the 69 differing pages and 0 of the 10 ticks only `own-1` keeps match a probe page within 2 ticks. The ticks kept differ again by one or two (14, 156, 342 against 12, 155, 343).
  - Against #301's superset capture, the probe has 45 of 110 pages identical.
- **Verdict**: adopted: an archive grown by inert chunks no game file uses draws differently from the own archive, so the extra props are not needed for the difference. One capture, so how much a padded archive varies between runs is not measured; stage 3 compares the props against padding of the same size.
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2 and open questions 5 and 8.

## 2026-11-09: padding of the props' size changes pages more than the props

- **Question**: On CTRY and TOD, does the own archive plus the superset's extra shape chunks draw like the own archive plus inert padding of the same chunk count and bytes ([spec](spec.md), stage 3)?
- **Method**: In `<data root>/bench/vault-<film>/348/unpatched/`, unpatched build, the own archives of the stage 2 entry:
  - `props.ALL`: `mise run pad-all -- own/<FILM>.ALL -o props.ALL --add-from ../../301/unpatched/superset-bare.ALL`: CTRY 2,529 chunks, 4,092,524 bytes; TOD 2,623 chunks, 4,138,716 bytes.
  - `padding.ALL`: `pad-all --inert` with those counts and bytes (CTRY's is the stage 2 probe's file, `aaa1cbd2…`).
  - Captures `own-1`, `props-1`, `padding-1`, in that order per film, each `capture-ref --film <FLM> --name 348-<film> --game-root <build> --archive <ALL> --out <arm>`, sound stubbed by default; `capture-compare --shift 2` on each pair, in `compare.txt`. A whole-view page is one whose differing pixels span at least 290 columns.
- **Result**:
  - `props.ALL` stubbed as captures stage it (`stub-sound-samples`, hashes in `props.txt`) is byte-identical to #301's `superset.ALL` stubbed (CTRY `e8110ffe…`, TOD `bdee4cd7…`; `capture-compare` prints the unstubbed inputs' hashes): the own archive plus the superset's extra chunks is the superset plus the own sound ids. So arm (a) repeats #301's superset arm.
  - Each archive captured twice replays bit for bit: `own-1` against #301's `own-1`, `props-1` against #301's `superset`, and (CTRY) `padding-1` against the stage 2 `probe` are identical on every page and palette.

    | Film, pair | Identical pages | Median, 90th percentile pixels | Whole-view, small differing pages | Pages within 2 ticks |
    |---|---|---|---|---|
    | CTRY, own against props | 72 of 112 | 0, 1,649 | 16 (736–8,580), 24 (1–104) | 0 of 40 |
    | CTRY, own against padding | 42 of 111 | 6, 1,360 | 22 (276–8,680), 47 (1–134) | 0 of 69 |
    | CTRY, props against padding | 45 of 110 | 6, 1,772 | 27, 38 | 0 of 65 |
    | TOD, own against props | 108 of 115 | 0, 0 | 5 (530–1,272), 2 (1–3) | 0 of 7 |
    | TOD, own against padding | 51 of 109 | 1, 939 | 33 (387–1,452), 25 (1–11) | 0 of 58 |
    | TOD, props against padding | 53 of 109 | 1, 803 | 30, 26 | 0 of 56 |

    Palettes are byte-equal on every paired tick of every pair.
  - The ticks kept differ by one or two in every cross-archive pair (TOD own against padding: 19 ticks only in `own-1`, 20 only in `padding-1`), and of those ticks' pages at most 3 per pair match within 2 ticks.
- **Verdict**: the extra props as a necessary cause: rejected. Inert chunks that no film references, of the same count and bytes, change more pages than the props on both films, and draw differently from the props too. What `PLAYONE` draws at a film tick depends on the archive beyond the chunks the film uses; every archive captured twice repeated bit for bit (TOD's padded archive was captured once). Total bytes and chunk count alone do not decide it, since props and padding share both and differ; ids, chunk sizes or content remain open.
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2, Ruled out, and open questions 5 and 8.
