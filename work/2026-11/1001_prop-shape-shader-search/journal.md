# Journal: #1001, the plane's per-fragment `prop_shape` search

## 2026-11-26: the carrier for a world prop vertex's shape word

- **Question**: Which of the issue's three candidates removes `prop_shape`'s binary search of `prop_runs` at the least cost, and does `#1001` land before or after `#999`'s frame-streamed world?
- **Method**: Read `mode13h.wgsl`, `mesh.rs`, `pipeline.rs` and `scene_renderer.rs` at `main` `4d776929`, and [`world_stream.rs`](../../../crates/stunt-render/src/world_stream.rs) (`#999` stage A, which streams nothing yet).
- **Result**:
  - **Spare bits of `SodVertex`** do not hold it.
    The vertex is the seam-3 contract struct ([`contracts/shape/mod.rs`](../../../crates/stunt-core/src/contracts/shape/mod.rs)); its one spare byte (`_padding`) is 8 bits and a shape word, `shape id + 1` of a `u16` id, needs 17, so the contract and every consumer of the world IR would change.
  - **Per draw or per slice** was not built.
    It needs the word in the per-draw uniform (`model.layer.z`, which carries one for the view-facing props only), so each world prop slice would take its own uniform write and bind, draw state the loop already pays for (`#1002`: other state changes `8.5%` of lavapipe's queue thread); the per-vertex word adds none.
    Not measured.
  - **A smaller table** still searches.
    Only a per-frame table (`#999`) is small, and it keeps a search.
  - **Chosen: a 4 B per-vertex attribute in the second vertex stream.**
    The stream already follows the vertex buffer vertex for vertex (the apex, `outline::Outlined`); it becomes `ApexVertex { position: [f32; 3], prop_shape: u32 }`, 16 B a vertex, read at location 4 and flat-interpolated.
    The vertex shader picks `in.prop_shape` for a `SCENERY_PROP` vertex and `model.layer.z` for any other, which is what `prop_shape(vertex_index)` returned (a prop vertex lies in exactly one run, `PropRun`); the fragment stage reads one `u32`.
    No draw, pipeline, vertex-buffer slot or index changes, and the prop-runs bind group (`PROP_RUNS_GROUP`, its layout, the placeholder group, `attach_prop_runs`) goes.
    `GpuChunk::upload` fills the stream where the buffer is mapped (`mapped_at_creation`), in blocks, so no 16 B-a-vertex copy is made beside the device buffer.
  - **Cost of the attribute**: 4 B a vertex on every model's second stream, `25.57` MiB on `LOCATION`'s `6,702,496` world vertices (`6,702,496 x 4 / 1,048,576`), a few KiB on a shape.
  - **Order against `#999`**: `#1001` lands first.
    `#999`'s stage A already builds a per-frame runs table (`WorldStream::runs`, `987` pieces at most on the seven films); stage B, which draws from the stream, would write each streamed vertex's `ApexVertex::prop_shape` from those runs in the same pass that appends its apex, and drop the table's bind group, which `#1001` has already removed.
    `chunk_prop_runs` stays for stage A until then.
- **Verdict**: adopted for the attempt; whether it lands waits on the lavapipe gate (the entry on the load check below).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 1.

## 2026-11-26: stores and peak memory with the per-vertex shape word

`[Bounded Observation]`

- **Question**: Does the change leave every store byte-identical on the seven reference films on both adapters, and is the peak memory no higher by more than the added attribute (`25.57` MiB)?
- **Method**:
  - Two release binaries from isolated target directories (`mise run build-at`): `base` at `main` `4d776929` and `shape-word` at `ce42f628` (`crates` tree `ccb651e3`), Windows, the owner's laptop (RTX 4070 Laptop GPU, and `mesa-dist-win 25.2.8` `llvmpipe (LLVM 21.1.7, 256 bits)`).
  - [`store_check.py`](store_check.py) renders each reference film's captured ticks with each binary on each adapter, as `mise run parity` does, and hashes `frames.zst`, `layers.zst`, `palettes.zst` and `shapes.zst`.
  - [`memory_check.py`](memory_check.py) renders `LOCATION` ticks `12..=120` with `--report-memory` ([`measure-a-renders-memory.md`](../../../docs/howto/measure-a-renders-memory.md)), three runs a binary and adapter.
- **Result**:
  - Stores: all four hashes of `ctry`, `intro`, `land`, `balloon`, `traintnl`, `bomb` and `location` matched between the binaries on lavapipe and on the RTX 4070 ([`stores.csv`](stores.csv)).
  - Peak memory ([`memory.csv`](memory.csv), medians of three): lavapipe `907.6` MiB base and `931.7` MiB shape-word, `+24.1` MiB; RTX 4070 `700.4` and `699.8` MiB, `-0.6` MiB.
    The peaks of one cell spread at most `1` MiB.
    On lavapipe the renderer-opened reading rose `23.3` MiB (`763.6` to `786.9`) and the frames-rendered reading fell `54.6` MiB (`674.3` to `619.7`).
- **Verdict**: the stores gate and the peak-memory gate hold on this machine (`+24.1` MiB against the `25.57` MiB bound; the attribute is `25.57` MiB of `LOCATION`'s world).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 1.

## 2026-11-26: the lavapipe loop gate stopped on the load check, and what the stopped runs show

`[Bounded Observation]`

- **Question**: Is the whole `LOCATION` film's (`12..=8262`) lavapipe loop at least `5%` lower, faster in all 4 pairs, with the per-vertex shape word (`#1001`'s gate, read against `#1018`'s A/A: median `-1.07%`, eight loops spread `6.2%`)?
- **Method**:
  - `mise run ab -- --out work/2026-11/1001_prop-shape-shader-search --name lavapipe-ab --variant "base binary=build/base-1001.exe" --variant "shape-word binary=build/new-1001.exe" --span 12..=8262 --adapter lavapipe --rounds 4 --order alternate`, the two binaries above, default `--max-load 0.10`, nothing else of this task running.
  - [`ab-retry.sh`](ab-retry.sh) reran it between 08:15 and 10:00 UTC (34 attempts kept a row, numbered 0-45 in `stopped/`; the others kept none and no attempt log was kept), a minute apart in the later ones, each time moving the stopped run's CSV aside.
- **Result**:
  - Not one run finished: each stopped on the load check, before its first round (`16%` busy) or after one to three runs (`10%`, `11%`, `12%`).
    One other process held a core all the time (an unrecorded observation of the worker's, no raw file kept: a `claude.exe --resume ... --fork-session` of an Orca agent view, `1.01` cores of 16 over three 10-15 s samples, about `6%` of the CPUs, and whole-machine load `8..9%` with it running and nothing of this task), so other load sat at `0.096..0.108` in the kept rows.
    A stray `python -` of this task that spun one core was found and killed before the later attempts.
  - The kept rows are [`stopped/`](stopped/) (34 CSVs, one per attempt that kept a row, written by `mise run ab` as it stopped).
    `13` complete pairs, both binaries, come from 12 of them (attempt 22 holds two consecutive rounds), with the stores hashing alike: the shape-word loop was faster in all `13`, by `5.6%` to `12.6%` (median pair `-9.3%`), base loops `26,739..27,889 ms` and shape-word loops `24,082..25,496 ms`.
    Twelve of the `13` are a run's round 0 (base first) and one its round 1 (shape-word first); their other load was `0.096..0.108`, over the `0.10` bar in some.
- **Verdict**: no gate result.
  The runner's own bar (other load at most `0.10` over each run) was never met for a whole run, and no bar was raised.
  The stopped pairs are each more than `5%` faster, so a complete run at a quiet machine may pass, but these are 13 pairs from 12 runs, 12 of them a run's round 0 with base first (a fixed order, which `--order alternate` cancels), not 4 interleaved pairs of one run.
  The `RTX 4070` is reported below and never gates.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 1.

## 2026-11-26: the RTX 4070 loop, three pairs

`[Bounded Observation]`

- **Question**: What does the shape word do to the RTX 4070's whole-film loop (reported, never gating)?
- **Method**: `mise run ab` as above with `--adapter gpu --name gpu-ab`, 4 rounds asked.
- **Result**: it stopped on the load check after three pairs ([`gpu-ab.csv`](gpu-ab.csv)): base `8614.1`, `8604.9`, `8300.4 ms` and shape-word `8573.7`, `8570.9`, `8853.4 ms`, medians `8604.9` and `8573.7 ms` (`-0.4%`), faster in 2 of 3 pairs, other load `0.089..0.103`, the four hashes alike.
- **Verdict**: nothing resolved: a `6.7%` slower third pair is larger than the `0.4%` median change.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 1.

## 2026-11-27: the gates on the rebased change, and the owner's call

`[Bounded Observation]`

- **Question**: Does the per-vertex shape word, rebased onto `main` at `5951161`, hold `#1001`'s gates (stores, the whole `LOCATION` lavapipe loop at least `5%` lower and faster in all 4 pairs, Span B and the RTX 4070 reported), and does an instruction count agree?
- **Method**:
  - Owner's laptop (Windows, mesa-dist-win 25.2.8 and the RTX 4070), one release binary per side: `base` is `5951161`, `shape-word` is `acf55a0` (that base plus this change, before the third rebase below).
    Stores: [`store_check.py`](store_check.py) on both adapters ([`rebased/stores.csv`](rebased/stores.csv), this run's rows only).
    Loops: `mise run ab` as in the entries above, `--rounds 4 --order alternate`, at the default `--max-load 0.10` with another session's agent and the browser closed; each of the three runs completed on its first attempt ([`rebased/lavapipe-ab.csv`](rebased/lavapipe-ab.csv), [`rebased/lavapipe-ab-span-b.csv`](rebased/lavapipe-ab-span-b.csv), [`rebased/gpu-ab.csv`](rebased/gpu-ab.csv)).
  - A cloud session (4 vCPUs, Ubuntu `mesa-vulkan-drivers 25.2.8`): `mise run icount` on the same two commits built for Linux, 3 repeats a variant, on Span B's first 30 and 60 ticks ([`rebased/icount-b30-summary.md`](rebased/icount-b30-summary.md), [`rebased/icount-b60-summary.md`](rebased/icount-b60-summary.md) and their CSVs).
- **Result**:

  | Measure | base | shape-word | Change | Pairs shape-word won |
  |---|---|---|---|---|
  | Lavapipe, whole `LOCATION` (`12..=8262`), median loop | `28,509.0 ms` | `26,143.4 ms` | `-8.3%` | 3 of 4 |
  | Lavapipe, Span B (`3680..=3979`), median loop | `2,758.2 ms` | `2,595.1 ms` | `-5.9%` | 4 of 4 |
  | RTX 4070, whole `LOCATION`, median loop (reported) | `9,868.4 ms` | `10,322.8 ms` | `+4.6%` | 0 of 4 |
  | Instructions, Span B ticks `3680..=3709`, whole run | `28,159,572,670` | `26,759,290,554` | `-4.97%` (`299.6x` base range) | 3 repeats each |
  | the same outside glibc's `malloc.c` and `memmove` | `26,593,611,349` | `25,214,126,982` | `-5.19%` (`1511.7x`) | |
  | Instructions, ticks `3680..=3739`, whole run | `31,935,345,385` | `29,071,377,533` | `-8.97%` (`618.4x`) | |
  | the same outside the allocator | `30,095,422,004` | `27,270,934,828` | `-9.39%` (`2031.1x`) | |

  - Stores: all 14 film and adapter pairs hash alike (seven reference films, both adapters, `shapes.zst` included); every `mise run ab` and `mise run icount` run hashed its stores alike too.
  - The one lavapipe pair `shape-word` lost (round 2, `28,548.4` against `28,849.0 ms`, `+1.1%`) ran at the highest other load of the run (`0.092`; the others `0.037..0.071`).
  - On the RTX 4070 both sides slowed round by round (base `9,519.1` to `10,473.7 ms`), and `shape-word` lost every pair, including the two where it ran first.
  - In the counts the JIT-compiled shader code (no symbols, `???`) fell `1,770,240,116` (30 ticks) and `3,219,790,292` (60 ticks) instructions in repeat 0; the upload's new work rose by about `0.66` billion (`apex_vertices` `+441.9M`, `GpuChunk::upload` `+109.1M`, `memset` `+104.1M` on the 30-tick span), a start-up cost.
  - Callgrind with `--separate-threads` (2 repeats each, stores alike) splits the count by thread ([`rebased/callgrind-threads.md`](rebased/callgrind-threads.md)).
    The main thread, our Rust and the upload, rose `+612,819,204` (`+3.04%`) on 30 ticks and `+624,465,012` (`+3.00%`) on 60, the same amount at both lengths.
    Lavapipe's two worker threads fell: thread 2 by `10.00%` and `8.98%`, thread 3 by `57.51%` and `57.65%` (`2,605,161,552` to `1,107,018,777` on 30 ticks).
    Each change is at least 90 times its base's repeat gap; the totals, `-5.05%` and `-8.94%`, sit about 0.2% below Cachegrind's whole-run counts.
- **Verdict**: the lavapipe gate as written is missed on its direction clause (3 of 4 pairs) and met on its median (`-8.3%`, 3.3 points over the `5%` bar).
  By the issue's rule mixed pairs go to the owner; with the count's agreement the owner chose on 2026-11-27 to land the change and record the RTX 4070 cost.
  Why the RTX 4070 is slower is not measured; a larger second vertex stream is a candidate.
- **The third rebase**: before merging, the change was rebased onto a `main` whose second vertex stream had become a point and a radius (`outline::Apex`, `Float32x4`, `#1159`) beside a list rank at location 4, and which had added a diagnostic look reading the prop runs (`#1189`).
  The shape word moved to location 5 at offset 16 (`ApexVertex`, 20 B a vertex against `main`'s 16 B, the same `+4` B the runs above measured), and the diagnostic look reads it as the plane does.
  The measured binaries predate that rebase; it was checked by `mise run check` and the GPU tests on cloud lavapipe, and the lavapipe expected pins were re-measured on the merged tree.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 1.
