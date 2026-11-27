# stunt_reel is repo-internal tooling and may take dev dependencies

## Status

accepted 2026-11-27, on the owner's decision in [#1051](https://github.com/neilsh/stunt-reel/issues/1051#issuecomment-7212035374) (Option B), for [#1170](https://github.com/neilsh/stunt-reel/issues/1170).
Amends the first decision of [ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) for `python/stunt_reel`: the package may take dev-group dependencies, and its shipped wheel keeps none.

## Context

[ADR 0010](0010-python-scripts-may-take-well-established-dependencies.md) keeps `python/stunt_reel` free of runtime dependencies, because it is the shipped package and the offline capture harness, and it reserves the dev group for `python/scripts/`.
Its Consequences say that giving `stunt_reel` a dependency would amend that first decision.
This record does so.

Eight modules under [`python/stunt_reel/bench/`](../../python/stunt_reel/bench/) import numpy or PIL: `faults`, `metrics`, `mismatch`, `panels`, `planes`, `run`, `sheets` and `ssim`.
All eight import numpy at run time.
`sheets.py` imports PIL at run time, and `panels.py` imports it only under `TYPE_CHECKING`.
The bench tests reach both packages through the dev group, and [`pyproject.toml`](../../pyproject.toml) lists `numpy>=2.5` and `pillow>=13` there.
[#1051](https://github.com/neilsh/stunt-reel/issues/1051) recorded that as drift from ADR 0010, not as a decision.

Moving `bench/` out of the package would not remove either import.
No workflow publishes the wheel: nothing under `.github/` or in `mise.toml` uploads one to an index, so a move would change where the code lives without changing what anyone installs.

## Decision

* **`python/stunt_reel` may take dependencies in the dev group.**
  It starts with numpy and Pillow, which `bench/` imports.
* **The shipped wheel keeps no runtime dependencies.**
  `dependencies = []` in [`pyproject.toml`](../../pyproject.toml) stays, and a runtime dependency needs its own record.
* **ADR 0010's two tiers are the bar.**
  A dependency in either package clears the checks and the record that ADR 0010 sets for `python/scripts/`.
  This record adds no version gate and no transitive-count gate.

### Admitting record for numpy and Pillow

Each package is recorded against the two tiers.

* **numpy 2.5.4**, dev group.
  Job: array arithmetic for the SSIM and the comparison planes (`bench/ssim.py`, `bench/metrics.py`, `bench/planes.py`).
  The standard library has no vectorised array type, so the same SSIM would be a per-pixel Python loop.
  Dependency tree: no dependencies of its own in `uv.lock`.
  Licence: BSD-3-Clause, with bundled components under other permissive licences.
  Wheels: `cp315` wheels for `manylinux` x86_64 and `win_amd64`, the Linux and Windows runners CI uses; it ships `py.typed`.
  Release: uploaded 2026-10-10, as `uv.lock` records.
* **Pillow 13.0.0**, dev group.
  Job: builds the comparison sheets and panels (`bench/sheets.py`, `bench/panels.py`).
  The standard library has no PNG writer and no font rasterizer.
  Dependency tree: no dependencies of its own in `uv.lock`.
  Licence: MIT-CMU.
  Wheels: `cp315` wheels for `manylinux` x86_64 and `win_amd64`; it ships `py.typed`.
  Release: uploaded 2026-10-16, as `uv.lock` records.

The two scripts that import numpy or PIL, `python/scripts/parity_probe.py` and `python/scripts/shape_diff.py`, use the same dev-group entries, and this record covers them too.

## Considered Options

* **Keep ADR 0010 as written and move `bench/` out.** Rejected. It was option A in [#1051](https://github.com/neilsh/stunt-reel/issues/1051). Both imports stay, and no installed artifact changes.
* **List numpy and Pillow as runtime dependencies.** Rejected. ADR 0010 keeps the installed package free of them, and the owner's decision asks only for the dev group.

## Consequences

* ADR 0010's first decision now reads as this record amends it: the shipped wheel keeps no runtime dependencies, and `python/stunt_reel` may take dev-group dependencies that clear the two tiers.
* The wheel still declares no dependencies, but it ships `bench/`, whose modules import numpy when imported.
  A bare install of the wheel therefore cannot import the eight `stunt_reel.bench` modules that import numpy, such as `ssim` and `sheets`.
  This was read from the code and the metadata, not run.
  No workflow installs the wheel, so nothing exercises that path.
* `pyproject.toml` lists numpy and Pillow without a comment naming this record.
  Nothing in it contradicts the record, so it is unchanged.
