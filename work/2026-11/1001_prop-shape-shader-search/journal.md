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
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6.

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
    The peaks of one cell spread under `1` MiB.
    On lavapipe the renderer-opened reading rose `23.3` MiB (`763.6` to `786.9`) and the frames-rendered reading fell `54.6` MiB (`674.3` to `619.7`).
- **Verdict**: the stores gate and the peak-memory gate hold on this machine (`+24.1` MiB against the `25.57` MiB bound; the attribute is `25.57` MiB of `LOCATION`'s world).
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6.

## 2026-11-26: the lavapipe loop gate stopped on the load check, and what the stopped runs show

`[Bounded Observation]`

- **Question**: Is the whole `LOCATION` film's (`12..=8262`) lavapipe loop at least `5%` lower, faster in all 4 pairs, with the per-vertex shape word (`#1001`'s gate, read against `#1018`'s A/A: median `-1.07%`, eight loops spread `6.2%`)?
- **Method**:
  - `mise run ab -- --out work/2026-11/1001_prop-shape-shader-search --name lavapipe-ab --variant "base binary=build/base-1001.exe" --variant "shape-word binary=build/new-1001.exe" --span 12..=8262 --adapter lavapipe --rounds 4 --order alternate`, the two binaries above, default `--max-load 0.10`, nothing else of this task running.
  - [`ab-retry.sh`](ab-retry.sh) reran it about 35 times in all between 08:15 and 10:00 UTC, a minute apart in the later ones, each time moving the stopped run's CSV aside.
- **Result**:
  - Not one run finished: each stopped on the load check, before its first round (`16%` busy) or after one to three runs (`10%`, `11%`, `12%`).
    One other process held a core all the time (a `claude.exe --resume ... --fork-session` of an Orca agent view, `1.01` cores of 16 over three 10-15 s samples, about `6%` of the CPUs), and whole-machine load `8..9%` with it running and nothing of this task, so other load sat at `0.096..0.108` in the kept rows.
    A stray `python -` of this task that spun one core was found and killed before the later attempts.
  - The kept rows are [`stopped/`](stopped/) (34 CSVs, one per attempt that kept a row, written by `mise run ab` as it stopped).
    `13` of them hold a complete round, both binaries, with the stores hashing alike: the shape-word loop was faster in all `13`, by `5.6%` to `12.6%` (median pair `-9.3%`), base loops `26,739..27,889 ms` and shape-word loops `24,082..25,496 ms`.
    Twelve of the `13` are a run's round 0 (base first) and one its round 1 (shape-word first); their other load was `0.096..0.108`, over the `0.10` bar in some.
- **Verdict**: no gate result.
  The runner's own bar (other load at most `0.10` over each run) was never met for a whole run, and no bar was raised.
  The stopped pairs are each more than `5%` faster, so a complete run at a quiet machine may pass, but these are 13 round-0 pairs from different runs, not 4 interleaved pairs of one.
  The `RTX 4070` is reported below and never gates.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6.

## 2026-11-26: the RTX 4070 loop, three pairs

`[Bounded Observation]`

- **Question**: What does the shape word do to the RTX 4070's whole-film loop (reported, never gating)?
- **Method**: `mise run ab` as above with `--adapter gpu --name gpu-ab`, 4 rounds asked.
- **Result**: it stopped on the load check after three pairs ([`gpu-ab.csv`](gpu-ab.csv)): base `8614.1`, `8604.9`, `8300.4 ms` and shape-word `8573.7`, `8570.9`, `8853.4 ms`, medians `8604.9` and `8573.7 ms` (`-0.4%`), faster in 2 of 3 pairs, other load `0.089..0.103`, the four hashes alike.
- **Verdict**: nothing resolved: a `6.7%` slower third pair is larger than the `0.4%` median change.
- **Lives in**: [`lavapipe-render-time.md`](../../../research/parity/lavapipe-render-time.md) § 6.
