"""List the `GVPOLY` polygons in a `mise run debug-x` JSONL, by object and ramp base.

`mise run gvpoly-stream -- <jsonl> [--handlers 0x995C,0x9A24] [--json out.json]` decodes the
`mem:ES:SI:40` capture of every hit whose `cs_ip_image` is a `GVPOLY` handler. The defaults are
the unpatched build's handler offsets; for a patched run, pass that build's offsets to
`--handlers`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

from stunt_reel.gvpoly_stream import Polygon, decode_record

DEFAULT_HANDLERS = "0x995C,0x9A24"
CAPTURE = "mem:ES:SI:40"


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("jsonl", type=Path)
    parser.add_argument("--handlers", default=DEFAULT_HANDLERS, help="GVPOLY handler image offsets")
    parser.add_argument("--json", type=Path, help="write every polygon here")
    return parser.parse_args(argv)


def polygons(rows: list[dict[str, object]], handlers: set[int]) -> dict[int, list[Polygon]]:
    """Decoded records by object segment (`ES`), in hit order, duplicates (same address) dropped."""
    by_es: dict[int, dict[int, Polygon]] = defaultdict(dict)
    for row in rows:
        mem = row.get("mem")
        regs = row.get("regs")
        if row.get("type") != "hit" or row.get("cs_ip_image") not in handlers:
            continue
        if not isinstance(mem, dict) or not isinstance(regs, dict) or CAPTURE not in mem:
            continue
        linear = regs["es"] * 16 + regs["si"]
        poly = decode_record(bytes.fromhex(mem[CAPTURE]), linear, int(str(row["cs_ip_image"])))
        if poly is not None:
            by_es[regs["es"]].setdefault(linear, poly)
    return {es: list(polys.values()) for es, polys in by_es.items()}


def main(argv: list[str] | None = None) -> int:
    """Print a per-object, per-base count of `GVPOLY` polygons."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    handlers = {int(h, 0) for h in args.handlers.split(",")}
    rows = [
        json.loads(line) for line in args.jsonl.read_text(encoding="utf-8").splitlines() if line
    ]
    found = polygons(rows, handlers)
    total: Counter[int] = Counter()
    for es, polys in sorted(found.items()):
        bases = Counter(p.base for p in polys)
        total.update(bases)
        print(
            f"{es:04X}: {len(polys)} polygons; "
            + ", ".join(f"{c:#04x} x{n}" for c, n in sorted(bases.items()))
        )
    print("all: " + ", ".join(f"{c:#04x} x{n}" for c, n in sorted(total.items())))
    if args.json is not None:
        out = {f"{es:04X}": [asdict(p) for p in polys] for es, polys in found.items()}
        args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
