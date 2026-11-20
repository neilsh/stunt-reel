"""Capture a film with and without PLAYONE's actor shadow call, and diff the pages (#628 journal).

`trees <data root> <out>` copies `<data root>/builds/unpatched` twice into `<out>`: `unpacked`, whose
PLAYONE.EXE is the LZEXE-unpacked MZ file (`mise run unlzexe -- --mz`), and `noshadow`, the same
with the scene walk's `je short 1E38h` at image `0x1E33` made `jmp short` (`0x74` to `0xEB`), so
`0x1E35` never calls the shadow queue `0x19FC`. It prints both SHA-256s.

`capture <tree> <out> [capture-ref options]` runs capture-ref on a tree from `trees`, with both
builds registered at the unpatched build's DGROUP offsets (LZEXE unpacks to the same load
paragraph, so the offsets hold; a wrong DS would fail the capture's composed-page test).

`compare <capture A> <capture B> [lo-hi]` prints, per film tick in both captures (default 800 to
940), each page's palette-index-0 pixels in the 3D view (rows 0 to 184, the clock box at rows 175
and up, columns below 32, left out) as `count@x<min>-<max>,y<min>-<max>`, then the pixels that
differ between the two pages and the A page's indices there.

Usage, from the repository root:
`mise exec -- uv run python work/2026-11/628_high-actor-shadow-pixels/shadow_control.py trees|capture|compare ...`
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import runpy
import shutil
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))

from stunt_reel.tac import playone  # noqa: E402

#: The scene walk's test of `SIF_SHADOW` before the shadow call: `test byte [si+1],4; je 1E38h; call 19FCh`.
SHADOW_TEST = bytes.fromhex("f64401047403e8c4fb")
#: Image offset of the `je` in SHADOW_TEST.
JE_OFFSET = 0x1E33
UNPACKED_SHA256 = "4e68d1007c78a476430cf45d8e31a03c8bebc355d71d4f208c5c64b0abbef83f"
NOSHADOW_SHA256 = "83e814ba55ae9600476b33729fb4de71998a3e2bf8d40301fd7751609170a0e6"
VIEW_ROWS = 185
WIDTH = 320


def trees(data_root: Path, out: Path) -> None:
    """Write the `unpacked` and `noshadow` game trees under *out*."""
    source = data_root / "builds" / "unpatched"
    unpacked = out / "unpacked"
    shutil.copytree(source, unpacked)
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "python" / "scripts" / "unlzexe.py"),
            str(source / "PLAYONE.EXE"),
            str(unpacked / "PLAYONE.EXE"),
            "--mz",
        ],
        check=True,
    )
    noshadow = out / "noshadow"
    shutil.copytree(unpacked, noshadow)
    exe = noshadow / "PLAYONE.EXE"
    image = bytearray(exe.read_bytes())
    at = struct.unpack("<H", image[8:10])[0] * 16 + JE_OFFSET
    if image[at - 4 : at + 5] != SHADOW_TEST:
        raise SystemExit(f"unexpected bytes at file offset {at:#x}: {image[at - 4 : at + 5].hex()}")
    image[at] = 0xEB
    exe.write_bytes(image)
    for tree in (unpacked, noshadow):
        print(tree.name, hashlib.sha256((tree / "PLAYONE.EXE").read_bytes()).hexdigest())


def capture(tree: Path, out: Path, options: list[str]) -> None:
    """Run capture-ref on *tree* into *out* with the two variant builds known."""
    playone.LAYOUTS = (
        *playone.LAYOUTS,
        dataclasses.replace(playone.UNPATCHED, name="unpacked", sha256=UNPACKED_SHA256),
        dataclasses.replace(playone.UNPATCHED, name="noshadow", sha256=NOSHADOW_SHA256),
    )
    script = ROOT / "python" / "scripts" / "capture_playone_reference.py"
    sys.argv = [str(script), "--game-root", str(tree), "--out", str(out), *options]
    runpy.run_path(str(script), run_name="__main__")


def _pages(capture_dir: Path) -> dict[int, bytes]:
    meta = json.loads((capture_dir / "meta.json").read_text(encoding="utf-8"))
    return {f["film_tick"]: (capture_dir / f["frame_file"]).read_bytes() for f in meta["frames"]}


def _extent(points: list[int]) -> str:
    if not points:
        return "0"
    xs = [k % WIDTH for k in points]
    ys = [k // WIDTH for k in points]
    return f"{len(points)}@x{min(xs)}-{max(xs)},y{min(ys)}-{max(ys)}"


def _index0(page: bytes) -> list[int]:
    return [
        k
        for k, v in enumerate(page[: VIEW_ROWS * WIDTH])
        if v == 0 and not (k // WIDTH >= 175 and k % WIDTH < 32)
    ]


def compare(a_dir: Path, b_dir: Path, lo: int, hi: int) -> None:
    """Print each shared tick's index-0 extents and the A-B difference."""
    a, b = _pages(a_dir), _pages(b_dir)
    for tick in sorted(set(a) & set(b)):
        if not lo <= tick <= hi:
            continue
        diff = [k for k in range(len(a[tick])) if a[tick][k] != b[tick][k]]
        values = dict(sorted(Counter(a[tick][k] for k in diff).items()))
        print(
            tick,
            "A",
            _extent(_index0(a[tick])),
            "B",
            _extent(_index0(b[tick])),
            "diff",
            _extent(diff),
            values,
        )


def main(argv: list[str]) -> int:
    """Dispatch the subcommand in `argv[0]`."""
    command, rest = argv[0], argv[1:]
    if command == "trees":
        trees(Path(rest[0]), Path(rest[1]))
    elif command == "capture":
        capture(Path(rest[0]), Path(rest[1]), rest[2:])
    elif command == "compare":
        lo, hi = map(int, (rest[2] if len(rest) > 2 else "800-940").split("-"))
        compare(Path(rest[0]), Path(rest[1]), lo, hi)
    else:
        raise SystemExit(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
