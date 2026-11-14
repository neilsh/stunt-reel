"""Which comparison pictures a targeted sweep draws, and what they are called.

``mise run sweep --images`` shows the winner against the baseline on a few ticks (spec
``work/2026-11/440_target-frame-adoption/spec.md`` § 4). :func:`choose_ticks` picks them from the
target frames, :func:`guard_pictures` adds each film's worst frame, and :func:`plan_pictures`
names them. The ticks are chosen by whole-frame SSIM change, the per-frame guard's metric, not
the target metric. Nothing here renders, draws or prints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from stunt_reel.parity_judge import LISTED

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from pathlib import Path

    from stunt_reel.parity_judge import Delta, Judgement

__all__ = [
    "CROP_SCALE",
    "MAX_PER_FILM",
    "MIN_SPACING",
    "SCREEN_HEIGHT",
    "SCREEN_WIDTH",
    "SPACING",
    "Picture",
    "choose_ticks",
    "existing_paths",
    "films_with",
    "guard_pictures",
    "parse_crop",
    "picture_name",
    "plan_pictures",
    "topic_clashes",
    "topic_slug",
]

#: At most this many target-frame pictures per targeted film.
MAX_PER_FILM = 5
#: Chosen ticks lie at least this far apart, in film ticks, while there are frames to choose.
SPACING = 50
#: The spacing is halved to this when too few are chosen, and never goes below it.
MIN_SPACING = 25
#: The raster a picture is cut from.
SCREEN_WIDTH, SCREEN_HEIGHT = 320, 200
#: A cropped picture is enlarged this many times; a whole frame is drawn at native size.
CROP_SCALE = 3

_TOPIC_RUN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class Picture:
    """One PNG to draw: the film, the film tick and the file name."""

    film: str
    tick: int
    name: str
    #: A guard picture of the film's worst frame, outside the per-film cap.
    guard: bool = False


def topic_slug(words: str) -> str:
    """``--topic`` as a file-name part: lower-case words joined by ``-``.

    Raises ``ValueError`` when nothing is left.
    """
    slug = _TOPIC_RUN.sub("-", words.lower()).strip("-")
    if not slug:
        raise ValueError(f"--topic wants a few words, got {words!r}")
    return slug


def picture_name(film: str, tick: int, topic: str, *, guard: bool = False) -> str:
    """``<film>-<tick>-<topic>.png``, or ``...-guard.png`` for a guard picture."""
    return f"{film}-{tick}-{topic}{'-guard' if guard else ''}.png"


def parse_crop(text: str) -> tuple[int, int, int, int]:
    """``x0,y0,x1,y1`` as a box; raises ``ValueError`` unless it is a box on the screen."""
    try:
        x0, y0, x1, y1 = (int(part) for part in text.split(","))
    except ValueError:
        raise ValueError(f"--crop wants x0,y0,x1,y1, got {text!r}") from None
    if not (0 <= x0 < x1 <= SCREEN_WIDTH and 0 <= y0 < y1 <= SCREEN_HEIGHT):
        raise ValueError(
            f"--crop {text!r} is not a box inside the {SCREEN_WIDTH}x{SCREEN_HEIGHT} screen"
        )
    return x0, y0, x1, y1


def choose_ticks(
    deltas: Sequence[Delta], limit: int = MAX_PER_FILM, spacing: int = SPACING
) -> list[int]:
    """Up to *limit* ticks of one film's target frames, in the order they are chosen.

    First the frame with the lowest SSIM change, its biggest fall or smallest rise. Then the
    frames in descending change, each taken only when at least *spacing* ticks from every tick
    already chosen. If fewer than *limit* are chosen the spacing is halved, to
    :data:`MIN_SPACING` at least, and the list is gone down again. Ties go to the lower tick.
    """
    if not deltas or limit < 1:
        return []
    chosen = [min(deltas, key=lambda d: (d.ssim, d.tick)).tick]
    ranked = sorted(deltas, key=lambda d: (-d.ssim, d.tick))
    passes = [spacing] if spacing <= MIN_SPACING else [spacing, max(spacing // 2, MIN_SPACING)]
    for gap in passes:
        for delta in ranked:
            if len(chosen) >= limit:
                return chosen
            if delta.tick not in chosen and all(abs(delta.tick - tick) >= gap for tick in chosen):
                chosen.append(delta.tick)
    return chosen


def guard_pictures(judgement: Judgement) -> list[Delta]:
    """Each film's worst frame when it fell by more than 0.005 in SSIM, in film order."""
    worst = (
        min(join.deltas, key=lambda d: d.ssim, default=None) for join in judgement.joins.values()
    )
    return [d for d in worst if d is not None and d.ssim < -LISTED]


def plan_pictures(judgement: Judgement, topic: str) -> list[Picture]:
    """Every picture a round draws: up to five per targeted film, then the guard pictures.

    A guard picture whose frame is already pictured as a target pick is not drawn twice.
    """
    pictures: list[Picture] = []
    for film in dict.fromkeys(t.film for t in judgement.targets):
        frames = [d for d in judgement.target_frames() if d.film == film]
        pictures += [
            Picture(film, tick, picture_name(film, tick, topic)) for tick in choose_ticks(frames)
        ]
    taken = {(p.film, p.tick) for p in pictures}
    pictures += [
        Picture(d.film, d.tick, picture_name(d.film, d.tick, topic, guard=True), guard=True)
        for d in guard_pictures(judgement)
        if (d.film, d.tick) not in taken
    ]
    return pictures


def existing_paths(directory: Path, names: Iterable[str]) -> list[Path]:
    """The files among *names* that already exist in *directory*; a picture is never replaced."""
    return [directory / name for name in names if (directory / name).exists()]


def topic_clashes(directory: Path, topic: str) -> list[Path]:
    """Files in *directory* named for this topic, whatever film and tick: ``<film>-<tick>-<topic>``
    with or without ``-guard``. A picture of the topic could overwrite one of them."""
    if not directory.is_dir():
        return []
    shape = re.compile(rf"[a-z0-9_-]+-\d+-{re.escape(topic)}(-guard)?\.png")
    return sorted(path for path in directory.iterdir() if shape.fullmatch(path.name))


def films_with(pictures: Iterable[Picture]) -> Mapping[str, list[int]]:
    """Each pictured film's distinct ticks, ascending."""
    ticks: dict[str, set[int]] = {}
    for picture in pictures:
        ticks.setdefault(picture.film, set()).add(picture.tick)
    return {film: sorted(values) for film, values in ticks.items()}
