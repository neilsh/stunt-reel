# Journal: recapture noise

## 2026-11-09: what does not make recaptures differ

- **Question**: Does recapture noise come from the Patch 3 build, the window-pass harness, a film's lack of motion, or a label lag that render-tick matching can see?
- **Method**: At `52a2807`, existing captures only. Pixel comparison of each film's reference index pages against its recapture (`<data root>/captures/<slug>/frames` against `<data root>/bench/<slug>/recapture`), and of the unpatched references (`<data root>/backup/pre-300/<slug>/frames`) against `bench/<slug>/recapture-unpatched`. Motion is the number of pixels that differ between consecutive pages of one capture. For BALLOON and BOMB, a fresh `mise run parity` render, and for each paired page the render tick within -6 to +3 whose index plane agrees best with rows 0 to 149.
- **Result**:
  - Unpatched builds diverge as much as Patch 3: BALLOON 24 of 101 paired pages differ unpatched and 39 of 96 on Patch 3; BOMB 110 of 292 and 114 of 280; LOCATION 2 of 745 and 3 of 746.
  - LOCATION moves more than the short films: median motion between consecutive pages 14,472 pixels, against 9,386 (BALLOON), 3,569 (BOMB) and 7,383 (CTRY). Its near-identical replays are not a still scene.
  - Differing pages were mostly dumped at the same emulated frame and `film_tick` in both runs (BALLOON tick 122: emulated frame 1441 in both, 3,348 pixels differ). The large differences span the whole view, rows 0 to 184 and all 320 columns.
  - Render-tick matching could not resolve ticks: identical page pairs had their best offset spread over -6 to +3 (BALLOON 13 at 0 of 57), and best agreements sat between 0.0 and 0.92, so our render is too far from the capture to serve as a tick ruler.
- **Verdict**: control. The build and the scene's motion are ruled out; the harness is ruled out by the next entry. Render-tick matching does not test open question 15 at today's fidelity.
- **Lives in**: [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4, Ruled out and open question 15.

## 2026-11-09: sound samples in the archive make replays differ

- **Question**: Which input makes two captures of one film differ, given that `CTRY.FLM` with the demo's own `.ALL` replayed bit for bit in 2026-10?
- **Method**: At `52a2807`, `mise run capture-ref -- --film <FLM> --name spike305-<variant> --game-root <data root>/builds/<build> --out <data root>/spike/305/<variant>-<run>`, two runs started together (the BALLOON pairs with the second run 0.1 s after the first), pages compared pixel for pixel. Archive chunks compared with a header parse per [`all.ksy`](../../../research/formats/all.ksy). The stubbed `BALLOON.ALL` replaces every chunk payload in `0xC000`-`0xCFFF` with the one byte (`0x04`) the demo's `CTRY.ALL` holds in `0xC302`, keeping ids and order.
- **Result**:

  | Film, archive, build | Differing / paired pages |
  |---|---|
  | CTRY, demo `CTRY.ALL` (`9de1bc1e`), unpatched | 0 / 121 |
  | CTRY, demo `CTRY.ALL`, Patch 3 | 0 / 121 |
  | CTRY, demo `CTRY.ALL`, unpatched, against the 2026-11-08 unpatched recapture | 0 / 121 |
  | CTRY, MAKEONE `CTRY.ALL` (`cb58d95b`), Patch 3 (the 2026-11-08 reference and recapture) | 27 / 111 |
  | BALLOON, MAKEONE `BALLOON.ALL` (`e8d852fa`), Patch 3 | 26 / 102 |
  | BALLOON, the same archive with its sound stubbed, Patch 3 | 0 / 108 |
  | BALLOON stubbed against the BALLOON reference | 66 / 96 |

  - The demo `CTRY.ALL` holds its three sound chunks as stubs (`0xC302` 1 byte, `0xC319` 1,839, `0xC31E` 1); MAKEONE writes 16,978, 17,005 and 12. MAKEONE's `LOCATION.ALL` has no chunk in `0xC300`-`0xC3FF`; each of the other six reference archives has one to sixteen.
  - Stubbing the sound changes the pictures as well as removing the noise: the stubbed capture differs from the with-sound reference on more pages (66 of 96) than two with-sound captures differ from each other.
- **Verdict**: adopted as the cause, `[Bounded Observation]` on CTRY and BALLOON. With its chunks in `0xC000`–`0xCFFF` stubbed, BALLOON's archive replays page for page; with them (the samples `0xC307` and `0xC565`) it diverges. Corrected by the next entry, which lists those chunks: this entry first named `0xC307` alone. How playback changes the picture (frame pacing, the tick a render loop starts from) is not measured.
- **Lives in**: [`method.md`](../../../research/parity/method.md) § 2.2.1; [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4.

## 2026-11-09: what the sound range holds, and CTRY stubbed

- **Question**: Which chunks does the stub replace, and does stubbing them make `CTRY.FLM` from `MAKEONE`'s archive replay page for page?
- **Method**: At `a48b50c`, a header parse of the demo `CTRY.ALL` and the seven stored reference archives (`<data root>/captures/<slug>/archives/`), listing each chunk in `0xC000`-`0xCFFF` with its size and first bytes. Then two `mise run capture-ref -- --film corpus/stuntisl/VAULT/CTRY.FLM --out <data root>/bench/vault-ctry/stubbed-{a,b}` runs with the default stub, the second started 0.1 s after the first, compared with `mise run capture-compare`.
- **Result**:

  | Archive | Chunks in `0xC000`-`0xCFFF` (bytes) |
  |---|---|
  | demo `CTRY.ALL` | `0xC010` FORM (3,561), `0xC302` (1), `0xC319` (1,839), `0xC31E` (1) |
  | `CTRY` | `0xC010` FORM (3,561), `0xC302` (16,978), `0xC319` (17,005), `0xC31E` (12), `0xC56A` (2,204) |
  | `BALLOON` | `0xC307` (8,903), `0xC565` (1,556) |
  | `BOMB` | four FORM, `0xC307`, `0xC319`, `0xC31E`, `0xC548`, `0xC54F` |
  | `INTRO` | one FORM, twenty samples |
  | `LAND` | `0xC107` FORM (2,323), `0xC306` (7,001) |
  | `LOCATION` | six FORM, `0xC447` (6,034) |
  | `TRAINTNL` | `0xC302`, `0xC307`, `0xC537` |

  - Samples begin with `0x00` or `0x02`; the other chunks begin `03 'FORM'` and sit under `0xC0` and `0xC1`, the music `res_index` values of [`linking.md`](../../../research/makeone-exe/linking.md) § 5. The stub replaces both.
  - The stubbed CTRY pair agreed on 121 of 121 pages, palettes 121 of 121 (the with-sound 2026-11-08 pair: 27 of 111 differing).
- **Verdict**: `[Bounded Observation]`. Stubbing the range makes CTRY replay page for page, as it did BALLOON. The previous entry's "one sample" and the notes' "`LOCATION.ALL` has no sample" were wrong: BALLOON's stub covered two samples, and LOCATION holds a sample-like chunk yet replays nearly identically (capture note open question 16).
- **Lives in**: [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) § 4.4 and open questions 16 and 18; [`all.md`](../../../research/formats/all.md) § 3.3; [`method.md`](../../../research/parity/method.md) § 2.2.1.
