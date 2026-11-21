# System Architecture & 1-Hop Routing Table

Code path to the documents that govern it.
Every cell links to its single home: anchors resolve through the registry in [`python/stunt_reel/doc_anchors.py`](../python/stunt_reel/doc_anchors.py), byte layouts live in the `.ksy` schemas next to each format document, and the format catalog starts at [`research/formats/INDEX.md`][].
Nothing else is defined here, so a stale row is a broken link or a missing path and fails `mise run check`.
This table routes the Rust crates and research directories, with the Python files that pair with them; the rest of the Python package and scripts route from [`architecture-python.md`](architecture-python.md).

## 1. 1-Hop Module Routing Table

| Subsystem / Code Path | Seam Contract | Governing Anchors | Specification / Research Notes |
|---|---|---|---|
| [`crates/stunt-core/src/contracts/vfs.rs`](../crates/stunt-core/src/contracts/vfs.rs) | Seam 1 (`VfsArchive`) | [`[FMT-RES-HEADER]`][FMT-RES-HEADER], [`[FMT-ALL-CHUNKS]`][FMT-ALL-CHUNKS], [`[I7]`][I7], [`[I8]`][I8] | [`research/formats/res.md`][], [`research/formats/all.md`][], [`research/playone-exe/startup.md`](../research/playone-exe/startup.md) |
| [`crates/stunt-core/src/contracts/trajectory.rs`](../crates/stunt-core/src/contracts/trajectory.rs) | Seam 2 (`TrajectoryRecord`) | [`[I1]`][I1], [`[I4]`][I4] | [`research/formats/flm.md`][], [`research/formats/concepts/timeline-and-ticks.md`][] |
| [`crates/stunt-core/src/contracts/shape/mod.rs`](../crates/stunt-core/src/contracts/shape/mod.rs) | Seam 3 (`SodModelIr`) | [`[I2]`][I2] | [`research/formats/sod.md`][], [`research/playone-exe/sod-vm.md`][], [`research/playone-exe/sod-vm-generators.md`][] |
| [`crates/stunt-parity`](../crates/stunt-parity/) (typed render, capture, video and report documents; their JSON Schemas in [`schema/`](../crates/stunt-parity/schema/)) | Seam 4 (`VisualParityGate`) | [`[I6]`][I6] | [`research/parity/method.md`](../research/parity/method.md#1-the-loop), [ADR 0011](adr/0011-parity-artifacts-are-a-versioned-port.md), [ADR 0048](adr/0048-the-python-parity-adapter-is-checked-against-a-generated-schema.md) |
| [`crates/stunt-core/src/contracts/palette/mod.rs`](../crates/stunt-core/src/contracts/palette/mod.rs) | Seam 4 (`VisualParityGate`) | [`[I3]`][I3] | [`research/formats/concepts/palette-and-shading.md`][] |
| [`crates/stunt-core/src/vfs/`](../crates/stunt-core/src/vfs/) | Seam 1 (`VfsArchive`) | [`[FMT-RES-HEADER]`][FMT-RES-HEADER], [`[FMT-ALL-CHUNKS]`][FMT-ALL-CHUNKS], [`[I8]`][I8] | [`research/formats/res.md`][], [`research/formats/all.md`][] |
| [`crates/stunt-core/src/link.rs`](../crates/stunt-core/src/link.rs), [`crates/stunt-cli/src/link/mod.rs`](../crates/stunt-cli/src/link/mod.rs) and [`python/stunt_reel/link.py`](../python/stunt_reel/link.py) (a film's `.ALL` as a committed manifest: `stuntreel link extract` and `build`; every stock shape for `stuntreel --game`) | Seam 1 (`VfsArchive`) | [`[FMT-ALL-CHUNKS]`][FMT-ALL-CHUNKS], [`[I7]`][I7], [`[I8]`][I8] | [ADR 0032](adr/0032-a-films-archive-is-committed-as-a-manifest.md), [`research/makeone-exe/linking.md`](../research/makeone-exe/linking.md) |
| [`crates/stunt-core/src/sod/`](../crates/stunt-core/src/sod/) | Seam 3 (`SodModelIr`) | [`[FMT-SOD-OPCODES]`](../research/formats/sod-opcodes.md#1-the-authoritative-107-opcode-reference-table--fmt-sod-opcodes), [`[FMT-SOD-IFVIS]`](../research/formats/sod-opcodes.md#25-bsp-sorting--two-sided-visibility-logic--fmt-sod-ifvis), [`[FMT-SOD-TAP]`](../research/formats/sod-opcodes.md#23-terrain-anchor-load-op_tap-0x022e--fmt-sod-tap), [`[FMT-SOD-ANIMATE]`][FMT-SOD-ANIMATE], [`[MEM-SOD-VM]`][MEM-SOD-VM], [`[MEM-SOD-ANCHOR-TABLE]`][MEM-SOD-ANCHOR-TABLE] | [`research/formats/sod.md`][], [`research/playone-exe/sod-vm.md`][], [`research/playone-exe/sod-vm-execution.md`](../research/playone-exe/sod-vm-execution.md), [`research/playone-exe/sod-vm-generators.md`][], [`research/playone-exe/sod-vm-lines-spans.md`][], [`research/playone-exe/sod-vm-frame.md`](../research/playone-exe/sod-vm-frame.md), [`research/playone-exe/sod-animate.md`][], [`research/formats/sod-opcode-coverage.md`](../research/formats/sod-opcode-coverage.md) (unimplemented-opcode queue) |
| [`crates/stunt-core/src/sprite.rs`](../crates/stunt-core/src/sprite.rs) (`OP_ANIMATE` image frames) | Seam 3 (`SodModelIr`) | [`[FMT-SOD-ANIMATE]`][FMT-SOD-ANIMATE], [`[I3]`][I3] | [`research/playone-exe/sod-animate.md`][], [`research/formats/auxiliary/spr.md`](../research/formats/auxiliary/spr.md) |
| [`crates/stunt-core/src/flm/`](../crates/stunt-core/src/flm/) | Seam 2 (`TrajectoryRecord`) | [`[FMT-FLM-OPCODES]`](../research/formats/flm.md#33-master-opcode-dispatch-table--fmt-flm-opcodes), [`[I4]`][I4] | [`research/formats/flm.md`][], [`research/formats/concepts/timeline-and-ticks.md`][] |
| [`crates/stunt-core/src/anchor.rs`](../crates/stunt-core/src/anchor.rs) | Seam 3 (`SodModelIr`), static world | [`[MEM-SOD-ANCHOR-TABLE]`][MEM-SOD-ANCHOR-TABLE], [`[I1]`][I1] | [`research/formats/auxiliary/anchorpt.md`][], [`docs/adr/0001-sod-tap-anchor-table.md`][] |
| [`crates/stunt-core/src/world/mod.rs`](../crates/stunt-core/src/world/mod.rs) (the `World` build: anchors, `MAP.BIN` patches, scenery, terrain, the arena mesh with `[I5]` decals, `OP_TAP` props) | Seam 3 (`SodModelIr`), static world | [`[I1]`][I1], [`[I2]`][I2], [`[I3]`][I3], [`[I5]`][I5] | [`research/formats/auxiliary/map.md`](../research/formats/auxiliary/map.md), [`research/formats/auxiliary/anchorpt.md`][], [`research/playone-exe/world-scene.md`](../research/playone-exe/world-scene.md), [`research/playone-exe/world-scene-residuals.md`](../research/playone-exe/world-scene-residuals.md), [`research/parity/render-model.md`][], [`docs/adr/0001-sod-tap-anchor-table.md`][], [`docs/adr/0035-ground-lying-props-are-terrain-decals.md`](adr/0035-ground-lying-props-are-terrain-decals.md), [`docs/adr/0045-flat-ground-is-painted-in-walk-order.md`][] |
| [`crates/stunt-core/src/world/scenery/mod.rs`](../crates/stunt-core/src/world/scenery/mod.rs) (placements: the scenery walk with its LOD gate, dedup, the sub-pixel cull and which props `PLAYONE`'s distance cut may drop) | Static world | [`[I1]`][I1] | [`research/formats/auxiliary/scenery.md`](../research/formats/auxiliary/scenery.md), [`research/playone-exe/lod.md`](../research/playone-exe/lod.md), [`research/playone-exe/world-scene-residuals.md`](../research/playone-exe/world-scene-residuals.md), [`research/parity/attribution.md`](../research/parity/attribution.md) |
| [`crates/stunt-core/src/world/placed.rs`](../crates/stunt-core/src/world/placed.rs) (placement records: each placement's `SCENERY.scn` node, the partition steps above it, its shape's collision list and its runs of the world mesh, for the collision probe and the partition-ordered sprite draw) | Static world, Seam 3 (`SodModelIr`) | [`[I1]`][I1], [`[I2]`][I2] | [`research/formats/sod.md`][], [`research/playone-exe/scene-walk-actors.md`](../research/playone-exe/scene-walk-actors.md) |
| [`crates/stunt-core/src/world/probe.rs`](../crates/stunt-core/src/world/probe.rs) (the collision half of the ground and collision probe: a shadowed slot tested against the placement records' lists, for the height a code-8 box gives its shadow) | Static world, film scene | [`[I1]`][I1] | [`research/playone-exe/sod-vm-frame.md`](../research/playone-exe/sod-vm-frame.md), [`research/formats/sod.md`][] |
| [`crates/stunt-core/src/world/slot_order.rs`](../crates/stunt-core/src/world/slot_order.rs) (an actor's pending-list entry ordered among the placement records as the scenery walk splits it; the Rust counterpart of `scene_tree.walk_slot`, for the partition-ordered sprite draw) | Static world | [`[I1]`][I1] | [`research/playone-exe/scene-walk-actors.md`](../research/playone-exe/scene-walk-actors.md), [`research/playone-exe/sod-animate.md`][] |
| [`crates/stunt-core/src/scene/mod.rs`](../crates/stunt-core/src/scene/mod.rs) (the film scene: frame, archive and `RES` shapes, view camera and LOD bounds, ground shadow, sprite bank) | Seam 2 (`TrajectoryRecord`), Seam 3 (`SodModelIr`), film scene | [`[I1]`][I1], [`[I4]`][I4] | [`research/formats/all.md`][], [`docs/adr/0001-sod-tap-anchor-table.md`][] |
| [`crates/stunt-core/src/font.rs`](../crates/stunt-core/src/font.rs) | — (game data read at run time) | [`[I3]`][I3], [`[I7]`][I7] | [`research/formats/auxiliary/pfont.md`](../research/formats/auxiliary/pfont.md) |
| [`crates/stunt-core/src/credits.rs`](../crates/stunt-core/src/credits.rs) | — (film events beside the trajectory) | [`[I3]`][I3] | [`research/formats/auxiliary/pfont.md`](../research/formats/auxiliary/pfont.md#32-drawing-the-credits), [`research/playone-exe/sod-vm-frame.md`](../research/playone-exe/sod-vm-frame.md#9-per-frame-routine-and-scene-composition) |
| [`crates/stunt-core/src/frame.rs`](../crates/stunt-core/src/frame.rs) (Mode 13h frame geometry and per-pixel layer ids, shared by the renderer and the parity scorer; `stunt-render` re-exports them) | Seam 4 (`VisualParityGate`) | [`[I3]`][I3] | [`research/parity/method.md`](../research/parity/method.md#1-the-loop), [`research/parity/attribution.md`](../research/parity/attribution.md) |
| [`crates/stunt-gltf/`](../crates/stunt-gltf/) | Seam 3 (`SodModelIr`) | [`[I1]`][I1], [`[I3]`][I3], [`[I5]`][I5] | [`research/formats/sod.md`][], [`research/formats/concepts/palette-and-shading.md`][], [`docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md`][] |
| [`crates/stunt-cli/src/scene/mod.rs`](../crates/stunt-cli/src/scene/mod.rs) | Seam 3 (`SodModelIr`), Seam 1 | [`[FMT-ALL-CHUNKS]`][FMT-ALL-CHUNKS], [`[I8]`][I8] | [`research/formats/all.md`][], [`research/formats/sod.md`][], [`coordinates-and-units.md`](../research/formats/concepts/coordinates-and-units.md#12-right-handed-metric-basis-i1) |
| [`crates/stunt-cli/src/shape_views/mod.rs`](../crates/stunt-cli/src/shape_views/mod.rs) (`stuntreel shape-views`: orthographic views of an archive's shapes and a geometry-hash manifest), with [`shape_diff.py`](../python/scripts/shape_diff.py) (`mise run shape-diff`: the shapes a `DBG_*` value changes, drawn before and after) | Seam 3 (`SodModelIr`) | [`[I1]`][I1] | [`research/parity/probes.md`](../research/parity/probes.md#8-tool-coverage) |
| [`crates/stunt-score/`](../crates/stunt-score/) (the parity engine as a library with no GPU dependency; [`stunt-cli/src/parity.rs`](../crates/stunt-cli/src/parity.rs) parses the `stuntreel parity` flags into `parity::Options` and calls it): [`src/parity/`](../crates/stunt-score/src/parity/) (the capture-vs-render compare and report: frames matched by film clock, per-frame SSIM, mask IoU, fade, per-class loss, `--compare` and `--compare-test`, contact sheets) | Seam 4 (`VisualParityGate`) | [`[I6]`][I6] | [`research/playone-exe/capture.md`](../research/playone-exe/capture.md), [`research/formats/concepts/palette-and-shading.md`][], [`method.md`](../research/parity/method.md#1-the-loop), [`report-fields.md`](../research/parity/report-fields.md) |
| [`crates/stunt-cli/src/main.rs`](../crates/stunt-cli/src/main.rs) (subcommand dispatch; [`config/mod.rs`](../crates/stunt-cli/src/config/mod.rs) options, [`headless.rs`](../crates/stunt-cli/src/headless.rs) PNG/`--out-dir`/video, [`page_slot.rs`](../crates/stunt-cli/src/page_slot.rs) the page sink, [`memory_report.rs`](../crates/stunt-cli/src/memory_report.rs) `--report-memory`, [`window.rs`](../crates/stunt-cli/src/window.rs) interactive playback) | Seam 2, Seam 4 | [`[I4]`][I4], [`[I6]`][I6] | [`research/formats/flm.md`][], [`research/formats/concepts/timeline-and-ticks.md`][] |
| [`crates/stunt-render/`](../crates/stunt-render/) | Seam 3 (`SodModelIr`), Seam 4 | [`[I3]`][I3], [`[I5]`][I5] | [`research/formats/concepts/palette-and-shading.md`][], [`research/parity/render-model.md`][], [`research/parity/lavapipe.md`](../research/parity/lavapipe.md), [`research/parity/lavapipe-render-time.md`](../research/parity/lavapipe-render-time.md), [`docs/adr/0045-flat-ground-is-painted-in-walk-order.md`][], [`docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md`][] |
| [`crates/stunt-render/src/video.rs`](../crates/stunt-render/src/video.rs) | Seam 2, Seam 4 | [`[I4]`][I4], [`[I6]`][I6] | [`research/formats/concepts/timeline-and-ticks.md`][] |
| [`research/formats/`](../research/formats/) | All Seams | — | [`research/formats/INDEX.md`][] (master catalog) |
| [`research/playone-exe/`](../research/playone-exe/) | — | [`[MEM-VSYNC-03DA]`](../research/playone-exe/memory-map-runtime.md#-mem-vsync-03da), [`[MEM-FLM-TICK]`](../research/playone-exe/memory-map-runtime.md#-mem-flm-tick), [`[MEM-SOD-VM]`][MEM-SOD-VM] | [`research/playone-exe/memory-map.md`](../research/playone-exe/memory-map.md) (offset tables) |

[`docs/adr/0001-sod-tap-anchor-table.md`]: adr/0001-sod-tap-anchor-table.md
[`docs/adr/0045-flat-ground-is-painted-in-walk-order.md`]: adr/0045-flat-ground-is-painted-in-walk-order.md
[`docs/adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md`]: adr/0046-coplanar-decals-are-drawn-in-an-ordered-pass.md
[FMT-ALL-CHUNKS]: ../research/formats/all.md#21-on-disk-directory-layout--fmt-all-chunks
[FMT-RES-HEADER]: ../research/formats/res.md#21-on-disk-physical-header--offset-table-layout--fmt-res-header
[FMT-SOD-ANIMATE]: ../research/formats/sod-opcodes.md#24-animation-resource-draw-op_animate-0x01f8--fmt-sod-animate
[I1]: SPEC.md#i1-metric-right-handed-coordinates-attribute-preserving-vertex-welding--anglefov-normalization
[I2]: SPEC.md#i2-flat-arena-allocation-no-recursive-pointers
[I3]: SPEC.md#i3-authentic-vga-mode-13h-palette-indexing--flat-shading
[I4]: SPEC.md#i4-discrete-simulation-ticks--cut-aware-sub-tick-interpolation
[I5]: SPEC.md#i5-coplanar-decal-resolution
[I6]: SPEC.md#i6-visual-parity-acceptance-thresholds--vga-112-aspect-ratio-correction
[I7]: SPEC.md#i7-asset-isolation--small-pure-rust-core-dependencies
[I8]: SPEC.md#i8-dos-83-uppercase-path-normalization
[MEM-SOD-ANCHOR-TABLE]: ../research/playone-exe/memory-map-vm.md#31-anchor-table-cache--mem-sod-anchor-table
[MEM-SOD-VM]: ../research/playone-exe/memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm
[`research/formats/all.md`]: ../research/formats/all.md
[`research/formats/auxiliary/anchorpt.md`]: ../research/formats/auxiliary/anchorpt.md
[`research/formats/concepts/palette-and-shading.md`]: ../research/formats/concepts/palette-and-shading.md
[`research/formats/concepts/timeline-and-ticks.md`]: ../research/formats/concepts/timeline-and-ticks.md
[`research/formats/flm.md`]: ../research/formats/flm.md
[`research/formats/INDEX.md`]: ../research/formats/INDEX.md
[`research/formats/res.md`]: ../research/formats/res.md
[`research/formats/sod.md`]: ../research/formats/sod.md
[`research/parity/render-model.md`]: ../research/parity/render-model.md
[`research/playone-exe/sod-animate.md`]: ../research/playone-exe/sod-animate.md
[`research/playone-exe/sod-vm-generators.md`]: ../research/playone-exe/sod-vm-generators.md
[`research/playone-exe/sod-vm-lines-spans.md`]: ../research/playone-exe/sod-vm-lines-spans.md
[`research/playone-exe/sod-vm.md`]: ../research/playone-exe/sod-vm.md

## Decoding Engine and Independent Oracle

`crates/stunt-core` is the only hand-written decoder for `.RES`/`.ALL`/`.SOD`/`.FLM`, the Mode 13h palette, and decal resolution; `stunt-render`, `stunt-gltf` and `stunt-cli` consume its output.
The Python package does not decode game formats.
Its one remaining copy of Rust knowledge is `python/stunt_reel/tac/palette.py`, which `tests/fixtures/mode13h_palette.json` pins to the Rust table in both languages.

A decoded shape owns its provenance and its geometry: `stunt_core::sod::decode_sod` is the single entry point in strict, lenient or census mode, it attaches a `DecodeRecord` (header, first blocking opcode, census step-overs, first `OP_RETURN`) to the shape, and it enforces the shape invariants consumers rely on.
The world builder, renderer and glTF exporter therefore read `meshes()` and `extent()` instead of re-validating ranges or re-measuring bounds; authored shapes carry no decode record.

The one sanctioned second decoder is deliberate: the Kaitai `.ksy` schemas under `research/formats/` and `python/stunt_reel/flm_walk.py` are written from the format description, not from the Rust code, and `python/scripts/verify_*.py` compare them against the corpus.
A disagreement there is evidence about the format, so these stay independent of the Rust parsers.

## Direction and History

The 2026-10-25 architecture deepening programme (parity artifact port, decoded shape seam, renderer entry point, capture session) is closed; its decisions, closure note and residual risk are in [work/2026-10/architecture-deepening/overview.md](../work/2026-10/architecture-deepening/overview.md).
