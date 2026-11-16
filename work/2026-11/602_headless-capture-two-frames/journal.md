# Journal

## 2026-11-15: Two frames in flight in headless capture

- **Question**: Can headless capture submit tick N+1 before reading tick N's page back, so the
  main thread's encoding and store writes overlap the command thread, and leave every render
  store byte-identical?
- **Method**:
  - Built `5844b4b8` before the change and this branch after it, each with
    `cargo build --release -p stunt-cli`; both binaries were kept and swapped between runs.
  - LOCATION ticks 12-300 rendered headless with the parity pipeline's arguments (`--at-ticks`
    for those 289 ticks, `--width 320 --height 200 --viewport-rows 185`) on lavapipe
    (mesa-dist-win 25.2.8, `VK_DRIVER_FILES` naming its `lvp_icd.x86_64.json`,
    `--software-only`) and on the RTX 4070 Laptop, one process per run. Two rounds, the second
    with the after binary first.
  - Every reference film's captured ticks rendered on the GPU with `mise run parity -- --jobs 1`,
    before and after; `frames.zst`, `layers.zst` and `palettes.zst` compared by SHA-256, with
    the stores' tick counts checked.
  - `mise run test-gpu`, `mise run check-rust`, then the full `mise run check`.
- **Result**:
  - **Timings**, one headless process each:

    | Run | Before | After |
    |---|---|---|
    | lavapipe, LOCATION ticks 12-300 | 88.65 s | 76.31 s |
    | GPU, LOCATION ticks 12-300 | 16.66 s | 12.40 s |
    | lavapipe, second round, after binary first | 89.89 s | 78.15 s |
    | GPU, second round, after binary first | 16.64 s | 12.56 s |

  - **Byte identity:** all three store files are identical before and after on both measured
    sets.
    - On lavapipe over LOCATION ticks 12-300, both sides hash
      `frames.zst` `ba77c2018d3d509b8b236f702e4f49f3f058a8d0f8c517a277b98b3dba56372f`,
      `layers.zst` `f9efdd2c72a683c0181beda17fd67d969e427d819ccfdc457f6bc17c81c880ae`,
      `palettes.zst` `2537dc858937720397d4220fc3f8678c092f49ec0c81ff445fb5041d93ec2aab`.
    - On the GPU over every reference film's captured ticks, 20,621 ticks in all, each of the 21
      file pairs matches; the comparison printed `ticks equal: True` and `0 difference(s)`.
      LOCATION for example hashes `frames.zst`
      `e00c24b2afd7820b2dfb8a8d08948644baa36c814b2c5652eb90091022ed3a12`, `layers.zst`
      `e2b3414e81bd62aaf8312f1135af91abf6a99b2195ce23fc4ea327dfe20144a2` and
      `palettes.zst` `f467d6646a04e66e0f6a14bba25def87d7434a29bba44d962dbc7dc9c41fd119`.
    - The seven `mise run parity` score lines are the same before and after.
  - **Order:** the before and after stores hold the same ticks in the same order, per film 1,320
    (CTRY), 3,807 (INTRO), 1,123 (LAND), 1,179 (BALLOON), 1,222 (TRAINTNL), 3,719 (BOMB) and
    8,251 (LOCATION); the render record's tick list is unchanged.
  - **Tests:** the new GPU test `pipelined_submits_hand_pages_back_in_submission_order` checks
    that a page is held until the next submission and that three pipelined pages match, in order,
    the pages a synchronous draw gives; the headless test
    `landed_pages_are_written_in_submission_order` pairs two landed pages with their frames.
- **Verdict**: adopted. The stores measured above are byte-identical and both adapters render the
  LOCATION span faster, the GPU by about a quarter and lavapipe by about an eighth.
- **Lives in**: [`research/parity/lavapipe.md`](../../../research/parity/lavapipe.md) section 6
  and open question 5.
