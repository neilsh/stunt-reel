"""Matched frames: a captured frame together with the render at its film clock.

Two sources yield them. :func:`pair` walks a capture set against a render store and also
reports the captured frames that found no partner (their files are missing, or the render holds
no planes for their tick). :meth:`Reference.from_report` starts from a report's per-frame rows
and looks each captured frame up by ordinal, which is what the probes and the sweep need.
Store reads stay behind :class:`~stunt_reel.parity_artifacts.RenderStore` (ADR 0027).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
lazy from collections.abc import Iterator
lazy from pathlib import Path

from stunt_reel.parity_artifacts import (
    CapturedFrame,
    CaptureSet,
    Page,
    RenderStore,
    Report,
    read_capture,
    read_capture_palette,
    read_page,
)

__all__ = ["MatchedFrame", "Pairing", "Reference", "pair"]


@dataclass(frozen=True)
class MatchedFrame:
    """A captured frame, its resolved files and the render's page at ``film_tick``."""

    frame: CapturedFrame
    film_tick: int
    frame_path: Path
    palette_path: Path
    store: RenderStore

    @property
    def ordinal(self) -> int:
        """The captured frame's ordinal."""
        return self.frame.ordinal

    @cached_property
    def page(self) -> Page:
        """The render's planes at :attr:`film_tick`."""
        return read_page(self.store, self.film_tick)

    def capture_indices(self) -> bytes:
        """The captured frame's palette-index plane."""
        return self.frame_path.read_bytes()

    def capture_palette(self) -> tuple[tuple[int, int, int], ...]:
        """The captured frame's palette."""
        return read_capture_palette(self.palette_path)


@dataclass(frozen=True)
class Pairing:
    """The result of pairing a whole capture set with a render."""

    matched: tuple[MatchedFrame, ...]
    unmatched: tuple[CapturedFrame, ...]


class Reference:
    """A reference capture directory paired with a render store."""

    def __init__(self, directory: Path, store: RenderStore) -> None:
        self.directory = directory
        self.store = store
        self.capture: CaptureSet = read_capture(directory)
        self._by_ordinal = {frame.ordinal: frame for frame in self.capture.frames}

    def match(self, ordinal: int, tick: int | None = None) -> MatchedFrame:
        """The captured frame *ordinal* against the render at *tick* (default: its own tick).

        Raises ``ValueError`` when the capture has no such ordinal.
        """
        frame = self._by_ordinal.get(ordinal)
        if frame is None:
            raise ValueError(f"the capture has no ordinal {ordinal}")
        return self.matched_frame(frame, frame.film_tick if tick is None else tick)

    def from_report(self, report: Report, *, scored_only: bool = True) -> Iterator[MatchedFrame]:
        """The report's per-frame rows as matched frames, at each row's film tick.

        With *scored_only* a row the scorer excluded is skipped.
        """
        for row in report.per_frame:
            if scored_only and row.scored is not True:
                continue
            yield self.match(row.ordinal, row.film_tick)

    def matched_frame(self, frame: CapturedFrame, tick: int) -> MatchedFrame:
        """*frame* against the render at *tick*, its files resolved under the capture directory."""
        return MatchedFrame(
            frame,
            tick,
            self.directory / frame.frame_file,
            self.directory / frame.palette_file,
            self.store,
        )


def pair(directory: Path, store: RenderStore) -> Pairing:
    """Pairs every captured frame of *directory* with the render, in capture order.

    A frame is unmatched when its frame or palette file is missing, or the render holds no
    planes for its film tick.
    """
    reference = Reference(directory, store)
    matched: list[MatchedFrame] = []
    unmatched: list[CapturedFrame] = []
    for frame in reference.capture.frames:
        found = reference.matched_frame(frame, frame.film_tick)
        if (
            found.frame_path.is_file()
            and found.palette_path.is_file()
            and store.holds(frame.film_tick)
        ):
            matched.append(found)
        else:
            unmatched.append(frame)
    return Pairing(tuple(matched), tuple(unmatched))
