# Python scripts may take well-established dependencies

## Status

accepted

## Context

The Python half is tooling. [`python/scripts/`](../../python/scripts/) drives the parity loop, captures
references and verifies the docs; [`python/stunt_reel`](../../python/stunt_reel/) is the capture harness
and the only package that ships in the wheel. [`pyproject.toml`](../../pyproject.toml) declares no runtime
dependencies, and its dev group holds only the Kaitai Struct runtime, mypy, pytest (with coverage)
and ruff.

Work on the parity scripts raised two questions at once. Four JSON files written by the Rust binaries
are read with bare dictionary access — `report.json`, `meta.json`, `palette_controls.json` and
`palettes_%04d.json` — so a shape change surfaces as a `KeyError` in the middle of a sweep, after
the renders have been paid for. And the nine argparse entry points repeat flag definitions, with
[`parity_run.py`](../../python/scripts/parity_run.py) and [`parity_sweep.py`](../../python/scripts/parity_sweep.py)
already disagreeing about what `--reuse` means.

A dependency would have to sit in one of two places: the shipped wheel or the scripts.
`pydantic-settings` was raised for argument parsing, which conflates three jobs the scripts keep
apart: parsing `argv`, resolving layered settings, and validating data read from another process.
No settings layer exists — two `STUNT_*` environment variables, read in
[`dataroot.py`](../../python/stunt_reel/dataroot.py), with no `.env` and no config file — so
`pydantic-settings`' CLI support would be used as a plain argv parser, a job argparse already does,
including the subparsers in [`parity_probe.py`](../../python/scripts/parity_probe.py).

## Decision

`python/stunt_reel` keeps no runtime dependencies: it is the shipped package and the offline
capture harness, so a decision about dev tooling never widens what installing or testing it needs.

`python/scripts/` may take a dependency in the dev group when it clears two tiers.

- **Checks.** Wheels for every CI platform, so `uv sync --locked` never builds from source; a
  `py.typed` marker or a maintained mypy plugin; an acceptable licence; and a release or commit
  within roughly two years.
- **Record.** The admitting ADR states the job the dependency does and why the standard library
  cannot, and reads its dependency tree, justifying each package.

Version numbers are not a gate: [`mise.toml`](../../mise.toml) already pins `uv 0.13.1` and
`dosbox-x-mcp-server 0.1.2`. Neither is a transitive-dependency count, which would refuse the
packages with the widest use.

## Considered Options

- **pydantic for the JSON boundary.** Rejected for now. The deciding payload is the palette sidecar,
  which `retime` rewrites while preserving keys it does not know; that pass-through is the opposite
  shape to a model, and models would add `plugins = ["pydantic.mypy"]` to a configuration that is
  otherwise strict by default. Validation instead lives in the artifact adapter
  ([`parity_artifacts.py`](../../python/stunt_reel/parity_artifacts.py) since ADR 0011; its temporary
  `parity_inputs.py` shim was removed in unit A landing 4), which names the file and the field it
  could not read. Revisit when a payload gains a second consumer or a version field.
- **pydantic-settings, Typer or cyclopts for argument parsing.** Rejected. The framework would be
  used only as an argv parser, where argparse already covers subparsers, choices and typed values;
  migrating nine stable entry points would churn them for no behaviour change and pull
  `python-dotenv` into the lock for a `.env` story this repo does not have. The duplication that did
  exist was copy-paste, and one module removes it today: [`cli.py`](../../python/scripts/cli.py).
- **Tooling dependencies in the shipped wheel.** Rejected. `stunt_reel` is imported by the offline
  tests, and a dependency there would make them depend on an install decision taken for dev tooling.

## Consequences

The bar is repeated in the README's development section, because a contributor meets it before
this record. `cargo deny` still governs Rust only: the Python bar is checked in review against this
ADR, not by CI. Giving `stunt_reel` a dependency would amend this ADR's first decision, not add to it.
