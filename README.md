# stunt-reel

[![CI](https://github.com/neilsh/stunt-reel/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/neilsh/stunt-reel/actions/workflows/ci.yml)

Format analysis, documentation, and modern reconstruction for *Stunt Island* (1992, Walt Disney Computer Software / The Assembly Line): offline-tested Rust and Python parsers for its file formats, a native `wgpu` renderer (`stuntreel`) that plays the standalone film reels, and a dosbox-automation harness that captures frames from the original `PLAYONE.EXE` to check the renderer against.

> [!WARNING]
> **Work in progress (pre-alpha).** This is an active reverse-engineering project, not a finished product or a game you can install and play. Formats, APIs, command lines and documentation change without notice, and parts of the rendering are known to differ from the original. It is developed in collaboration with AI coding agents; [`AGENTS.md`](AGENTS.md) is the contributor guide.

No game assets or executables are distributed. You need your own lawfully obtained copy of the files you want to analyse or play — see [Legal & assets](#legal--assets).

---

## Status

| Area | State |
| --- | --- |
| File formats (`.RES`, `.ALL`, `.SOD`, `.FLM`, `.SET` and auxiliaries) | Documented in [`research/formats/`](research/formats/INDEX.md) with Kaitai Struct layouts; parsed in `stunt-core`. Some fields are still hypotheses — each claim carries an evidentiary tier. |
| `.SOD` display-list VM and film timeline | Implemented; a few opcodes and timing details are still open. |
| Native renderer (`stuntreel`) | Plays the demo films `CTRY.FLM` and `INTRO.FLM` at 50 Hz with a free camera. Terrain colours, some actor placement and level of detail do not yet match the original. |
| glTF export | Shapes and single film frames. |
| Parity loop | Scores rendered frames against frames captured from the original player. Its log is [`research/parity/log.md`](research/parity/log.md). |
| Platforms | The build and test gate runs on Linux, macOS and Windows. Capture and parity need Windows, dosbox-automation and your own copy of the demo. |
| Not planned | The interactive flight simulator and authoring tools (`STUNT.EXE`); audio output is deferred. See [`docs/SPEC.md`](docs/SPEC.md#21-explicit-scope-boundaries--non-goals). |

---

## Quick start

You can build and test everything without any game files:

```powershell
mise trust && mise install   # pinned toolchains (Rust, Python, uv, Java, dosbox-automation, Kaitai)
mise run init                # shared data root, cached Python environment
mise run check               # format, lint, typecheck and tests, Rust and Python
mise run hooks               # optional: commit hooks (format and lint when Rust or Python is staged)
```

To render a film you need the *Stunt Island* demo (`stisldem`) in `corpus/stisldem/`, described in [`corpus/README.md`](corpus/README.md):

```powershell
cargo run -p stunt-cli -- corpus/stisldem/VAULT/CTRY.FLM --all corpus/stisldem/VAULT/CTRY.ALL
```

Space pauses, C toggles authored/free camera, WASD/QE fly the free camera, Esc exits. Headless rendering, video and glTF export, reference capture and the parity loop are in the [development guide](docs/development.md).

---

## Where to look

| Document | Covers |
| --- | --- |
| [`docs/development.md`](docs/development.md) | Requirements, setup, workflows, project layout, the quality gate and every `mise` task |
| [`docs/SPEC.md`](docs/SPEC.md) | Goals, invariants `[I1]`–`[I8]`, evidentiary tiers, verification matrix |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Module routing to specification anchors and research notes |
| [`research/formats/INDEX.md`](research/formats/INDEX.md) | Format catalog and Kaitai layouts |
| [`research/playone-exe/`](research/playone-exe/) | `PLAYONE.EXE` disassembly notes: startup, memory map, display-list VM, capture harness |
| [`research/parity/`](research/parity/) | How rendered frames are compared with the original, and the dated results |
| [`GLOSSARY.md`](GLOSSARY.md) | Project vocabulary: film, slice, tick, shape, slot |
| [`docs/adr/`](docs/adr/) | Accepted design decisions, one record each |
| [`tests/fixtures/README.md`](tests/fixtures/README.md) | Synthetic fixtures the offline tests use |
| [`NOTICE.md`](NOTICE.md) | Provenance, game-derived data and third-party credits |
| [`AGENTS.md`](AGENTS.md) | Contributor directives and standard operating procedures |

---

## Legal & assets

*Stunt Island* and related marks are trademarks of The Walt Disney Company. This is an unofficial, non-commercial research and preservation project: it is not affiliated with, authorised by, or endorsed by The Walt Disney Company or The Assembly Line.

No game assets, executables, or original data files are distributed. `corpus/` is gitignored and every test runs offline against synthetic fixtures; you must supply your own lawfully obtained copy of any retail files. Two small game-derived tables are committed as documented exceptions because the renderer needs them for format fidelity — the 256-entry master palette (768 bytes) and an 18-entry SOD scale table — and they are credited and described in [`NOTICE.md`](NOTICE.md). Quoted manual text and cited community research remain under their original terms.

See [`NOTICE.md`](NOTICE.md) for provenance and third-party credits, and [License](#license) for the licence split.

---

## Contributing

Issues are welcome. For anything larger than a small fix, please open an issue before a pull request so we can agree on the approach. This is a small project with no promised response times. Before opening a pull request, run `mise run check` and read [`AGENTS.md`](AGENTS.md). Report vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md).

## License

Original code and schemas are dual-licensed under [MIT](LICENSE-MIT) OR [Apache-2.0](LICENSE-APACHE), at your option.

Original documentation and research notes are licensed [CC BY 4.0](LICENSE-CC-BY-4.0).

Game-derived material (the raw palette and scale tables), quoted manual text, and cited community work are not relicensed by this project and remain under their own terms — see [`NOTICE.md`](NOTICE.md).
