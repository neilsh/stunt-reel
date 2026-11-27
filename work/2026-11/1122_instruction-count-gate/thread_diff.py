"""Print the largest per-function Ir differences between two callgrind_annotate listings (#1122)."""

import re
import sys

LINE = re.compile(r"\s*([\d,]+) \([^)]*\)\s+(.*?) \[")


def load(path: str) -> dict[str, int]:
    found: dict[str, int] = {}
    for line in open(path):
        match = LINE.match(line)
        if match:
            name = match.group(2)
            found[name] = found.get(name, 0) + int(match.group(1).replace(",", ""))
    return found


a, b = load(sys.argv[1]), load(sys.argv[2])
diffs = sorted(((a.get(k, 0) - b.get(k, 0), k) for k in a.keys() | b.keys()), key=lambda d: -abs(d[0]))
print(f"total difference {sum(d for d, _ in diffs):,}")
for d, name in diffs[:15]:
    print(f"{d:>14,} {name[:140]}")
