# Journal: does the probe's sweep change CTRY's padded-archive pages

## 2026-11-19: the probe's results held at every probed frame; pages differ at the propeller and the viewpoint

- **Question**: do the pages that differ between the own and a padded `CTRY.ALL` differ where the probe `0x240A`'s results (slot `+0x1E`, `+0x20/+0x22`) differ, given that the probe sweeps from the slot's position at the previous drawn frame (`film-load.md` § 5)?
- **Method**: two parts, at `77a9a49`.
  - *Pages, no debugger.* #348's captures `bench/vault-ctry/348/unpatched/own-1` (own archive `cb0e26a8…`) and `padding-1` (`aaa1cbd2…`, 2,529 inert chunks), in the data root, paired by `film_tick` as in `compare.txt`.
    A scratch script masked the HUD clock (rows 176-184, columns 0-47), counted differing pixels in rows 0-184 elsewhere, and drew each differing page with its differences marked; the pages were classified by eye.
  - *Live, DOSBox-X's debugger.* `mise run debug-x -- --plan tools/dosbox-x/plans/carried-state.toml --build unpatched` on `CTRY.FLM` (`corpus/stuntisl/VAULT`), staged twice in `bench/vault-ctry/779/` with the own and #348's padded archive beside it, each with its sound samples stubbed as captures play them (`stub-sound-samples`; `975553da…` and `1cf18af1…`).
    The break `0x1492`, just before `0x1463` calls the probe, has `SI` = the slot; each hit read the film clock `DS:0x4896` and the slot's bytes `+0x00..+0x2F`.
    Runs in `bench/vault-ctry/779/runs/{own,padding}/CTRY/`.
- **Result**:
  - *Pages.* Of 111 shared ticks, 42 pages are identical and 17 more differ only in the HUD clock; 52 differ elsewhere.
    28 differ at the aircraft's nose, its propeller, and at the propeller in its shadow (100 to 793, up to 122 pixels); 23 differ along edges across the whole view, terrain, horizon and objects shifted by a pixel or so, the viewpoint (67, 265, 287, 309, 320, 507, 551, 804, 815, 903 to 1311; 131 to 8,572 pixels); 1 (837) by 14 pixels near an object's tip.
    No page differs at the shadow alone; shadow pixels differ only at the propeller's shadow or on viewpoint pages.
    On 27 of the 52 the HUD clock is equal in both arms: 15 viewpoint pages, 11 propeller pages and 837.
  - *Live.* One slot (`DS:0x393A`) passed `0x1463`'s filter on each hit: 183 hits from tick 52 to 849 (own) and 208 from tick 0 to 850 (padding); no hit after tick 850 in either arm.
    Its `+0x24..+0x2F` equalled the previous hit's `+0x04..+0x0F` on 141 of 182 consecutive pairs (own) and 164 of 207 (padding); every pair that did not was 4 to 24 ticks apart, where hits 2 to 4 ticks apart were the norm, so a drawn frame went unhit between them.
    `+0x1C`, `+0x1E`, `+0x20` and `+0x22` read 0, `0x033C`, 0 and 0 on every hit in both arms but the padding's first, at tick 0, which read 0 in all four before any probe had run: one ground leaf's plane, no box code, no code-8 box top.
    These are DOSBox-X's frames, not the captures' (hits mostly 3 ticks apart, up to 24), so they cannot be paired with a capture's pages; the results are constant, so pairing would not change the answer.
- **Verdict**: control; the hypothesis is rejected for these pages.
  The probe's results, the only inputs the sweep changes, stayed the same at every probed frame of both runs (own: ticks 52 to 849; padded: 5 to 850, its tick-0 hit before any probe excluded), and no differing page differs at the shadow alone, so the sweep does not explain CTRY's padded-archive pages.
  The propeller pages fit the angle bank's word `0x14`, the previous drawn frame's var 10 ([`angle-bank.md`](../../../research/playone-exe/angle-bank.md)), which is per-frame state too, if the biplane's propeller is a stock `ROTZ` on operand `0x14` (not checked).
  Why the viewpoint differs on 23 pages, 15 of them at an equal HUD clock, is open.
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5 and its Ruled out and Open questions; [`sod-vm-frame.md`](../../../research/playone-exe/sod-vm-frame.md) § 9.1.
