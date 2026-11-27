# Check a .glb without a GPU

Validate a glTF binary with the Khronos glTF validator and render one PNG of it, on a cloud session with no GPU.
The checker is `mise run glb-check`, from [`python/scripts/glb_check.py`](../../python/scripts/glb_check.py); its renderer is [`tools/glb-check/render_blender.py`](../../tools/glb-check/render_blender.py) (Blender, CPU Cycles) or F3D.
Both renderers and the validator were run on 2026-11-26 in a cloud session (Ubuntu 24.04, no GPU), on a scene from `stuntreel export-gltf` (section 3).

## 1. Install the tools

These are the cloud session's own installs, not part of the repo's gate.

```bash
sudo apt-get install -y blender f3d xvfb python3-numpy
(cd tools/glb-check && npm ci)
```

- `blender` 4.0.2 from Ubuntu noble. Its glTF importer needs the system `python3-numpy`: without it, the import fails with `No module named 'numpy'`, and Blender exits 0 unless the task passes `--python-exit-code`, which `glb_check.py` does.
- `f3d` 2.2.1 from Ubuntu noble. Without a display it segfaults, even for an offscreen `--output`. The task runs it under `xvfb-run` when `DISPLAY` is unset, so `xvfb` must be installed too.
- The Khronos validator is the npm package `gltf-validator`, pinned in [`tools/glb-check/package.json`](../../tools/glb-check/package.json) with its lock file. `node` must be on `PATH`.

## 2. Get the game data (only for a scene export)

A shape or a film frame needs the game archives in the data root.
A cloud session fetches them in its setup, or on demand with the R2 read key pair from [`cloud-sessions.md`](../cloud-sessions.md):

```bash
mise run cloud-assets -- fetch
```

A `.glb` made by `stuntreel export-gltf` does not need the data root once it exists.

## 3. Export a glb

```bash
cargo build -p stunt-cli
D="$STUNT_DATA_ROOT/corpus"
mkdir -p build/gltf_output
./target/debug/stuntreel export-gltf --archive "$D/stisldem/VAULT/CTRY.ALL" \
    --film "$D/stisldem/VAULT/CTRY.FLM" --tick 400 \
    --sidata "$D/siarchive/Developer/FreeFlight/SIDATA" --out build/gltf_output/CTRY_t400.glb
```

Observed: 1,130 nodes, 880 meshes, 1.4 MB.
`--shape 0x0408`, which [`export-a-film.md`](export-a-film.md) gives as an example, did not export on 2026-11-26 (`CTRY.ALL`, default options): the shape stopped at opcode `0x022E` (`missing anchor table`) and the model had no vertices.

## 4. Check and render

```bash
mise run glb-check -- build/gltf_output/CTRY_t400.glb --time 8
mise run glb-check -- build/gltf_output/CTRY_t400.glb --time 8 --renderer f3d
```

| Option | Meaning |
| --- | --- |
| `--time S` | Animation time in seconds. Blender sets the frame at 24 fps; F3D passes `--animation-time`. |
| `--renderer blender\|f3d` | Default `blender`. |
| `--out DIR` | Default `build/glb-check/`. |
| `--validate-only` | Skip the render. |

Each run writes `<out>/<stem>.validation.json` (counts, counts per code, the first 200 messages) and `<out>/<stem>.png` (960 × 720).
Exit 0 means the validator reported no errors and the render wrote its PNG. With `--validate-only`, exit 0 means only that the validator reported no errors. Exit 1 means the validator reported errors or the render failed; exit 2 means a missing tool, a bad argument, or a validator that could not run.

Observed on the one scene: Blender rendered in about 2.6 s of Cycles time, and F3D under Xvfb took longer (not timed).
Observed: the film-frame glb had no animations, F3D printed `No animation available`, and `--time` changed nothing.

## What the first run found

On `CTRY_t400.glb` the validator first reported 2,757,016 errors, all `ACCESSOR_VECTOR3_NON_UNIT` on mesh `NORMAL` attributes, and 1,118 `NODE_MATRIX_DEFAULT` infos.
A Blender-made monkey glb (`bpy.ops.mesh.primitive_monkey_add` exported with `export_scene.gltf`, GLB; not in the repo) validated with 0 errors, so the validator does not flag every file.
Every non-unit normal was a screen-line vertex: the shape IR stores the vector to the segment's other end in a line vertex's `normal` ([`SodVertex`](../../crates/stunt-core/src/contracts/shape/mod.rs)), and the exporter copied it.
The validator counts a bad value once for each primitive reading its `NORMAL` accessor, and many primitives share one accessor: summing each primitive's non-unit values gives exactly 2,757,016, from 3,488 distinct line vertices.
The exporter now writes that vector's direction ([`shape.rs`](../../crates/stunt-gltf/src/shape.rs)), and on 2026-11-27 the same export validated with 0 errors and 1,125 infos (1,118 `NODE_MATRIX_DEFAULT`, 7 `UNUSED_OBJECT`).
