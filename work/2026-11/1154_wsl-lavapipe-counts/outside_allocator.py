"""Print each Cachegrind file's total Ir, and its Ir outside glibc's malloc.c and memmove (#1122)."""

import lzma
import sys
from pathlib import Path


ALLOCATOR = ("/malloc/malloc.c", "memmove-vec-unaligned-erms.S")


def totals(path: Path) -> tuple[int, int]:
    total = malloc = 0
    in_malloc = False
    text = lzma.open(path, "rt", errors="replace").read() if path.suffix == ".xz" else path.read_text()
    for line in text.splitlines():
        if line.startswith("fl="):
            in_malloc = any(name in line for name in ALLOCATOR)
        elif line[:1].isdigit():
            parts = line.split()
            if len(parts) > 1:
                total += int(parts[1])
                if in_malloc:
                    malloc += int(parts[1])
    return total, total - malloc


for name in sys.argv[1:]:
    total, rest = totals(Path(name))
    print(f"{Path(name).name.removesuffix('.xz')}: total {total:,} outside malloc.c and memmove {rest:,}")
