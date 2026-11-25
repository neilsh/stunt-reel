# Journal

## 2026-11-24: the stadium's loss split by line, outline and fill

- **Question**: how much of the stadium 613's loss on `location` ticks 2586 to 2872 its lines and outlines own, and how much its fills.
- **Method**: `main` at `1e1d5680` with two temporary switches, on the RTX 4070 (the GPU; at 2729 its 613 loss, 0.057408, is the canonical lavapipe's 0.057405 of [#989's `shape-frames.csv`](../989_props-loss-shapes/shape-frames.csv)).
  The 27 ticks are the frames on which #989 found 613 losing.
  - [`DBG_LINEMARK=1`](switches/DBG_LINEMARK.diff) tags each pixel's shape word with what drew it last: a `ZLINETO` line quad, an outline quad, or the world's outline line list (`mesh.rs`'s `LineList`, [`sod-vm-lines-spans.md` § 8.11](../../../research/playone-exe/sod-vm-lines-spans.md#811-polygon-spans-include-both-ends)).
    `mise run frame -- --film location --ticks <the 27> --no-build --var DBG_LINEMARK=0,1` rendered both; the marked render's index and shape planes equal the baseline's at every tick, so the tags move no pixel.
  - [`line_masks.py`](line_masks.py) turns the pair into masks of 613's pixels: `zline` (a `ZLINETO` line drew it), `outline` (an outline drew it), `lines` (either), `fill` (the rest), and `lines_d1` (`lines` grown by one pixel in the four directions, within 613).
    [`mask_classes.py`](mask_classes.py) adds `band` (`lines_d1` less `lines`) and `interior` (613 less `lines_d1`), and [`line_band.py`](line_band.py) splits `band` into `band_z` (beside a `ZLINETO` pixel) and `band_o` (the rest, beside an outline pixel); `zfoot` is `zline` with `band_z`, `ofoot` `outline` with `band_o`.
  - The capture-side oracle of [`probes.md` § 7](../../../research/parity/probes.md#7-no-rebuild-experiments-on-the-capture): [`DBG_ORACLE_DIR`](switches/DBG_ORACLE_DIR.diff) makes the scorer copy our index into the capture's at a mask's pixels before scoring, with the capture's sky mask unchanged, and prints 613's per-frame loss (#904's `DBG_SHAPE_DUMP` print).
    Each mask was scored with `target/release/stuntreel.exe parity --reference <data root>/captures/vault-location/frames --test <the DBG_LINEMARK=0 store>`; the loss a mask removes is 613's loss without the oracle minus its loss with it.
  - Per frame, every mask's pixel count, frame SSIM and 613 loss: [`oracle.csv`](oracle.csv).
  - The scripts' output: [`logs/base_line_masks.txt`](logs/base_line_masks.txt) (`line_masks.py <DBG_LINEMARK=0 store> <DBG_LINEMARK=1 store> <mask dir> 613`), [`logs/base_mask_classes.txt`](logs/base_mask_classes.txt) and [`logs/base_line_band.txt`](logs/base_line_band.txt) (`mask_classes.py` and `line_band.py` with `<data root>/captures/vault-location/frames <DBG_LINEMARK=0 store> <mask dir>`), each run as `mise exec -- uv run python …`.
    The first session's stores were overwritten by the next entry's renders, so these logs are from a second render of the same ticks, with the same switches on the same `crates/` (`ca208dc9`, whose `crates/` equal `1e1d5680`'s) on the same GPU; its masks are byte for byte the first session's at every tick and mask kept, and [`direction.txt`](direction.txt) is reproduced exactly.
- **Result**:
  - At 2729, 613 covers 12,488 pixels and loses 0.05741 (frame SSIM 0.81494); 132 of its pixels are `ZLINETO` lines, all in index 149 (the field's chalk), and 1,196 are outlines, all from the world's line list.
  - Loss removed, at 2729 and as the mean over the 27 frames (613's mean loss 0.03842), each as a share of 613's loss:

    | Mask | Pixels at 2729 | Removed at 2729 | Share | Mean removed | Share of mean |
    |---|---|---|---|---|---|
    | all of 613 | 12,488 | 0.03887 | 67.7% | 0.03099 | 80.7% |
    | lines (`ZLINETO` and outlines) | 1,328 | 0.00986 | 17.2% | 0.00782 | 20.4% |
    | `ZLINETO` lines | 132 | 0.00641 | 11.2% | 0.00413 | 10.8% |
    | outlines | 1,196 | 0.00345 | 6.0% | 0.00369 | 9.6% |
    | one-pixel band beside them | 2,043 | 0.02091 | 36.4% | 0.01506 | 39.2% |
    | lines and band (`lines_d1`) | 3,371 | 0.03073 | 53.5% | 0.02318 | 60.3% |
    | `ZLINETO` lines and their band (`zfoot`) | 378 | 0.00910 | 15.9% | 0.00694 | 18.1% |
    | outlines and their band (`ofoot`) | 2,993 | 0.02157 | 37.6% | 0.01619 | 42.1% |
    | fill (all but lines) | 11,160 | 0.02892 | 50.4% | 0.02271 | 59.1% |
    | interior (all but `lines_d1`) | 9,117 | 0.00752 | 13.1% | 0.00669 | 17.4% |

    Lines and fill add up to all of 613 (0.00986 + 0.02892 = 0.03878 of 0.03887 at 2729).
    The 32.3% of 613's loss at 2729 that no mask of 613 removes (19.3% of the mean) is in windows over 613 whose other pixels, of the shapes, ground or sky beside it, still differ from the capture.
  - Index disagreement with the capture over the 27 frames ([`logs/base_mask_classes.txt`](logs/base_mask_classes.txt)): 613 as a whole 8.9% (28,693 of 322,118 pixels), `ZLINETO` lines 38.4% (1,003 of 2,609), outlines 17.1% (5,044 of 29,523), the band 25.0% (12,728 of 50,962), the interior 4.1% (9,918 of 239,024).
    At 2729: 10.6%, 39.4%, 17.1%, 30.8% and 4.8%.
  - The chalk lines are drawn one pixel off, not missing: of the 1,003 disagreeing `ZLINETO` pixels, 958 have a four-neighbour where the capture shows our pixel's index, and of the 1,052 disagreeing `band_z` pixels, 877 show a capture index used by `ZLINETO` pixels in that frame ([`logs/base_line_band.txt`](logs/base_line_band.txt): `z_bad_linecol_adjacent`, `bz_bad`, `bz_cap_linecol`).
  - Which way ([`line_direction.py`](line_direction.py), [`direction.txt`](direction.txt)): for each disagreeing `ZLINETO` or outline pixel, the four-neighbours where the capture shows our pixel's index, counted by whether the neighbour lies toward the projection centre (160, 92.5) or away, on each side of it:

    | Pixels | Above the centre, row below / above | Below, row above / below | Left, column right / left | Right, column left / right |
    |---|---|---|---|---|
    | `ZLINETO` | 460 / 44 | 176 / 147 | 199 / 44 | 76 / 130 |
    | outline | 2,326 / 338 | 790 / 229 | 971 / 240 | 650 / 282 |

    The first figure of each pair is toward the centre.
    Seven of the eight counts favour the centre; the eighth, `ZLINETO` pixels right of the centre, favours the column to their right.
  - [Sheet](images/location-2729-stadium-lines.png): the capture (top left), our render (top right), the projector-truncation prototype of the next entry (bottom left), and 613's pixels at 2729 (bottom right; grey where our index matches the capture's, else red on a `ZLINETO` line, yellow on an outline, orange in the band beside them, blue in the interior, where it lies along the edges of the light towers' poles and the scoreboard drawn over 613).
    The capture shows the bases as white dots ours lacks.
- **Verdict**: control (diagnosis).
  613's lines and outlines own 17% of its loss at 2729 (20% of the mean); with the one-pixel band beside them, 54% (60%).
  The chalk lines alone, with their band, own 16% (18%), so lines in the narrow sense do not carry the loss; the edges, outlines and band, own 38% (42%).
  The disagreement there lies mostly a pixel toward the projection centre from ours, the direction `PLAYONE`'s truncating projectors move a vertex ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre)); the next entry scores that rule on these frames.
- **Lives in**: [`prop-shape-loss.md` § 2.5](../../../research/parity/prop-shape-loss.md#25-one-tick-phase-and-lines).

## 2026-11-24: the projector truncation prototype on the stadium

- **Question**: does drawing vertices where `PLAYONE`'s projectors truncate them ([`sod-vm-lines-spans.md` § 8.14](../../../research/playone-exe/sod-vm-lines-spans.md#814-projected-points-are-truncated-toward-the-centre), [#1064](https://github.com/neilsh/stunt-reel/issues/1064)) remove the stadium's line and edge loss?
- **Method**: the shader of `proto/1027-projector-rounding` (`f2e12e39`, the facet-plane form, gate passing, applied as `git diff origin/main...f2e12e39 -- crates/stunt-render/src/shaders/mode13h.wgsl` on `1e1d5680` with the previous entry's switches), the same 27 ticks rendered on the RTX 4070 and scored, 613's loss printed per frame as before ([`oracle.csv`](oracle.csv), `proto_*` columns).
  The prototype's renders were made with `DBG_LINEMARK=0,1` as before, and `line_masks.py` was rerun on that pair, so its masks are the prototype's own, not the baseline's; `mask_classes.py` and `line_band.py` were then rerun on them ([`logs/proto_line_masks.txt`](logs/proto_line_masks.txt), [`logs/proto_mask_classes.txt`](logs/proto_mask_classes.txt), [`logs/proto_line_band.txt`](logs/proto_line_band.txt)).
  These logs are from the first session's surviving prototype stores and are byte for byte those of a second render with the same shader diff.
  This is an attribution on one shape's frames, not a sweep: adopting the rule is #1064's.
- **Result**:
  - 613's loss at 2729 falls from 0.05741 to 0.03496 (39%); its mean over the 27 frames from 0.03842 to 0.02728 (29%), falling on 26 of them.
    Mean frame SSIM rises from 0.86011 to 0.88156, on 23 of the 27.
  - Index disagreement over the 27 frames ([`logs/proto_mask_classes.txt`](logs/proto_mask_classes.txt)) falls on 613 as a whole from 8.9% to 5.9%, on the `ZLINETO` lines from 38.4% to 21.8%, in the band from 25.0% to 10.0% and in the interior from 4.1% to 2.1%; on the outline pixels it rises from 17.1% to 23.2%.
- **Verdict**: control (attribution), evidence-backed by the rule at image `0x9D0D`, `0x9D25`, `0x9D71`, `0x9D82` that § 8.14 cites; not adopted here.
  The truncation rule removes about a third of the stadium's loss, its disagreement falling in the band, on the chalk lines and in the interior but not on the outline pixels; #1064, which owns drawing it without breaking depth ties, is the follow-up.
  The outline pixels' own disagreement rises under it, which points at the outline's pixels against the inclusive spans' (§ 10's polygon-outline question) as the part the rule leaves.
- **Lives in**: [`prop-shape-loss.md` § 2.5](../../../research/parity/prop-shape-loss.md#25-one-tick-phase-and-lines).
