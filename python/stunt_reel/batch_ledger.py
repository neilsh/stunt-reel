"""The batch survey's ledger: one JSON line per stage outcome, so a rerun resumes where it stopped.

A film's stages are ``archive``, ``capture``, ``render`` and ``score``. The ledger is append-only;
the latest line for a film and stage is its current state. Nothing here runs a stage or touches
the corpus: it only records outcomes and reads them back.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["STAGES", "Record", "append", "latest", "read", "summarize"]

#: The stages of one film, in the order the batch runs them.
STAGES = ("archive", "capture", "render", "score")

#: How many SSIM extremes the summary lists on each side.
_EXTREMES = 5


@dataclass(frozen=True)
class Record:
    """The outcome of one stage of one film; ``status`` is ``ok``, ``error`` or ``skipped``."""

    slug: str
    stage: str
    status: str
    message: str
    seconds: float
    at: str
    ssim: float | None = None
    iou: float | None = None


def append(path: Path, record: Record) -> None:
    """Add *record* as one JSON line at the end of the ledger at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(record), sort_keys=True) + "\n")


def read(path: Path) -> list[Record]:
    """Every record in the ledger at *path*, oldest first; a malformed line is skipped."""
    if not path.exists():
        return []
    records: list[Record] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            records.append(Record(**json.loads(line)))
        except (ValueError, TypeError):
            continue
    return records


def latest(records: list[Record], slug: str, stage: str) -> Record | None:
    """The most recent record for *slug* at *stage*, or ``None`` when it has never run."""
    for record in reversed(records):
        if record.slug == slug and record.stage == stage:
            return record
    return None


def summarize(records: list[Record]) -> str:
    """Counts per stage, the still-failing stages, and the SSIM extremes of the latest scores."""
    latest_by_key: dict[tuple[str, str], Record] = {}
    for record in records:
        latest_by_key[(record.slug, record.stage)] = record
    counts: dict[str, Counter[str]] = {stage: Counter() for stage in STAGES}
    for (_, stage), record in latest_by_key.items():
        counts.setdefault(stage, Counter())[record.status] += 1

    lines = ["stage      ok  error  skipped"]
    for stage, tally in counts.items():
        lines.append(f"{stage:<10} {tally['ok']:>2}  {tally['error']:>5}  {tally['skipped']:>7}")

    failing = sorted(key for key, record in latest_by_key.items() if record.status == "error")
    if failing:
        lines.append("")
        lines.append("still failing (slug  stage  message):")
        for slug, stage in failing:
            lines.append(f"{slug}  {stage}  {latest_by_key[(slug, stage)].message}")

    scored = sorted(
        (
            record
            for (_, stage), record in latest_by_key.items()
            if stage == "score" and record.status == "ok" and record.ssim is not None
        ),
        key=lambda record: (record.ssim or 0.0, record.slug),
    )
    if scored:
        lines.append("")
        lines.append("lowest ssim:")
        lines.extend(f"  {record.ssim:.4f}  {record.slug}" for record in scored[:_EXTREMES])
        lines.append("highest ssim:")
        highest = scored[::-1][:_EXTREMES]
        lines.extend(f"  {record.ssim:.4f}  {record.slug}" for record in highest)
    return "\n".join(lines)
