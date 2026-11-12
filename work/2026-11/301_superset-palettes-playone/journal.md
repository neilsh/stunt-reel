# Journal: a superset archive on `PLAYONE`

## 2026-11-09: the superset with palettes on CTRY and TOD

- **Question**: With `SPRITES.RES` items `0x801E` and `0x8042` added, does `PLAYONE` play a superset archive with the film's palette, and page for page like the film's own archive, once sound is not a variable ([spec](spec.md))?
- **Method**: At `4f5f8e59` (stacked on [PR 347](https://github.com/neilsh/stunt-reel/pull/347)), for `corpus/stuntisl/VAULT/CTRY.FLM` and `TOD.FLM` on `<data root>/builds/unpatched` and `builds/patch3`, under `<data root>/bench/vault-<film>/301/<build>/`:
  - `own/`: `mise run make-all -- --film <FLM> --name 301-<film> --game-root <build> --out own`.
  - `superset-bare.ALL`: `mise run superset-all -- --game <build> --with-palettes`; `superset.ALL`: `mise run stub-sound-samples -- superset-bare.ALL -o superset.ALL --sound-ids-from own/<FILM>.ALL`.
  - Captures `own-1`, `own-2`, `superset`, `superset-bare`: `mise run capture-ref -- --film <FLM> --name 301-<film> --game-root <build> --archive <ALL> --out <arm>`, sound stubbed by default, one after another.
  - `mise run capture-compare` on each pair, in `compare.txt`. The bench name `301-<film>` keeps `make-all` from refusing CTRY's `references.toml` pin to Patch 3.
- **Result**:
  - Both builds' supersets are the same file (`c994fc6d…`, 2,671 chunks, 4,194,236 bytes): Patch 3's `RES\` differs from the unpatched one only in `SPRITES.RES`, `COMMNSND.SMP`, `SNDFX2.SMP`, `MUSIC1.ESS` and `MUSIC2.ESS`, none a shape file.
  - Every chunk of the own `CTRY.ALL` (147) and `TOD.ALL` (50) outside `0xC000`-`0xCFFF` is in the superset byte for byte. Patch 3's `SPRITES.RES` drops item `0x54` (9,398 bytes), so the unpatched `0x55` is its `0x54`; the other 83 items are unchanged. The unpatched and Patch 3 own `CTRY.ALL` (`cb0e26a8…`, `cb58d95b…`) hold the same 147 ids and differ only in `0xC56A`, a sound chunk.
  - The ground draws in its own colours: palettes are byte-equal on every paired tick of every pair.

    | Film, build | Own against own | Own against superset | Superset against bare |
    |---|---|---|---|
    | CTRY, unpatched | 121 of 121 identical | 72 of 112; median 0, 90th percentile 1,649 | 121 of 121 |
    | CTRY, Patch 3 | 121 of 121 | 48 of 101; median 3, 90th percentile 1,186 | 122 of 122 |
    | TOD, unpatched | 128 of 128 | 108 of 115; median 0, 90th percentile 0 | 129 of 129 |

    Each row's two own captures compared alike against the superset (the same counts for `own-1` and `own-2`).
  - The superset's captures keep other ticks: of CTRY unpatched's 121 own pages, 9 (14, 133, 177, …) have no superset page, which kept 12, 134, 178, … instead; TOD loses 13. A capture keeps the ticks it draws, so the superset run drew some frames at other ticks than the own archive's runs (`[Supported Inference]`).
  - Of the 40 differing CTRY unpatched pages, 16 differ across the whole view (columns 0 or 1 to 319 on 15 of them; 736 to 8,580 pixels, the most at tick 804); the other 24 differ by 1 to 104 pixels inside smaller boxes, 8 of them by 1 to 8 pixels at columns 21 to 27, rows 179 to 183. Of TOD's 7, 5 span the view (530 to 1,272 pixels) and 2 differ by 1 and 3 pixels at the same corner.
  - `make-all` on Patch 3 did not return to text mode within 600 s for `TOD.FLM` on two attempts (the log kept, `vault-tod/301/patch3.make-all.log`, is the second's), so TOD has no Patch 3 row.
- **Verdict**: rejected on page content, adopted on palettes. With the palette items, `PLAYONE` draws the right colours, and a missing sound chunk plays like a stubbed one; but on all three rows some superset pages differ where two own captures agreed on every page. The cause is open; candidates include the extra props, the other stock items, and the archive's size (about 33 times CTRY's).
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2, Ruled out, and open questions 4, 5 and 8.

## 2026-11-11: the TOD Patch 3 row

- **Question**: What does the superset do on `TOD.FLM` with Patch 3, the row the 2026-11-09 entry lacked because `make-all` stalled ([#355](https://github.com/neilsh/stunt-reel/issues/355))?
- **Method**: As the 2026-11-09 entry, under `<data root>/bench/vault-tod/301/patch3/`: the own archive is a `make-all` rerun's `TOD.ALL` (md5 `906b04f9…`; `capture-compare` names it `2d6e06aa…`, its id as the capture stages it, sound stubbed), the superset the Patch 3 one stubbed against it (`bdee4cd7…`); captures `own-1`, `own-2`, `superset`; `mise run capture-compare`.
- **Result**: `make-all` did not stall on 4 reruns (24 to 28 s), so the 2026-11-09 stall did not recur in 4 reruns and its cause is unknown. Own against own: 128 of 128 identical. Own against superset: 53 of 108 shared ticks identical, median 1 and 90th percentile 934 pixels differing, palettes equal on 108 of 108. Closer to CTRY Patch 3's row (48 of 101) than to TOD unpatched's (108 of 115).
- **Lives in**: [`linking.md`](../../../research/makeone-exe/linking.md) § 7.2; [`driving.md`](../../../research/makeone-exe/driving.md) item 9.
