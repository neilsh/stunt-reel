#!/usr/bin/env python3
"""Check one .glb with no GPU: the Khronos glTF validator, then one PNG render.

The validator is ``tools/glb-check/validate.mjs`` (npm ``gltf-validator``, pinned in its
``package.json``). The render is Blender in background mode on the CPU (``render_blender.py``),
or F3D (``--renderer f3d``, which takes the same ``--time``; without DISPLAY it runs under Xvfb). Both read only the file named,
so pass a ``.glb`` you made or trust: a glb is parsed by the renderer.

Usage: ``mise run glb-check -- <file.glb> [--out DIR] [--time SECONDS] [--renderer blender|f3d]
[--validate-only]``. Writes ``<out>/<stem>.png`` and ``<out>/<stem>.validation.json``, default
``build/glb-check/``.

Exit status: 0 when the file validates with no errors and renders; 1 when the validator
reports an error or a renderer fails; 2 on a usage or missing-tool error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tools" / "glb-check"


def _run(argv: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Runs *argv* from the repo root, streaming its output unless *capture* is set."""
    print("+ " + " ".join(argv), flush=True)
    return subprocess.run(  # noqa: S603 - argv is a resolved tool path and the file the user named
        argv, cwd=REPO_ROOT, text=True, capture_output=capture, check=False
    )


def validate(glb: Path, out: Path) -> int:
    """Runs the validator, writes its JSON to *out*, and returns 0 with no errors, 1 with errors, 2 when it cannot run."""
    node = shutil.which("node")
    if node is None:
        print("glb-check: node is not on PATH", file=sys.stderr)
        return 2
    if not (TOOL_DIR / "node_modules" / "gltf-validator").is_dir():
        print(f"glb-check: run `npm ci` in {TOOL_DIR} first", file=sys.stderr)
        return 2
    done = _run([node, str(TOOL_DIR / "validate.mjs"), str(glb)], capture=True)
    if done.returncode == 2:
        print(done.stderr, file=sys.stderr)
        return 2
    try:
        report = json.loads(done.stdout)
    except json.JSONDecodeError:
        print(
            f"glb-check: the validator printed no report for {glb}:\n{done.stderr}", file=sys.stderr
        )
        return 2
    out.write_text(done.stdout)
    print(
        f"validation: {out}: {report['numErrors']} errors, {report['numWarnings']} warnings, "
        f"{report['numInfos']} infos, {report['numHints']} hints"
    )
    return done.returncode


def render(glb: Path, png: Path, seconds: float, renderer: str) -> int:
    """Renders *glb* at *seconds* into *png* with the chosen renderer."""
    if renderer == "blender":
        blender = shutil.which("blender")
        if blender is None:
            print("glb-check: blender is not on PATH (apt-get install blender)", file=sys.stderr)
            return 2
        argv = [
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "-P",
            str(TOOL_DIR / "render_blender.py"),
            "--",
            str(glb),
            str(png),
            str(seconds),
        ]
    else:
        f3d = shutil.which("f3d")
        if f3d is None:
            print("glb-check: f3d is not on PATH (apt-get install f3d)", file=sys.stderr)
            return 2
        argv = [
            f3d,
            str(glb),
            f"--output={png}",
            f"--animation-time={seconds}",
            "--resolution=960,720",
            "--no-background",
        ]
        # F3D needs an X server even to render offscreen: without DISPLAY it segfaults, so use Xvfb.
        if not os.environ.get("DISPLAY"):
            xvfb = shutil.which("xvfb-run")
            if xvfb is None:
                print(
                    "glb-check: F3D needs DISPLAY or xvfb-run (apt-get install xvfb)",
                    file=sys.stderr,
                )
                return 2
            argv = [xvfb, "-a", "-s", "-screen 0 1280x1024x24", *argv]
    return _run(argv).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("glb", type=Path, help="the .glb file to check")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "build" / "glb-check")
    parser.add_argument(
        "--time", type=float, default=0.0, help="animation time in seconds (default 0)"
    )
    parser.add_argument("--renderer", choices=("blender", "f3d"), default="blender")
    parser.add_argument("--validate-only", action="store_true", help="skip the render")
    args = parser.parse_args(argv)

    if not (args.time >= 0 and args.time < float("inf")):
        print(f"glb-check: --time must be a finite number >= 0, not {args.time}", file=sys.stderr)
        return 2
    glb = args.glb.resolve()
    if not glb.is_file() or glb.suffix.lower() != ".glb":
        print(f"glb-check: {args.glb} is not a .glb file", file=sys.stderr)
        return 2
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / glb.stem
    status = validate(glb, Path(f"{stem}.validation.json"))
    if status == 2:
        return 2
    if status not in (0, 1):
        return 2
    if args.validate_only:
        return status
    png = Path(f"{stem}.png")
    png.unlink(missing_ok=True)
    rendered = render(glb, png, args.time, args.renderer)
    if rendered == 0 and not png.is_file():
        print(f"glb-check: the renderer exited 0 but wrote no {png}", file=sys.stderr)
        rendered = 1
    if rendered == 2:
        return 2
    if rendered != 0:
        print(f"glb-check: render failed with exit {rendered}", file=sys.stderr)
        return 1
    print(f"glb-check: {png}")
    return status


if __name__ == "__main__":
    sys.exit(main())
