"""A graded run's readout, its comparison with an earlier one, and its table row.

:func:`readout` scores a run's real sheets per category; :func:`compare` reports the categories
whose clear-frame count moved by at least the taxonomy's ``min_change`` and :func:`suppressed`
the smaller moves it hides; :func:`table_row` writes one row of ``research/parity/batch.md``'s table.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.bench.grades import CLEAR, SheetGrades, _note
from stunt_reel.bench.planes import BenchError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from stunt_reel.bench.sheets import Sheet
    from stunt_reel.parity_artifacts import Report

__all__ = [
    "CategoryReadout",
    "Change",
    "Comparison",
    "Readout",
    "compare",
    "readout",
    "suppressed",
    "suppressed_line",
    "table_row",
]


@dataclass(frozen=True)
class CategoryReadout:
    """One category over a run's real frames."""

    category: str
    ticks_2plus: tuple[int, ...]
    mean: float | None
    ungraded: int


@dataclass(frozen=True)
class Readout:
    """What the grader saw on a run's real frames, and which render and categories it graded."""

    film: str
    ticks: tuple[int, ...]
    categories_digest: str
    render_digest: str
    categories: tuple[CategoryReadout, ...]
    other: dict[int, str]
    missing: int
    unknown: tuple[str, ...]
    #: Sheets the two passes disagreed on, scored from the tie-break (0 for a single pass).
    disputed: int = 0
    #: Undisputed sheets the tie-break graded because their index mismatch passed
    #: ``ROUTE_MISMATCH`` (#1117); 0 in readouts made before it.
    routed: int = 0
    #: How each page was paired with its render: ``render_tick`` (the scorer's pairing, #1172) or
    #: ``tag`` (the page's own tick, every readout made before it). Readouts with different
    #: pairings are not comparable.
    pairing: str = "tag"

    def to_json(self) -> dict[str, Any]:
        """The ``readout.json`` document."""
        document = asdict(self)
        document["other"] = {str(tick): note for tick, note in self.other.items()}
        return document

    @classmethod
    def from_json(cls, doc: dict[str, Any]) -> Readout:
        """Read a ``readout.json`` document."""
        try:
            return cls(
                film=str(doc["film"]),
                ticks=tuple(int(t) for t in doc["ticks"]),
                categories_digest=str(doc["categories_digest"]),
                render_digest=str(doc["render_digest"]),
                categories=tuple(
                    CategoryReadout(
                        category=str(c["category"]),
                        ticks_2plus=tuple(int(t) for t in c["ticks_2plus"]),
                        mean=None if c["mean"] is None else float(c["mean"]),
                        ungraded=int(c["ungraded"]),
                    )
                    for c in doc["categories"]
                ),
                other={int(tick): str(note) for tick, note in doc["other"].items()},
                missing=int(doc["missing"]),
                unknown=tuple(str(u) for u in doc["unknown"]),
                disputed=int(doc.get("disputed", 0)),
                routed=int(doc.get("routed", 0)),
                pairing=str(doc.get("pairing", "tag")),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise BenchError(f"not a readout document: {err}") from err


#: Frames graded 2+ that make a category a lead in the batch table: the readout's noise is up to
#: 3 frames per category (research/parity/batch.md § 4).
LEAD_FRAMES = 3

#: The header of the readout table in research/parity/batch.md; ``table_row`` fills its rows.
TABLE_HEADER = (
    "| Film | Ticks | Graded | Categories graded 2+ (frames) | `other` notes "
    "| SSIM (scored frames) |\n|---|---|---|---|---|---|"
)


def table_row(result: Readout, report: Report | None, lead: int = LEAD_FRAMES) -> str:
    """*result*'s row in the batch readout table, its SSIM from the film's ``report.json``."""
    leads = sorted(
        (c for c in result.categories if len(c.ticks_2plus) >= lead),
        key=lambda c: -len(c.ticks_2plus),
    )
    named = ", ".join(f"`{c.category}` {len(c.ticks_2plus)}" for c in leads) or "none"
    # A category the grader skipped reads as clean unless the row says so.
    ungraded = ", ".join(f"`{c.category}` {c.ungraded}" for c in result.categories if c.ungraded)
    if ungraded:
        named += f"; ungraded {ungraded}"
    ssim = "n/a"
    if report is not None and report.mean_ssim_scored is not None:
        ssim = f"{report.mean_ssim_scored:.3f} ({report.scored_frames})"
    # batch.md writes tick ranges with an en dash.
    span = f"{min(result.ticks)}–{max(result.ticks)}" if result.ticks else "n/a"  # noqa: RUF001
    graded = len(result.ticks) - result.missing
    return f"| `{result.film}` | {span} | {graded} | {named} | {len(result.other)} | {ssim} |"


def readout(
    grades: dict[str, SheetGrades],
    sheets: Sequence[Sheet],
    ids: Sequence[str],
    film: str,
    categories_digest: str,
    render_digest: str,
) -> Readout:
    """Per category, the real frames graded 2 or more and the mean grade."""
    real = sorted((s for s in sheets if s.kind == "real"), key=lambda s: s.tick)
    graded = [(s.tick, grades[s.id]) for s in real if s.id in grades]
    categories = []
    for name in ids:
        values = [(tick, g.grades.get(name)) for tick, g in graded]
        known = [v for _, v in values if v is not None]
        categories.append(
            CategoryReadout(
                category=name,
                ticks_2plus=tuple(t for t, v in values if v is not None and v >= CLEAR),
                mean=sum(known) / len(known) if known else None,
                ungraded=sum(1 for _, v in values if v is None),
            )
        )
    return Readout(
        film=film,
        ticks=tuple(s.tick for s in real),
        categories_digest=categories_digest,
        render_digest=render_digest,
        categories=tuple(categories),
        other={tick: _note(g) for tick, g in graded if _note(g)},
        missing=len(real) - len(graded),
        unknown=tuple(sorted({name for _, g in graded for name in g.unknown})),
    )


@dataclass(frozen=True)
class Change:
    """A category whose count of frames graded 2+ moved between two readouts."""

    category: str
    before: int
    after: int
    added: tuple[int, ...]
    removed: tuple[int, ...]


@dataclass(frozen=True)
class Comparison:
    """A readout's comparison: the moves past ``min_change`` and the smaller ones it hides."""

    changes: list[Change]
    suppressed: list[Change]
    min_change: int


def _moves(before: Readout, after: Readout) -> list[Change]:
    """Every category whose 2+ count differs, in category order.

    Raises ``BenchError`` if category digests or ticks differ, or either readout has missing sheets.
    """
    if before.categories_digest != after.categories_digest:
        raise BenchError(
            f"readouts graded different categories ({before.categories_digest} before, "
            f"{after.categories_digest} now); calibrate and start a new series"
        )
    if before.ticks != after.ticks:
        only_before = sorted(set(before.ticks) - set(after.ticks))
        only_after = sorted(set(after.ticks) - set(before.ticks))
        raise BenchError(
            f"readouts graded different ticks (only before: {only_before}, only now: {only_after})"
        )
    if before.missing or after.missing:
        raise BenchError(
            f"a readout is missing sheets ({before.missing} before, {after.missing} now); "
            "grade the missing sheets before comparing"
        )
    earlier = {c.category: set(c.ticks_2plus) for c in before.categories}
    moves = []
    for category in after.categories:
        was, now = earlier.get(category.category, set()), set(category.ticks_2plus)
        if len(now) != len(was):
            moves.append(
                Change(
                    category.category,
                    len(was),
                    len(now),
                    tuple(sorted(now - was)),
                    tuple(sorted(was - now)),
                )
            )
    return moves


def compare(before: Readout, after: Readout, min_change: int) -> list[Change]:
    """Categories whose 2+ count moved by at least *min_change*.

    Raises ``BenchError`` if category digests or ticks differ, or either readout has missing sheets.
    """
    return [c for c in _moves(before, after) if abs(c.after - c.before) >= min_change]


def suppressed(before: Readout, after: Readout, min_change: int) -> list[Change]:
    """Categories whose 2+ count moved, but by less than *min_change*, so :func:`compare` omits them.

    Raises ``BenchError`` as :func:`compare` does.
    """
    return [c for c in _moves(before, after) if abs(c.after - c.before) < min_change]


def suppressed_line(film: str, moves: list[Change], min_change: int, limit: int = 10) -> str:
    """One line naming *moves* as ``<film> <category> <before>→<after>``, *limit* at most."""
    shown = [f"{film} {c.category} {c.before}→{c.after}" for c in moves[:limit]]
    if len(moves) > limit:
        shown.append(f"… and {len(moves) - limit} more")
    return f"below min_change ({min_change}): {', '.join(shown) or 'none'}"
