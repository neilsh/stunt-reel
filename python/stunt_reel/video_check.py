"""Check a video capture against the film's pinned frame capture, and against its own replay.

The kept pages of ``captures/<film>/frames`` are what parity scores; the video holds every frame
PLAYONE drew. :func:`reference_check` maps each page's indices through its own palette and
searches the video around ``emu_frame - capture_start_frame`` for the frame whose rows match best.
:func:`replay_report` says whether two recordings of one film are the same. The AVI is decoded by
``ffmpeg``, whose ZMBV decoder matched the recorder byte for byte (``capture-dosbox-automation.md``
§ 4.6).
"""

from __future__ import annotations

import itertools
import json
import shutil
import statistics
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from stunt_reel.bench.ssim import render_luma, window_ssim
from stunt_reel.parity_artifacts import (
    CAPTURE_META,
    VIDEO_FILE,
    PixelEqual,
    ReferenceCheck,
    RenderStore,
    VideoCapture,
    load_video_capture,
    read_capture,
    read_capture_palette,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

#: Rows of a page compared: the 3D view's 185 rows, ``0..184`` inclusive.
REFERENCE_ROWS = (0, 184)
#: Largest absolute offset searched around a page's video index.
REFERENCE_SEARCH = 8


class VideoCheckError(RuntimeError):
    """A check cannot run: ffmpeg is missing or a file is not what it names."""


def iter_video_frames(avi: Path, width: int, height: int) -> Generator[np.ndarray]:
    """Every frame of *avi* in order, as ``(height, width, 3)`` ``uint8`` RGB, none dropped."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise VideoCheckError("ffmpeg is not on PATH; the video is decoded with it")
    size = width * height * 3
    command = [ffmpeg, "-v", "error", "-i", str(avi), "-fps_mode", "passthrough"]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:  # noqa: S603
        stdout = process.stdout
        if stdout is None:
            raise VideoCheckError(f"{avi}: ffmpeg gave no output stream")
        try:
            while chunk := stdout.read(size):
                if len(chunk) != size:
                    raise VideoCheckError(f"{avi}: ffmpeg ended inside a frame")
                yield np.frombuffer(chunk, dtype=np.uint8).reshape(height, width, 3)
            if process.wait() != 0:
                raise VideoCheckError(f"{avi}: ffmpeg failed to decode it")
        finally:
            process.kill()  # a reader that stops early must not leave ffmpeg on a broken pipe


def decode_frames(avi: Path, width: int, height: int, wanted: set[int]) -> dict[int, np.ndarray]:
    """The frames of *avi* at the indices in *wanted*; an index past the end is absent."""
    last = max(wanted, default=-1)
    held: dict[int, np.ndarray] = {}
    frames = iter_video_frames(avi, width, height)
    for index, frame in enumerate(frames):
        if index in wanted:
            held[index] = frame.copy()
        if index >= last:
            break
    frames.close()
    return held


@dataclass(frozen=True)
class PageMatch:
    """Where one kept page matched best in the video."""

    ordinal: int
    emu_frame: int
    #: Offset from ``emu_frame - capture_start_frame`` of the best frame, ties to the smallest.
    offset: int
    #: Fraction of the compared pixels that are equal in RGB at that offset.
    equal: float
    #: Number of differing pixels at that offset.
    differing: int
    #: ``exact``, ``split`` or ``band`` (:func:`classify_page`).
    kind: str


def _offsets(search: int) -> list[int]:
    """0, -1, 1, -2, 2 ...: a tie goes to the offset nearest zero, then the earlier frame."""
    return [0] + [step * n for n in range(1, search + 1) for step in (-1, 1)]


def best_offset(
    decoded: dict[int, np.ndarray],
    base: int,
    shown: np.ndarray,
    rows: tuple[int, int],
    search: int,
) -> tuple[int, int]:
    """The offset within *search* of *base* whose frame differs least from *shown* over *rows*
    (half-open), and the pixels that differ there; a tie goes to the offset nearest zero.
    """
    low, high = rows
    counts = (
        (offset, int(np.count_nonzero(np.any(decoded[base + offset][low:high] != shown, axis=2))))
        for offset in _offsets(search)
    )
    return min(counts, key=lambda found: found[1])


#: Frames around the paired one a page's rows may come from: the journal's ``f-2 .. f+4`` rule.
ROW_WINDOW = (-2, 4)


def _paired_index(capture: VideoCapture, emu_frame: int) -> int | None:
    """Video index of the log row of *emu_frame*: ``emu_frame - capture_start_frame - 1``."""
    index = capture.video_index(emu_frame)
    return None if index is None or index < 1 else index - 1


def classify_page(
    decoded: dict[int, np.ndarray],
    base: int,
    shown: np.ndarray,
    rows: tuple[int, int],
    differing: int,
) -> str:
    """``exact`` (a frame equals the page), ``split`` or ``band``.

    A page that no frame equals is a ``split`` when each of its rows equals that row of some frame
    in :data:`ROW_WINDOW` around *base*, and a ``band`` when some row equals none.
    """
    if differing == 0:
        return "exact"
    low, high = rows
    window = [
        decoded[base + offset][low:high] for offset in range(ROW_WINDOW[0], ROW_WINDOW[1] + 1)
    ]
    matched = np.zeros(high - low, dtype=bool)
    for candidate in window:
        matched |= np.all(candidate == shown, axis=(1, 2))
    return "split" if matched.all() else "band"


def page_matches(
    video: Path,
    capture: VideoCapture,
    reference: Path,
    *,
    rows: tuple[int, int] = REFERENCE_ROWS,
    search: int = REFERENCE_SEARCH,
) -> tuple[list[PageMatch], int]:
    """Best match of every kept page of *reference*, and the pages whose window left the video.

    A page is searched at the video indices ``emu_frame - capture_start_frame - 1 + offset``; it is
    skipped unless every index of its window exists.
    """
    kept = read_capture(reference)
    meta = json.loads((reference / CAPTURE_META).read_text(encoding="utf-8"))
    emu_frames = {entry["ordinal"]: entry["emu_frame"] for entry in meta["frames"]}
    width, height = capture.geometry.width, capture.geometry.height
    count = capture.video_frames or len(capture.log.frame)
    pages = []
    wanted: set[int] = set()
    skipped = 0
    for frame in kept.frames:
        base = _paired_index(capture, emu_frames[frame.ordinal])
        if base is None or base - search < 0 or base + search >= count:
            skipped += 1
            continue
        pages.append((frame, base))
        wanted.update(range(base - search, base + search + 1))
    decoded = decode_frames(video / VIDEO_FILE, width, height, wanted)
    low, high = rows[0], rows[1] + 1
    matches: list[PageMatch] = []
    for frame, base in pages:
        indices = np.fromfile(reference / frame.frame_file, dtype=np.uint8)
        palette = np.array(read_capture_palette(reference / frame.palette_file), dtype=np.uint8)
        shown = palette[indices[: width * height].reshape(height, width)][low:high]
        offset, differing = best_offset(decoded, base, shown, (low, high), search)
        matches.append(
            PageMatch(
                ordinal=frame.ordinal,
                emu_frame=emu_frames[frame.ordinal],
                offset=offset,
                equal=1 - differing / (shown.shape[0] * shown.shape[1]),
                differing=differing,
                kind=classify_page(decoded, base, shown, (low, high), differing),
            )
        )
    return matches, skipped


def summarise(
    matches: list[PageMatch],
    skipped: int,
    *,
    digest: str,
    rows: tuple[int, int] = REFERENCE_ROWS,
    search: int = REFERENCE_SEARCH,
) -> ReferenceCheck:
    """The :class:`ReferenceCheck` of *matches*: offset histogram, pixel-equal summary, exact pages."""
    offsets: dict[str, int] = {}
    for match in sorted(matches, key=lambda m: m.offset):
        offsets[str(match.offset)] = offsets.get(str(match.offset), 0) + 1
    equal = [match.equal for match in matches]
    return ReferenceCheck(
        capture_digest=digest,
        rows=rows,
        search=search,
        pages=len(matches) + skipped,
        skipped=skipped,
        offsets=offsets,
        pixel_equal=PixelEqual(
            min=min(equal, default=0.0), median=statistics.median(equal) if equal else 0.0
        ),
        exact_pages=sum(match.kind == "exact" for match in matches),
        split_pages=sum(match.kind == "split" for match in matches),
        band_pages=sum(match.kind == "band" for match in matches),
    )


@dataclass(frozen=True)
class Replay:
    """Whether two recordings of one film are the same, and where they first differ."""

    video_identical: bool
    meta_identical: bool
    #: Columns of ``log`` and ``palettes`` that differ, as ``name: first differing index``.
    differing: dict[str, int | None]

    @property
    def identical(self) -> bool:
        """True when both the AVI bytes and ``meta.json`` bytes are equal."""
        return self.video_identical and self.meta_identical


def _first_difference(left: Sequence[object], right: Sequence[object]) -> int | None:
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


def replay_report(first: Path, second: Path) -> Replay:
    """Compare two video capture directories of one film: the AVI bytes, then ``meta.json``."""
    video_identical = (first / VIDEO_FILE).read_bytes() == (second / VIDEO_FILE).read_bytes()
    meta_identical = (first / CAPTURE_META).read_bytes() == (second / CAPTURE_META).read_bytes()
    a, b = load_video_capture(first), load_video_capture(second)
    columns = ("frame", "film_tick", "global_tick", "slot_clock", "slot_ticks")
    differing: dict[str, int | None] = {}
    for name in columns:
        left, right = getattr(a.log, name), getattr(b.log, name)
        if left != right:
            differing[f"log.{name}"] = (
                None if left is None or right is None else _first_difference(left, right)
            )
    if a.palettes != b.palettes:
        differing["palettes"] = _first_difference(
            (a.palettes.initial, *a.palettes.changes), (b.palettes.initial, *b.palettes.changes)
        )
    return Replay(video_identical, meta_identical, differing)


#: Frames after a palette write that the DAC may still show the old palette on (§ 4.5).
PALETTE_LAG_FRAMES = 2
#: Render offsets tried around a frame's ``render_tick`` by the render check.
PAIRING_SPAN = 3


@dataclass(frozen=True)
class KeyGroups:
    """Run-end frames grouped by a pairing key: does one key always name one picture?"""

    #: Groups holding two or more frames.
    shared: int
    #: Of those, the groups whose frames are not all pixel-identical.
    conflicting: int
    #: Frames in the conflicting groups.
    conflicting_frames: int


@dataclass(frozen=True)
class RenderPairing:
    """The run-end frames against a render store, by offset from their ``render_tick``."""

    #: Frames whose ``render_tick`` and neighbours (to :data:`PAIRING_SPAN`) the store holds.
    compared: int
    #: Mean luma SSIM (the parity scorer's windows) per offset, over the compared frames.
    mean_ssim: dict[int, float]
    #: Number of frames whose SSIM is highest at each offset, ties to the smaller magnitude.
    best_offset: dict[int, int]
    #: Mean SSIM when paired by the tag, ``film_tick``, over the frames the store holds it for.
    tag_ssim: float
    #: Frames where the ``render_tick`` pairing's SSIM is no smaller than the tag's.
    rule_not_worse: int
    #: Frames the tag differs from ``render_tick`` on, and on how many the rule scores higher.
    tag_differs: int
    rule_better_where_differs: int


@dataclass(frozen=True)
class PairingCheck:
    """ADR 0057's rule on the run-end frames of a full-rate recording."""

    #: Which row of each run of one ``slot_clock`` value supplied the words: ``last`` (the
    #: run-end frame) or ``first`` (the frame the pass ran).
    key_row: str
    frames: int
    finished: int  # run-end frames
    #: Runs of one ``slot_clock`` value, those of two or more frames, and of those the runs whose
    #: ``slot_ticks`` is not the same on every row.
    runs: int
    multi_frame_runs: int
    ticks_vary: int
    #: Finished frames inside a palette write's lag window, left out.
    in_palette_window: int
    compared: int
    by_render_tick: KeyGroups
    by_film_tick: KeyGroups
    render_tick_falls: int
    render: RenderPairing | None


def _lag_window(capture: VideoCapture) -> set[int]:
    """Video indices within :data:`PALETTE_LAG_FRAMES` after a palette write, the write included."""
    window: set[int] = set()
    for change in capture.palettes.changes:
        start = change.frame - capture.log.frame[0]
        window.update(range(start, start + PALETTE_LAG_FRAMES + 1))
    return window


def _groups(keys: list[int], pictures: list[bytes]) -> KeyGroups:
    seen: dict[int, list[bytes]] = {}
    for key, picture in zip(keys, pictures, strict=True):
        seen.setdefault(key, []).append(picture)
    shared = [group for group in seen.values() if len(group) > 1]
    conflicting = [group for group in shared if len(set(group)) > 1]
    return KeyGroups(len(shared), len(conflicting), sum(len(group) for group in conflicting))


def _render_luma(store: RenderStore, tick: int, rows: tuple[int, int]) -> np.ndarray:
    frame = store.frame(tick)
    palette = np.frombuffer(frame.palette, dtype=np.uint8).reshape(256, 3)
    width = store.record.geometry.width
    indices = np.frombuffer(frame.indices, dtype=np.uint8).reshape(-1, width)
    return render_luma(palette[indices[rows[0] : rows[1] + 1]])


def run_ends(capture: VideoCapture) -> tuple[bool, ...]:
    """True on each frame before a frame whose ``slot_clock`` (else ``film_tick``) differs.

    The last frame of a run of one clock value. It is not known to be a whole picture: a video
    frame can be torn between two buffers.
    """
    log = capture.log
    clock = log.slot_clock if log.slot_clock is not None else log.film_tick
    return tuple(i + 1 < len(clock) and clock[i + 1] != clock[i] for i in range(len(clock)))


def pairing_check(
    video: Path,
    capture: VideoCapture,
    render_ticks: tuple[int, ...],
    *,
    store: RenderStore | None = None,
    key_row: str = "last",
    rows: tuple[int, int] = REFERENCE_ROWS,
    span: int = PAIRING_SPAN,
) -> PairingCheck:
    """Test the pairing rule on the run-end frames of *video* (:func:`run_ends`; one pass over the AVI).

    Two tests. Without a render: a pairing key must name one picture, so run-end frames that
    share a key must be pixel-identical on *rows*; the rule's ``render_tick`` is compared with the
    tag ``film_tick`` as the key. With a render *store* (a :class:`RenderStore` of the film):
    each compared frame's picture is scored (luma SSIM) against the render at
    ``render_tick + offset`` for offsets within *span*, and against the render at the tag.
    """
    width, height = capture.geometry.width, capture.geometry.height
    low, high = rows[0], rows[1] + 1
    if key_row not in ("last", "first"):
        raise ValueError(f"key_row is {key_row!r}, expected 'last' or 'first'")
    lag = _lag_window(capture)
    finished = run_ends(capture)
    keep = [i for i, done in enumerate(finished) if done and i not in lag]
    #: The row whose words name the picture of the run ending at each kept frame.
    first_of = {}
    start = 0
    for i, done in enumerate(finished):
        if done:
            first_of[i] = start
            start = i + 1
    word_row = {i: (first_of[i] if key_row == "first" else i) for i in keep}
    wanted = set(keep)
    pictures: dict[int, bytes] = {}
    scores: dict[int, dict[int, float]] = {}
    tag_scores: dict[int, float] = {}
    for index, frame in enumerate(iter_video_frames(video / VIDEO_FILE, width, height)):
        if index not in wanted:
            continue
        shown = frame[low:high]
        pictures[index] = shown.tobytes()
        if store is None:
            continue
        luma = render_luma(shown)
        key = render_ticks[word_row[index]]
        for offset in range(-span, span + 1):
            tick = key + offset
            if store.holds(tick):
                scores.setdefault(index, {})[offset] = float(
                    window_ssim(luma, _render_luma(store, tick, rows)).mean()
                )
        tag = capture.log.film_tick[word_row[index]]
        if store.holds(tag):
            tag_scores[index] = float(window_ssim(luma, _render_luma(store, tag, rows)).mean())
    kept = [i for i in keep if i in pictures]
    ticks = [render_ticks[word_row[i]] for i in kept]
    tags = [capture.log.film_tick[word_row[i]] for i in kept]
    shots = [pictures[i] for i in kept]
    render = None
    if store is not None:
        render = _render_pairing(kept, scores, tag_scores, word_row, render_ticks, capture, span)
    spans = [(first_of[i], i) for i in first_of]
    multi = [(a, b) for a, b in spans if b > a]
    log = capture.log
    return PairingCheck(
        key_row=key_row,
        runs=len(spans),
        multi_frame_runs=len(multi),
        ticks_vary=sum(
            1
            for a, b in multi
            if log.slot_ticks is not None and len(set(log.slot_ticks[a : b + 1])) > 1
        ),
        frames=len(finished),
        finished=sum(finished),
        in_palette_window=sum(1 for i, done in enumerate(finished) if done and i in lag),
        compared=len(kept),
        by_render_tick=_groups(ticks, shots),
        by_film_tick=_groups(tags, shots),
        render_tick_falls=sum(b < a for a, b in itertools.pairwise(ticks)),
        render=render,
    )


def _render_pairing(
    kept: list[int],
    scores: dict[int, dict[int, float]],
    tag_scores: dict[int, float],
    word_row: dict[int, int],
    render_ticks: tuple[int, ...],
    capture: VideoCapture,
    span: int,
) -> RenderPairing:
    full = [i for i in kept if len(scores.get(i, {})) == 2 * span + 1]
    mean_ssim = {
        offset: statistics.fmean(scores[i][offset] for i in full) if full else 0.0
        for offset in range(-span, span + 1)
    }
    best: dict[int, int] = {}
    for i in full:
        offset = max(scores[i], key=lambda o: (scores[i][o], -abs(o)))
        best[offset] = best.get(offset, 0) + 1
    tagged = [i for i in full if i in tag_scores]
    differs = [i for i in tagged if capture.log.film_tick[word_row[i]] != render_ticks[word_row[i]]]
    return RenderPairing(
        compared=len(full),
        mean_ssim=mean_ssim,
        best_offset=dict(sorted(best.items())),
        tag_ssim=statistics.fmean(tag_scores[i] for i in tagged) if tagged else 0.0,
        rule_not_worse=sum(scores[i][0] >= tag_scores[i] for i in tagged),
        tag_differs=len(differs),
        rule_better_where_differs=sum(scores[i][0] > tag_scores[i] for i in differs),
    )
