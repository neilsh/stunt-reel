# Journal: per-word slot angles

## 2026-11-26: the census bounds per-word angle interpolation as tiny

- **Question**: how much can interpolating a slot's three angle words each on its own, as `PLAYONE.EXE`'s `0x3E6C` does, move our render on the seven reference films (#1072 step 1, the census)?
  Is it worth the contract change it needs, and where would the per-word angles come from?
- **Method**: commit `25eb9586` (`origin/main`), plus [`census.patch`](census.patch), a throwaway `#[ignore]`d test in `stunt-core`'s player that is never committed (`git apply` it, then `cargo test -p stunt-core --lib census -- --ignored --nocapture`); its output is [`census.txt`](census.txt).
  It steps each reference film's `FlmPlayer` slice by slice and compares each pair of consecutive slices with a positive `tick_duration`, for slots active at both ends.
  The films are the seven of `research/parity/references.toml`; each file's SHA-256 equals its capture's `flm_sha256`.
  Per-word interpolation is `start + (end - start) * t` on the signed 16-bit difference of each word, at `t` 0.25, 0.5 and 0.75, without `0x3E6C`'s fixed-point rounding.
  - **Camera**: for every pair whose view slot changes any word (`view_obj` never switches in these films, and a view switch cuts), the angle between the direction our player draws, `normalize(lerp(forward_a, forward_b))` (it lerps the eye and a look-at point 1000 m ahead), and the forward axis of the per-word-interpolated words.
    The roll word needs no comparison: the player already interpolates it as a shortest-arc angle (`lerp_angle`), and the forward axis does not depend on it.
  - **Actors**: for every drawn, non-view slot (`SIF_DRAW`) with any word changed, the rotation angle between our slerp of the composed quaternions and the quaternion of the per-word-interpolated words.
  - **Gate count**: slices whose view slot or drawn actors change two or more words by more than 3 degrees (`census.txt` `CENSUS` lines).
  - **Scored frames**: the captured `film_tick`s of each `captures/vault-<film>/frames/meta.json` that fall inside an affected slice, by [`scored-ticks.py`](scored-ticks.py) over the `PAIR` lines of `census.txt` (run from the repository root, with `census.txt` copied to `build/scratch/pairs.txt`).
- **Result**:
  - **Gate count** (two or more words over 3 degrees; slices of the film out of its slice pairs; ticks in them):

    | Film | Slice pairs | View slot | Drawn actors |
    |---|---|---|---|
    | ctry | 129 | 0 | 0 |
    | intro | 369 | 1 (11 ticks) | 0 |
    | land | 111 | 0 | 0 |
    | balloon | 120 | 4 (45 ticks) | 0 |
    | traintnl | 125 | 8 (95 ticks) | 0 |
    | bomb | 348 | 1 (14 ticks) | 0 |
    | location | 868 | 5 (51 ticks) | 13 (138 ticks) |

  - **Camera**: the direction our player draws sits off the per-word direction by at most 0.03 degrees on ctry and intro, 0.04 on land, 0.24 on bomb and 0.38 on location.
    On balloon three slice pairs exceed 0.5 degrees (ticks 223 to 255, 32 ticks, at most 2.69) and on traintnl three (ticks 221 to 257, 36 ticks, at most 2.13); no other pair does.
    Why the large gaps arise (the look-at point's chord against the arc, or the second word moving) was not isolated: a `[Hypothesis]` that they are the pairs turning a word by tens of degrees.
  - **Actors**: slerp and per-word agree to 0.06 degrees at most on ctry, intro, balloon and traintnl, to 0.00 on land and bomb, and on location in all but two (slot, slice-pair) cases, both slot 9 (ticks 7244 to 7264, 0.78 and 0.71 degrees).
    Of the 64 location pairs, none exceeds 1 degree.
  - **Scored frames in the affected slices** (the captures hold 108 balloon, 112 traintnl and 745 location ticks): balloon 232, 243 and 254; traintnl 232, 243 and 254; location 7250 and 7261, none elsewhere.
    A captured tick near a slice's end, such as 232 in the slice 223 to 234, lies at a fraction near 0.8, away from the 0.25, 0.5 and 0.75 the census samples, so the figures above bound the gap on those ticks only roughly.
  - **Size on screen**: 185 viewport rows over the 42.67 degree vertical field of view is about 4.3 rows a degree, so the worst camera gap, 2.69 degrees, is about 12 rows at the screen centre, on three scored frames of each of two films.
  - **Where per-word angles come from** (#1072's second acceptance item): they are `SlotState::rot_bam`, the three raw angle words `0x3E6C` reads, which the player already holds and `evaluate_slice` drops into a quaternion (`crates/stunt-core/src/flm/player/mod.rs`).
    A change would carry them on the actor and camera records: the raw words, as no step turns a quaternion back into the three words `0x3E6C` interpolates, and `ActorTransform`/`CameraTransform` are seam contracts, so it needs `serde(default)` fields, fixtures and a roundtrip test (`changing-seam-contracts`).
- **Verdict**: not made; the issue's gate applies.
  The census bounds the effect as tiny: five films hold no camera pair over 0.5 degrees, the other two three each, and at most three scored frames of a film (balloon, traintnl; two on location from actors) sit in a slice pair whose gap exceeds 0.5 degrees.
  Arithmetic, not a measurement: three scored frames of 108 or 112 moving by 0.05 each would move a film's `mean_ssim_scored` by about 0.0014, under the 0.002 policy bound ([`loop-rules.md`](../../../.agents/skills/improving-render-parity/loop-rules.md#guards)); the change costs a seam-contract field, fixtures and a lavapipe repin.
  No sweep ran and nothing was adopted; the census figures above are the per-film record.
  A film that later holds slices turning two axes by tens of degrees would reopen it.
- **Lives in**: [`timeline-and-ticks.md` § 3.2](../../../research/formats/concepts/timeline-and-ticks.md#a-slot-moving-far-within-one-slice-is-not-a-cut) and the Ruled out list of [`framing-and-actors.md`](../../../research/parity/framing-and-actors.md#ruled-out).
