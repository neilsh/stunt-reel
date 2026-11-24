# Journal: what moves the viewpoint on CTRY's padded-archive pages

## 2026-11-24: the film step reads the clock before the render, and the HUD reads it after

- **Question**: does the per-frame call compose the scene and draw the HUD clock from one reading of the film clock (`film-load.md` open question 1)?
- **Method**: static, `mise run re-tool -- disasm 0x49F9 0x4A60`, `disasm 0x3A72 0x3B40`, `disasm 0x136F 0x1463`, `disasm 0x3E63 0x3EE0` and `xref 0x4896 --code-end 0xFFFF`, unpatched `PLAYONE.EXE`, at `288d3da8`.
  On review, since `xref` finds only direct operands and the film step reads the clock as `[bx+0Eh]`: `disasm 0x0 0x8000` and a one-off recursive descent over its direct near calls and jumps (not committed) from the calls between `0x4A07` and `0x4A38` (`0x3A72`, `0x4FCD`, `0x13EA`, `0x1151`, `0x11F8`, `0x0EE9`; 3,806 instructions), and from `0x62E7`, `0x33C3` and `0x31C0`, listing every `0x4896` operand and every `+0Eh` displacement reached, each read in its context.
- **Result**:
  - `0x49F9` calls the film step `0x3A72` at `0x4A07` with `BX = 0x4888`; the step reads the clock `[bx+0Eh]` (`DS:0x4896`) at `0x3A88`, moves the slice to the one holding it and stores the fraction `0x22E0` (`0x3AE0`, `0x3AF7`).
  - The slot pass `0x136F` (`0x1381`) and the interpolation `0x3E6C` (`0x3E76`) read `0x22E0`, not the clock.
  - After the render step `0x0EE9` (`0x4A35`), `0x4A38` reads `DS:0x4896` again and passes it in `AX` to `0x33C3`, the HUD clock's draw.
  - `xref 0x4896` finds the direct reads `0x3B37` (the step's zero-length-slice path), `0x3FF0`, `0x42CA`, `0x42DA`, `0x42E9`, the INT 8 path's `adc` at `0x43E6`, `0x4A38` and the speed keys at `0x4A77..0x4AC7`.
  - The descent adds three reads of the clock as `[reg+0Eh]` with the register holding `0x4888` between `0x4A07` and `0x4A38`: `0x1370` in the slot pass `0x136F` (`SI = 0x4888` from `0x4A14`), which stores the clock less `+0x12` at `0x22DC` and the clock at `+0x12`; `0x1DCA` in the angle bank's fill `0x1D96` (`angle-bank.md`), reached through `0x0EE9` and `0x0F77`; and `0x40C5` in `0x40AC` (`BX = 0x4888`), which stores a clock delta byte through `[0x4888]` and is reached from `0x141F` when the deferred-call queue `0x2366` is not empty and byte `0x2276` is set, and from the step's `0x3BB0`.
  - The other `+0Eh` reads it reaches (`0x152F`, `0x1545`, `0x1684`, `0x1859`, `0x185F`, `0x1A2A`, `0x1A66`, `0x1AAD`, `0x1BB1`, `0x1BB4`) sit beside `+04h`, `+08h` and `+0Ch` reads of a 32-bit position or a sort record, not on `0x4888`; the step's own `0x3AD8`, `0x3B48`, `0x3B5E`, `0x3BB4` and `0x3BD5` write the clock on its end and zero-length-slice paths.
  - `0x62E7`, `0x33C3` and `0x31C0` reach no `+0Eh` or `0x4896` read directly.
  - Not followed: the 78 far calls (most into segment `0x0824`), word-table calls (`[0x225A]`, `[0x2244]`, `[bx+0C08h]` and others) and register calls the descent met.
- **Verdict**: control (static reading).
  A drawn frame's slots, the camera's object among them, are placed by the fraction from the step's reading; the slot pass's own reading feeds only `0x22DC` and `+0x12`; the angle bank's word `0x10` is a later reading inside the render; and the HUD shows the clock after the render.
  The HUD and the slots differ by the timer interrupts that fall during the step, the slot pass and the render; a reader through the unfollowed calls is not excluded.
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5.

## 2026-11-24: HUD minus scene tick varies from frame to frame under DOSBox-X

- **Question**: does the gap between the scene's tick and the HUD's vary per drawn frame, and is the camera a function of the scene's tick alone?
- **Method**: `mise run debug-x -- --plan tools/dosbox-x/plans/view-clock.toml --film <stage>/CTRY.FLM --build unpatched` at `288d3da8`, once with the own `CTRY.ALL` and once with #348's padded one, rebuilt as #348 and #779 did and with the same hashes (`make-all --game-root builds/unpatched`: `cb0e26a8…`; `pad-all --inert 2529 4092524`: `aaa1cbd2…`; `stub-sound-samples`: `975553da…` and `1cf18af1…`), each staged with `corpus/stuntisl/VAULT/CTRY.FLM` in `<data root>/scratch/826/stage/`.
  Per drawn frame the plan records the clock at `0x4A07` (the scene's tick), the camera's 24 bytes at `0x1251` with `0x22E0`, `AX` at `0x4A3B` (the HUD's tick) and the clock at `0x4A4F`.
  [`live_lag.py`](live_lag.py) pairs the hits into frames ([`live-own.csv`](live-own.csv), [`live-padding.csv`](live-padding.csv), with the camera's 24 bytes and `0x22E0` as hex per frame; printed output, with each run's SHA-256, in [`live-lag.txt`](live-lag.txt)).
  The runs are `<data root>/scratch/826/runs/<own | padding>/CTRY/view-clock-unpatched-*.jsonl` (not committed).
- **Result**:
  - Own: 396 frames, scene ticks 53 to 1334; HUD minus scene tick 2 on 112 frames, 3 on 212, 4 on 72; the clock at `0x4A4F` equals the HUD's tick on every frame; scenes 2 to 5 ticks apart (48, 219, 112, 16 frames).
  - Padded: 418 frames, scene ticks 0 to 1335; HUD minus scene tick 1 on 1 frame, 2 on 139, 3 on 196, 4 on 79, 5 on 3; the clock at `0x4A4F` equals the HUD's tick on every frame.
  - The camera record (24 bytes at the camera object, eye and angles) is equal in both runs at all 195 scene ticks both drew, about half of each run's frames; the `camera` columns of the two CSVs give it again.
  - At the 201 HUD ticks both runs drew, the scene's tick is equal on 145 and one less in the own run on 56.
- **Verdict**: control.
  In these two runs the camera's eye and angles carried no state between frames at the ticks both drew; other view state was not compared.
  The scene's tick trails the HUD's by an amount that varies per frame, so pages with one HUD clock can show different ticks.
  These are DOSBox-X's frames, drawn 2 to 5 ticks apart where the captures' sit 0 to 3 ticks behind their tags (`capture-dosbox-automation.md` § 2), so the figures bound DOSBox-X's lag and do not pair with the captures' pages.
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5.

## 2026-11-24: on 12 viewpoint pages the two arms' scenes are one tick apart

- **Question**: on the 23 CTRY pages where #348's own and padded captures differ along edges across the whole view, does each arm's page match the render one tick from the other's, and can the score tell a one-tick step apart?
- **Method**: two fresh unpatched captures, `capture-ref --film corpus/stuntisl/VAULT/CTRY.FLM --game-root builds/unpatched --archive <own | padded>.ALL --out <data root>/scratch/826/cap/<own | padding>-1` (sound stubbed), at `288d3da8`; `capture-compare` gives 111 shared ticks and 42 identical pages, #348's figures.
  One render of `main` (`mise run parity -- --films ctry`, crates tree `d897adc`, RTX 4070, scored CTRY 0.9385 on its reference), relabelled with `parity_probe.py retime --reference <capture> --by N --allow-missing` for N in -3..+2 and scored with `stuntreel parity --reference <capture> --waive-archive-conflict` (the captures played the unpatched own archive, the render the reference's).
  [`page_offsets.py`](page_offsets.py) masks the HUD clock (rows 176 to 184, columns 0 to 47) as #779 did, lists the pages that differ elsewhere, and for each takes the *shift*: the k in -2..+2 for which the padded arm's index-agreement curve at offset n + k best matches the own arm's at n (mean absolute difference over the offsets both cover), decided when the next-best k's error is at least 3 times the best's ([`page-offsets.csv`](page-offsets.csv), printed in [`page-offsets.txt`](page-offsets.txt)).
  Offset N compares page `t` with the state at `t - 1 + N`; shift k = +1 means the padded page shows the state a tick later than the own page at the same tag.
- **Result**:
  - 52 pages differ outside the HUD clock, at #779's ticks; the viewpoint pages are the 23 it lists, and the HUD clock is equal on 15 of them (67, 507, 551, 804, 914, 969, 980, 991, 1014, 1047, 1145, 1167, 1189, 1212, 1267).
  - The 29 other differing pages (28 at the propeller, and 837): shift 0 decided on 28, with best-fit errors of 0.03 to 0.40 thousandths and next-best errors 3.0 to 684 times larger; 716, where the curve moves at most 1.9 thousandths per offset, is undecided at shift 0.
  - The 23 viewpoint pages: a one-tick shift decided on 15, the padded page a tick later on 9 (265, 287, 320, 815, 903, 914, 969, 1145, 1212) and a tick earlier on 6 (309, 551, 958, 1014, 1047, 1189); undecided on 6 (67, 507, 804, 980, 991, 1167), unscored (fade) on 2 (1267, 1311); no page decides shift 0 or ±2.
    Best-fit errors on the decided ones are 0.20 to 3.08 thousandths except 815 (8.71, where the curve falls 150 thousandths per offset).
  - Of the 15 equal-clock pages, 8 decide a one-tick shift (551, 914, 969, 1014, 1047, 1145, 1189, 1212), 6 are undecided and 1267 is unscored; of the 8 others, 7 decide one (1311 unscored).
  - On the viewpoint pages up to 1047 the own arm's curve peaks, its largest step between offsets 8.3 to 150 thousandths; from 1145 it is nearly flat (at most 3.3 thousandths per offset) and both arms peak at offset +1 or +2, so there a shift decides on small differences and an arm's best offset says little about its absolute tick.
  - On review: the three decided pages from 1145 (1145, 1189, 1212) move at most 2.1 thousandths between offsets in either arm, with fit errors of 0.20 to 0.24 thousandths, the size of the propeller pages' errors at shift 0, and their best offsets sit at +2 on 1189 and 1212.
    Because the padded arm's archive conflicts with the render's and every score is waived, its curve can sit at another level than the own arm's whatever its tick, and on a near-flat ramp a level offset can pass for a shift.
    Without them: 12 decided at one tick on peaked curves (7 later, 5 earlier), 5 of them at an equal HUD clock.
- **Verdict**: control.
  The score tells a one-tick camera step apart where the camera moves and the curve peaks: the propeller pages, whose scene is the same in both arms, fit shift 0 closely, and 12 viewpoint pages fit a shift of exactly one tick.
  So on those 12 of the 23 viewpoint pages, 5 of them at an equal HUD clock, the two arms' scenes are a tick apart at one tag, and at least one of each pair is paired by parity's `t - 1` with a render a tick off its scene; no pair is two ticks apart.
  The shift is relative: it dates neither page.
- **Lives in**: [`film-load.md`](../../../research/playone-exe/film-load.md) § 5; [`capture-dosbox-automation.md`](../../../research/playone-exe/capture-dosbox-automation.md) open question 15; [`capture.md` § 4](../../../research/playone-exe/capture.md#4-observed-results).
