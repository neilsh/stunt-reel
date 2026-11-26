"""Runs the #1090 placement-cut probe over reference films and prints each film's probe line.

Throwaway: needs the release binary built with ``world-cuts-probe.patch``. Each film runs with
the parity render's own arguments (``parity_pipeline.render_film``) and ``DBG_PROBE_WORLD_CUTS``
set, so the binary counts the world's placements with triangles in the shared ``WORLD_BASE`` and
``WORLD_DECAL`` slices and returns before any renderer opens. Usage:
``mise exec -- uv run python <this> <data root> <out file> [film ...]`` (default: all seven).
"""

import os
import sys
import tempfile
from pathlib import Path

from stunt_reel import parity_pipeline

FILMS = ("ctry", "intro", "land", "balloon", "traintnl", "bomb", "location")


def run_film(root: Path, name: str) -> list[str]:
    """Probes one film and returns its argv line and the binary's probe lines."""
    lines: list[str] = []

    def run(argv, env, timeout):
        code, tail = parity_pipeline.run_command(argv, env, timeout)
        lines.append(f"[{name}] exit {code}")
        lines.append(" ".join(Path(a).name if os.sep in a or "/" in a else a for a in argv))
        lines.extend(f"[{name}] {x.rstrip()}" for x in tail.splitlines() if "[probe1090]" in x)
        return code, tail

    env = {**os.environ, "DBG_PROBE_WORLD_CUTS": "1"}
    with parity_pipeline.reference_job(root, name) as job, tempfile.TemporaryDirectory() as tmp:
        parity_pipeline.render_film(job, Path(tmp) / "render", env, run=run)
    return lines


def main() -> None:
    root, out = Path(sys.argv[1]), Path(sys.argv[2])
    films = sys.argv[3:] or list(FILMS)
    log: list[str] = []
    for name in films:
        log += run_film(root, name)
    out.write_text("\n".join(log) + "\n", encoding="utf-8")
    print("\n".join(log))


if __name__ == "__main__":
    main()
