"""A sweep's figures: the scores behind its verdict, as the TOML file a work folder commits.

``mise run sweep -- --record`` writes one per sweep as ``<work folder>/sweeps/<topic>.toml``, and
``mise run judge -- --recheck`` reads it back, judges it again by :mod:`stunt_reel.parity_judge`
and compares the winner line. :func:`figures_text` words a file, :func:`parse_figures` reads one
and :func:`drift_note` says when today's bounds would give another verdict. Nothing here reads
or writes files.

Per variant and film the file holds the headline scores the table and ranking read, and each
frame the judge keeps from ``report.json``'s ``per_frame`` (the first per ``film_tick``) as
``[film_tick, ssim, index_agreement, scored]``: ``nan`` stands for a missing index agreement,
and a frame without ``scored`` has three elements. Floats are written in full, so a recheck
computes on the very values the sweep did.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Any, TypeIs, cast

from stunt_reel.parity_judge import (
    BASELINE,
    TODAY,
    TRACKS,
    Bounds,
    Decision,
    FilmRun,
    Frame,
    Headline,
    Target,
    Track,
    Variant,
    decide,
    label,
    winner_line,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = [
    "SCHEMA",
    "Figures",
    "FiguresError",
    "RecordedScore",
    "drift_note",
    "figures_text",
    "parse_figures",
]

#: The layout version a figures file states; :func:`parse_figures` reads only this one.
SCHEMA = 1

_BARE_KEY = re.compile(r"[A-Za-z0-9_-]+")


class FiguresError(ValueError):
    """A figures file that cannot be read back; the message names what is wrong."""


@dataclass(frozen=True)
class RecordedScore:
    """A film's headline scores as a figures file records them."""

    ssim: float
    iou: float
    actor_iou: float | None = None


@dataclass(frozen=True)
class Figures:
    """One sweep's figures: its variants' scores, how it judged them, and its winner line."""

    #: The ``--var`` names, in the sweep's order.
    names: tuple[str, ...]
    #: The films of the table, in its column order.
    films: tuple[str, ...]
    #: ``--probe``: ``film`` or ``iou``.
    probe: str
    track: Track | None
    targets: tuple[Target, ...]
    #: The bounds the sweep's verdict applied.
    bounds: Bounds
    variants: tuple[Variant, ...]
    #: The winner line the sweep printed, without ``--keep-best``'s ``; kept`` note.
    winner: str

    def decision(self, bounds: Bounds | None = None) -> Decision:
        """The variants judged again, by *bounds* or else by the recorded ones."""
        return decide(
            self.variants, self.targets, self.track, self.bounds if bounds is None else bounds
        )


def figures_text(
    names: Sequence[str], films: Sequence[str], decision: Decision, probe: str, winner: str
) -> str:
    """The figures file of a sweep that printed *winner* for *decision*."""
    lines = [
        "# The figures behind one `mise run sweep` verdict, written by its --record.",
        "# `mise run judge -- --recheck <this file>` judges them again and compares the winner.",
        "# A frame is [film_tick, ssim, index_agreement, scored]: index_agreement is nan and",
        "# scored absent where the report gave none.",
        f"schema = {SCHEMA}",
        f"names = {_strings(names)}",
        f"films = {_strings(films)}",
        f"probe = {_string(probe)}",
    ]
    if decision.track is not None:
        lines.append(f"track = {_string(decision.track)}")
    lines.append(f"targets = {_strings(t.spec() for t in decision.targets)}")
    base = next((v for v in decision.ordered if v.index == BASELINE), None)
    if base is not None:
        lines.append(f"baseline = {_string(label(names, base.values))}")
    lines.append(f"winner = {_string(winner)}")
    lines += ["", "[bounds]"]
    lines += [f"{f.name} = {getattr(decision.bounds, f.name)!r}" for f in fields(Bounds)]
    for variant in sorted(decision.ordered, key=lambda v: v.index):
        lines += ["", "[[variant]]", f"index = {variant.index}"]
        lines.append(f"values = {_strings(variant.values)}")
        for film in dict.fromkeys([*variant.scores, *variant.frames]):
            lines += ["", f"[variant.film.{_key(film)}]"]
            lines += _film_lines(variant.scores.get(film), variant.frames.get(film))
    return "\n".join(lines) + "\n"


def _film_lines(score: Headline | None, run: FilmRun | None) -> list[str]:
    if score is None and run is None:
        return ["failed = true"]
    lines = []
    if score is not None:
        lines += [f"ssim = {_number(score.ssim)}", f"iou = {_number(score.iou)}"]
        if score.actor_iou is not None:
            lines.append(f"actor_iou = {_number(score.actor_iou)}")
    if run is not None:
        lines.append(f"fade_aware = {_bool(run.fade_aware)}")
        lines.append("frames = [")
        lines += [f"  {_row(tick, frame)}," for tick, frame in run.frames.items()]
        lines.append("]")
    return lines


def _row(tick: int, frame: Frame) -> str:
    cells = [str(tick), _number(frame.ssim), "nan" if frame.index is None else _number(frame.index)]
    if frame.scored is not None:
        cells.append(_bool(frame.scored))
    return "[" + ", ".join(cells) + "]"


def _number(value: float) -> str:
    """*value* as a TOML float that reads back as the same float (``repr``: ``nan``, ``inf``)."""
    return repr(float(value))


def _bool(value: bool) -> str:
    return "true" if value else "false"


def _string(text: str) -> str:
    """*text* as a TOML basic string; JSON's escapes are a subset of TOML's."""
    return json.dumps(text)


def _strings(texts: Iterable[str]) -> str:
    return "[" + ", ".join(_string(t) for t in texts) + "]"


def _key(name: str) -> str:
    return name if _BARE_KEY.fullmatch(name) else _string(name)


def parse_figures(text: str) -> Figures:
    """The figures *text* holds; raises :class:`FiguresError` naming the first thing wrong."""
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise FiguresError(f"not TOML: {err}") from err
    if document.get("schema") != SCHEMA:
        raise FiguresError(f"schema is {document.get('schema')!r}, not {SCHEMA}")
    names = _texts(document, "names")
    track = document.get("track")
    if track is not None and track not in TRACKS:
        raise FiguresError(f"track {track!r} is none of {', '.join(TRACKS)}")
    try:
        targets = tuple(Target.parse(spec) for spec in _texts(document, "targets"))
    except ValueError as err:
        raise FiguresError(str(err)) from err
    variants = tuple(
        _variant(table, len(names)) for table in _tables(document.get("variant", []), "variant")
    )
    base = next((v for v in variants if v.index == BASELINE), None)
    recorded = document.get("baseline")
    if base is not None and recorded is not None and recorded != label(names, base.values):
        raise FiguresError(f"baseline {recorded!r} is not variant {BASELINE}'s values")
    return Figures(
        names=names,
        films=_texts(document, "films"),
        probe=_text(document, "probe"),
        track=cast("Track | None", track),
        targets=targets,
        bounds=_bounds(document.get("bounds")),
        variants=variants,
        winner=_text(document, "winner"),
    )


def drift_note(figures: Figures) -> str | None:
    """A note when today's bounds would give *figures* another verdict than the recorded ones.

    The verdict is which variant wins, if any; ``None`` when the bounds or the verdict agree.
    """
    if figures.bounds == TODAY:
        return None
    then, now = figures.decision(), figures.decision(TODAY)
    if _verdict(then) == _verdict(now):
        return None
    changed = ", ".join(
        f"{f.name} {getattr(TODAY, f.name)} (recorded {getattr(figures.bounds, f.name)})"
        for f in fields(Bounds)
        if getattr(TODAY, f.name) != getattr(figures.bounds, f.name)
    )
    return f"today's bounds ({changed}) give another verdict: {winner_line(figures.names, now)}"


def _verdict(decision: Decision) -> tuple[int | None, str | None]:
    return (None if decision.winner is None else decision.winner.index, decision.no_verdict)


def _variant(table: dict[str, Any], names: int) -> Variant:
    index = table.get("index")
    if not _is_int(index) or index < 1:
        raise FiguresError(f"variant index {index!r} is not a whole number from 1")
    values = _texts(table, "values")
    if len(values) != names:
        raise FiguresError(f"variant {index} has {len(values)} values for {names} names")
    variant = Variant(index, values, {})
    films = table.get("film", {})
    if not isinstance(films, dict):
        raise FiguresError(f"variant {index}'s film is not a table")
    for film, entry in films.items():
        if not isinstance(entry, dict):
            raise FiguresError(f"variant {index} film {film} is not a table")
        try:
            variant.scores[film], variant.frames[film] = _score(entry), _run(entry)
        except FiguresError as err:
            raise FiguresError(f"variant {index} film {film}: {err}") from err
    return variant


def _score(entry: dict[str, Any]) -> RecordedScore | None:
    if "ssim" not in entry:
        return None
    actor = entry.get("actor_iou")
    return RecordedScore(
        _float(entry, "ssim"),
        _float(entry, "iou"),
        None if actor is None else _float(entry, "actor_iou"),
    )


def _run(entry: dict[str, Any]) -> FilmRun | None:
    if "frames" not in entry:
        return None
    fade_aware = entry.get("fade_aware")
    if not isinstance(fade_aware, bool):
        raise FiguresError("fade_aware is not true or false")
    rows = entry["frames"]
    if not isinstance(rows, list):
        raise FiguresError("frames is not an array")
    frames: dict[int, Frame] = {}
    for row in rows:
        tick, frame = _frame(row)
        if tick in frames:
            raise FiguresError(f"tick {tick} is listed twice")
        frames[tick] = frame
    return FilmRun(frames, fade_aware)


def _frame(row: object) -> tuple[int, Frame]:
    if not isinstance(row, list) or len(row) not in (3, 4):
        raise FiguresError(f"frame {row!r} is not [film_tick, ssim, index_agreement, scored]")
    tick, ssim, index, *rest = row
    scored = rest[0] if rest else None
    if not (
        _is_int(tick)
        and _is_number(ssim)
        and _is_number(index)
        and (scored is None or isinstance(scored, bool))
    ):
        raise FiguresError(f"frame {row!r} is not [film_tick, ssim, index_agreement, scored]")
    agreement = None if math.isnan(index) else float(index)
    return tick, Frame(float(ssim), agreement, scored)


def _bounds(table: object) -> Bounds:
    """Every :class:`Bounds` field, and no other key: a missing bound is never today's."""
    if not isinstance(table, dict):
        raise FiguresError("bounds is not a table")
    names = [f.name for f in fields(Bounds)]
    odd = sorted(set(names) ^ set(table))
    if odd:
        raise FiguresError(f"bounds {'lacks' if odd[0] in names else 'has an unknown'} {odd[0]}")
    values: dict[str, Any] = {}
    for name in names:
        value = table[name]
        whole = name == "min_target_frames"
        if not (_is_int(value) if whole else _is_number(value)):
            raise FiguresError(f"bound {name} is {value!r}")
        values[name] = value if whole else float(value)
    return Bounds(**values)


def _tables(value: object, key: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
        raise FiguresError(f"{key} is not an array of tables")
    return cast("list[dict[str, Any]]", value)


def _text(table: dict[str, Any], key: str) -> str:
    value = table.get(key)
    if not isinstance(value, str):
        raise FiguresError(f"{key} is {value!r}, not text")
    return value


def _texts(table: dict[str, Any], key: str) -> tuple[str, ...]:
    value = table.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise FiguresError(f"{key} is {value!r}, not an array of text")
    return tuple(value)


def _float(table: dict[str, Any], key: str) -> float:
    value = table.get(key)
    if not _is_number(value):
        raise FiguresError(f"{key} is {value!r}, not a number")
    return float(value)


def _is_int(value: object) -> TypeIs[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> TypeIs[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)
