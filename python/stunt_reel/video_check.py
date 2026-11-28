"""Check a video capture against the film's pinned frame capture, and against its own replay.

The kept pages of ``captures/<film>/frames`` are what parity scores; the video holds every frame
PLAYONE drew. :func:`reference_check` maps each page's indices through its own palette and
searches the video around ``emu_frame - capture_start_frame - 1`` for the frame whose rows match best.
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
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from stunt_reel.bench.ssim import render_luma, window_ssim
from stunt_reel.parity_artifacts import (
    CAPTURE_META,
    DERIVED_FILE,
    VIDEO_FILE,
    PixelEqual,
    ReferenceCheck,
    RenderStore,
    VideoCapture,
    derive_columns,
    load_fresh_derived,
    load_video_capture,
    read_capture,
    read_capture_palette,
)
from stunt_reel.tac import stream as tac_stream

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence
    from pathlib import Path

    from stunt_reel.parity_artifacts import PaletteLog

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


@dataclass(frozen=True)
class CaptureFrame:
    """One video frame with its clocks: the frame as the emulator recorded it, torn or not."""

    #: Index in the AVI, equal to the row of the tick log.
    index: int
    rgb: np.ndarray
    emu_frame: int
    film_tick: int
    #: The film tick the frame's picture is paired with (``derived.json``, ADR 0057).
    render_tick: int


def iter_capture_frames(directory: Path) -> Generator[CaptureFrame]:
    """Every frame of the video capture in *directory* with its clocks, in order.

    ``render_tick`` is read from a fresh ``derived.json`` when one lies beside ``meta.json``,
    else derived in memory; a stale ``derived.json`` raises. The log and the AVI must have the
    same number of rows, or :class:`VideoCheckError` is raised after the last common frame.
    """
    capture = load_video_capture(directory)
    if (directory / DERIVED_FILE).is_file():
        ticks = load_fresh_derived(directory).frames.render_tick
    else:
        ticks = derive_columns(capture)[1].render_tick
    log = capture.log
    width, height = capture.geometry.width, capture.geometry.height
    count = 0
    for index, rgb in enumerate(iter_video_frames(directory / VIDEO_FILE, width, height)):
        if index >= len(log.frame):
            raise VideoCheckError(f"{directory}: the AVI holds more frames than the log's rows")
        yield CaptureFrame(index, rgb, log.frame[index], log.film_tick[index], ticks[index])
        count = index + 1
    if count != len(log.frame):
        raise VideoCheckError(
            f"{directory}: the AVI holds {count} frames, the log {len(log.frame)}"
        )


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
    #: Offset from ``emu_frame - capture_start_frame - 1`` of the best frame, ties to the smallest.
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
    if search < max(abs(edge) for edge in ROW_WINDOW):
        raise ValueError(f"search is {search}, but a page's rows are classified over {ROW_WINDOW}")
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
class StreamRun:
    """A recording's stream: its pictures by emulated frame, and the frames not known to be whole."""

    first_frame: int
    #: Frames whose picture is not known to be whole (``stream.json``'s ``held``).
    held: frozenset[int]
    #: Each picture's ``(192, 320)`` palette indices, keyed by emulated frame.
    pictures: dict[int, np.ndarray]

    def picture(self, frame: int) -> np.ndarray:
        """The picture of emulated *frame*; VideoCheckError when the stream does not hold it."""
        try:
            return self.pictures[frame]
        except KeyError:
            raise VideoCheckError(f"the stream holds no picture of frame {frame}") from None


def read_stream_document(directory: Path) -> dict[str, Any] | None:
    """The parsed ``stream.json`` of *directory*, or None when the recording has none."""
    path = directory / tac_stream.JSON_NAME
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VideoCheckError(f"{path}: cannot read it: {error}") from error
    if not isinstance(document, dict):
        raise VideoCheckError(f"{path}: is not a JSON object")
    return document


def load_stream(directory: Path) -> StreamRun:
    """The stream of the recording in *directory*: ``stream.mkv`` decoded and checked against
    ``stream.json``.

    Raises VideoCheckError when either file is missing, the file cannot be decoded, or it holds
    other than the ``frames`` that ``stream.json`` records.
    """
    document = read_stream_document(directory)
    mkv = directory / tac_stream.MKV_NAME
    if document is None or not mkv.is_file():
        raise VideoCheckError(
            f"{directory}: no {tac_stream.JSON_NAME} and {tac_stream.MKV_NAME} "
            "(encode the log with stream-encode)"
        )
    try:
        first = int(document["first_frame"])
        frames = int(document["frames"])
        held = frozenset(int(frame) for frame in document["held"])
    except (KeyError, TypeError, ValueError) as error:
        raise VideoCheckError(f"{directory / tac_stream.JSON_NAME}: {error}") from error
    pictures: dict[int, np.ndarray] = {}
    try:
        for index, picture in enumerate(tac_stream.decode_stream(mkv)):
            pictures[first + index] = picture
    except tac_stream.StreamError as error:
        raise VideoCheckError(str(error)) from error
    if len(pictures) != frames:
        raise VideoCheckError(
            f"{mkv}: decodes to {len(pictures)} pictures, stream.json records {frames}"
        )
    return StreamRun(first, held, pictures)


def working_palette(palettes: PaletteLog, frame: int) -> np.ndarray:
    """The 256 RGB entries of the working palette at emulated *frame* as ``(256, 3)`` ``uint8``.

    The initial palette with each write at or before *frame* applied, in log order.
    """
    table = np.array(palettes.initial, dtype=np.uint8)
    for change in palettes.changes:
        if change.frame <= frame:
            table[change.first : change.first + len(change.rgb)] = change.rgb
    return table


@dataclass(frozen=True)
class StreamPageMatch:
    """Where one kept page matched best in the stream, and what the matched picture is."""

    ordinal: int
    emu_frame: int
    #: Offset from the page's ``emu_frame`` of the matched picture, ties to the smallest.
    offset: int
    #: Number of differing palette indices over the compared rows at that offset.
    differing_pixels: int
    #: True when the matched picture's frame is one the stream holds as not known to be whole.
    on_held: bool
    #: True when the working palette at the matched frame equals the page's palette.
    palette_equal: bool


def stream_page_matches(
    directory: Path,
    capture: VideoCapture,
    reference: Path,
    *,
    rows: tuple[int, int] = REFERENCE_ROWS,
    search: int = REFERENCE_SEARCH,
) -> tuple[list[StreamPageMatch], int]:
    """Best stream picture of every kept page of *reference*, and the pages whose window left it.

    The indices of a page's *rows* (inclusive) are compared with the stream's picture at
    ``emu_frame + offset`` for offsets within *search*, nearest zero first. A page is skipped,
    and counted, unless every frame of its window is in the stream.
    """
    stream = load_stream(directory)
    kept = read_capture(reference)
    meta = json.loads((reference / CAPTURE_META).read_text(encoding="utf-8"))
    emu_frames = {entry["ordinal"]: entry["emu_frame"] for entry in meta["frames"]}
    width, height = kept.geometry.width, kept.geometry.height
    if width != tac_stream.WIDTH or height < rows[1] + 1:
        raise VideoCheckError(
            f"{reference}: pages are {width}x{height}; the stream is "
            f"{tac_stream.WIDTH}x{tac_stream.HEIGHT} and holds rows {rows[0]}..{rows[1]}"
        )
    low, high = rows[0], rows[1] + 1
    matches: list[StreamPageMatch] = []
    skipped = 0
    for frame in kept.frames:
        emu = emu_frames[frame.ordinal]
        if any(
            candidate not in stream.pictures for candidate in range(emu - search, emu + search + 1)
        ):
            skipped += 1
            continue
        indices = np.fromfile(reference / frame.frame_file, dtype=np.uint8)
        shown = indices[: width * height].reshape(height, width)[low:high]
        page_palette = np.array(
            read_capture_palette(reference / frame.palette_file), dtype=np.uint8
        )
        counts = (
            (offset, int(np.count_nonzero(stream.picture(emu + offset)[low:high] != shown)))
            for offset in _offsets(search)
        )
        offset, differing = min(counts, key=lambda found: found[1])
        matched = emu + offset
        matches.append(
            StreamPageMatch(
                ordinal=frame.ordinal,
                emu_frame=emu,
                offset=offset,
                differing_pixels=differing,
                on_held=matched in stream.held,
                palette_equal=bool(
                    np.array_equal(working_palette(capture.palettes, matched), page_palette)
                ),
            )
        )
    return matches, skipped


@dataclass(frozen=True)
class StreamCheck:
    """The stream check of a reference: offsets, exact pages, pages on held frames, palette equal."""

    pages: int
    skipped: int
    #: Matches per offset, as ``str(offset)``.
    offsets: dict[str, int]
    #: Pages whose best picture equals the page in every compared index.
    exact_pages: int
    on_held_pages: int
    palette_equal_pages: int


def summarise_stream(matches: list[StreamPageMatch], skipped: int) -> StreamCheck:
    """The :class:`StreamCheck` of *matches* and the *skipped* page count."""
    histogram = Counter(match.offset for match in matches)
    return StreamCheck(
        pages=len(matches) + skipped,
        skipped=skipped,
        offsets={str(offset): count for offset, count in sorted(histogram.items())},
        exact_pages=sum(match.differing_pixels == 0 for match in matches),
        on_held_pages=sum(match.on_held for match in matches),
        palette_equal_pages=sum(match.palette_equal for match in matches),
    )


@dataclass(frozen=True)
class Replay:
    """Whether two recordings of one film are the same, and where they first differ."""

    video_identical: bool
    meta_identical: bool
    #: Columns of ``log`` and ``palettes`` that differ, as ``name: first differing index``.
    differing: dict[str, int | None]
    #: Whether the two streams have the same raw SHA-256 and frame count; None when either lacks one.
    stream_identical: bool | None = None

    @property
    def identical(self) -> bool:
        """True when the AVI bytes and ``meta.json`` bytes are equal, and no stream differs."""
        return self.video_identical and self.meta_identical and self.stream_identical is not False


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
    return Replay(video_identical, meta_identical, differing, _stream_identical(first, second))


def _stream_identical(first: Path, second: Path) -> bool | None:
    """Whether two recordings' ``stream.json`` agree on the raw SHA-256 and frame count."""
    left, right = read_stream_document(first), read_stream_document(second)
    if left is None or right is None:
        return None
    try:
        return (left["sha256_raw"], left["frames"]) == (right["sha256_raw"], right["frames"])
    except KeyError as error:
        raise VideoCheckError(f"a stream.json lacks {error.args[0]}") from error


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
    run_ends: int
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
    #: Run-end rows left out because their frame is held in the stream; 0 without a stream.
    held_dropped: int = 0


def _pairing_pictures(
    video: Path,
    capture: VideoCapture,
    wanted: set[int],
    rows: tuple[int, int],
    stream: StreamRun | None,
) -> Generator[tuple[int, np.ndarray, bytes]]:
    """Each wanted log row as ``(row, RGB rows, the bytes that key it)``, in row order.

    Without a *stream* the AVI is decoded, and the bytes are the RGB rows. With one, the AVI is not
    read: the row's picture is the stream's picture of its frame, mapped through the working
    palette, and the bytes are the index rows.
    """
    low, high = rows
    if stream is None:
        width, height = capture.geometry.width, capture.geometry.height
        for index, frame in enumerate(iter_video_frames(video / VIDEO_FILE, width, height)):
            if index in wanted:
                shown = frame[low:high]
                yield index, shown, shown.tobytes()
        return
    for index in sorted(wanted):
        frame_number = capture.log.frame[index]
        indices = stream.picture(frame_number)[low:high]
        yield index, working_palette(capture.palettes, frame_number)[indices], indices.tobytes()


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
    stream: StreamRun | None = None,
) -> PairingCheck:
    """Test the pairing rule on the run-end frames of *video* (:func:`run_ends`; one pass over the AVI).

    Two tests. Without a render: a pairing key must name one picture, so run-end frames that
    share a key must be pixel-identical on *rows*; the rule's ``render_tick`` is compared with the
    tag ``film_tick`` as the key. With a render *store* (a :class:`RenderStore` of the film):
    each compared frame's picture is scored (luma SSIM) against the render at
    ``render_tick + offset`` for offsets within *span*, and against the render at the tag.

    With a *stream*, the pictures are the stream's instead of the AVI's (the AVI is not read),
    keyed by palette index; a run-end row whose frame the stream holds is left out.
    """
    low, high = rows[0], rows[1] + 1
    if key_row not in ("last", "first"):
        raise ValueError(f"key_row is {key_row!r}, expected 'last' or 'first'")
    lag = _lag_window(capture)
    ends = run_ends(capture)
    keep = [i for i, done in enumerate(ends) if done and i not in lag]
    held_dropped = 0
    if stream is not None:
        unheld = [i for i in keep if capture.log.frame[i] not in stream.held]
        held_dropped = len(keep) - len(unheld)
        keep = unheld
    #: The row whose words name the picture of the run ending at each kept frame.
    first_of = {}
    start = 0
    for i, done in enumerate(ends):
        if done:
            first_of[i] = start
            start = i + 1
    word_row = {i: (first_of[i] if key_row == "first" else i) for i in keep}
    wanted = set(keep)
    pictures: dict[int, bytes] = {}
    scores: dict[int, dict[int, float]] = {}
    tag_scores: dict[int, float] = {}
    for index, shown, picture in _pairing_pictures(video, capture, wanted, (low, high), stream):
        pictures[index] = picture
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
        frames=len(ends),
        run_ends=sum(ends),
        in_palette_window=sum(1 for i, done in enumerate(ends) if done and i in lag),
        compared=len(kept),
        by_render_tick=_groups(ticks, shots),
        by_film_tick=_groups(tags, shots),
        render_tick_falls=sum(b < a for a, b in itertools.pairwise(ticks)),
        render=render,
        held_dropped=held_dropped,
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
