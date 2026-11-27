"""The derived document: a video capture directory's ``derived.json``.

Computed from ``meta.json`` and the AVI beside it and never archived, so a rule change rewrites
it without a recapture. ``source`` names the two files' SHA-256, so a stale file is detectable;
every column is aligned with the capture's tick log.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stunt_reel.parity_artifacts._fields import (
    CAPTURE_META,
    SCHEMA_VERSION,
    ArtifactError,
    _as_array,
    _as_bool,
    _as_float,
    _as_object,
    _as_string,
    _as_unsigned,
    _error,
    _read_json,
    _write_json,
    _wrong_type,
)
from stunt_reel.parity_artifacts.video import VIDEO_FILE, VideoCapture, load_video_capture

if TYPE_CHECKING:
    from pathlib import Path


#: File name of the derived document inside a video capture directory.
DERIVED_FILE = "derived.json"
#: The ``kind`` a video capture's ``derived.json`` carries.
DERIVED_KIND = "video-derived"

RENDER_TICK_RULES = ("adr-0057", "film-tick")
PALETTE_STEP_RULES = ("palette-change-frame",)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_U64 = 0xFFFFFFFFFFFFFFFF
_U32 = 0xFFFFFFFF


def _derived_error(message: str, path: Path | None) -> ArtifactError:
    return _error("video_log", f"video log: {message}", path)


@dataclass(frozen=True)
class DerivedSource:
    """The files a derived document was computed from."""

    meta_sha256: str
    video_sha256: str


@dataclass(frozen=True)
class DerivedRules:
    """The rule behind each derived column."""

    render_tick: str
    palette_step: str


@dataclass(frozen=True)
class DerivedColumns:
    """Per-frame columns, one entry per row of the capture's tick log."""

    render_tick: tuple[int, ...]
    palette_step: tuple[bool, ...]


@dataclass(frozen=True)
class PixelEqual:
    """Smallest and median pixel-equal fraction over the compared pages."""

    min: float
    median: float


@dataclass(frozen=True)
class ReferenceCheck:
    """The video compared against the pinned frame capture of the same film."""

    capture_digest: str
    rows: tuple[int, int]
    search: int
    pages: int
    skipped: int
    #: Best offset as a decimal string (``"-1"``) to the number of pages that found it first.
    offsets: dict[str, int]
    pixel_equal: PixelEqual
    exact_pages: int
    #: Pages with no exact match whose every row equals that row of some frame in ``-2..+4``.
    split_pages: int
    #: The remaining pages: some row matches no frame in the window.
    band_pages: int


@dataclass(frozen=True)
class VideoDerived:
    """Document written by ``mise run video-derive`` as ``derived.json``."""

    schema_version: int
    kind: str
    source: DerivedSource
    rules: DerivedRules
    frames: DerivedColumns
    reference_check: ReferenceCheck | None = None

    def validate(self, path: Path | None = None) -> None:
        """Check the version, kind, source hashes, rules and that the columns are equally long."""
        if self.schema_version != SCHEMA_VERSION:
            raise _error(
                "unsupported_version",
                f"unsupported schema version {self.schema_version}; expected {SCHEMA_VERSION}",
                path,
            )
        if self.kind != DERIVED_KIND:
            raise _derived_error(f"kind is {self.kind!r}, expected {DERIVED_KIND!r}", path)
        for name, value in (
            ("meta_sha256", self.source.meta_sha256),
            ("video_sha256", self.source.video_sha256),
        ):
            if _SHA256.fullmatch(value) is None:
                raise _derived_error(f"source.{name} is not 64 lower-case hex digits", path)
        for name, value, known in (
            ("render_tick", self.rules.render_tick, RENDER_TICK_RULES),
            ("palette_step", self.rules.palette_step, PALETTE_STEP_RULES),
        ):
            if value not in known:
                raise _derived_error(f"rules.{name} is {value!r}, expected one of {known}", path)
        rows = len(self.frames.render_tick)
        if len(self.frames.palette_step) != rows:
            raise _derived_error(
                f"derived columns differ in length: render_tick {rows}, "
                f"palette_step {len(self.frames.palette_step)}",
                path,
            )
        if self.reference_check is not None:
            self._validate_check(self.reference_check, path)

    @staticmethod
    def _validate_check(check: ReferenceCheck, path: Path | None) -> None:
        if _SHA256.fullmatch(check.capture_digest) is None:
            raise _derived_error(
                "reference_check.capture_digest is not 64 lower-case hex digits", path
            )
        compared = sum(check.offsets.values())
        if (
            check.rows[0] > check.rows[1]
            or compared != check.pages - check.skipped
            or check.exact_pages + check.split_pages + check.band_pages != compared
        ):
            raise _derived_error(
                "reference_check rows, offsets, pages, skipped and page classes disagree", path
            )

    def validate_against(
        self,
        capture: VideoCapture,
        meta_sha256: str,
        video_sha256: str,
        path: Path | None = None,
    ) -> None:
        """Check that this was derived from *capture* and the two files with these hashes."""
        self.validate(path)
        if (self.source.meta_sha256, self.source.video_sha256) != (meta_sha256, video_sha256):
            raise _derived_error(
                "source hashes differ from the files beside derived.json: it is stale", path
            )
        rules, columns = derive_columns(capture)
        if rules != self.rules:
            raise _derived_error(f"rules are {self.rules}, the capture gives {rules}", path)
        if len(self.frames.render_tick) != len(capture.log.frame):
            raise _derived_error(
                f"derived columns hold {len(self.frames.render_tick)} rows, "
                f"the log {len(capture.log.frame)}",
                path,
            )
        for name in ("render_tick", "palette_step"):
            if getattr(self.frames, name) != getattr(columns, name):
                raise _derived_error(f"column {name} differs from the capture's derivation", path)


def render_tick(film_tick: int, slot_clock: int | None, slot_ticks: int | None) -> int:
    """The render-store tick a frame is paired with, as ``CapturedFrame.render_tick``.

    ``slot_clock - slot_ticks + 1`` (ADR 0057), or *film_tick* without both words or with a ticks
    word above the clock.
    """
    if slot_clock is None or slot_ticks is None or slot_ticks > slot_clock:
        return film_tick
    return slot_clock - slot_ticks + 1


def derive_columns(capture: VideoCapture) -> tuple[DerivedRules, DerivedColumns]:
    """The rules and columns the derivation rules give *capture*, one entry per log row.

    No column says which frames are whole pictures: a video frame can be torn between two buffers
    and no rule on the log separates them.
    """
    log = capture.log
    words = log.slot_clock is not None and log.slot_ticks is not None
    rows = len(log.frame)
    ticks = tuple(
        render_tick(
            log.film_tick[i],
            log.slot_clock[i] if log.slot_clock is not None else None,
            log.slot_ticks[i] if log.slot_ticks is not None else None,
        )
        for i in range(rows)
    )
    stepped = {change.frame for change in capture.palettes.changes}
    return (
        DerivedRules(
            render_tick="adr-0057" if words else "film-tick",
            palette_step="palette-change-frame",
        ),
        DerivedColumns(
            render_tick=ticks,
            palette_step=tuple(frame in stepped for frame in log.frame),
        ),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def derive_video(directory: Path, reference_check: ReferenceCheck | None = None) -> VideoDerived:
    """The derived document of the video capture in *directory*, from its two files."""
    capture = load_video_capture(directory)
    rules, columns = derive_columns(capture)
    return VideoDerived(
        schema_version=SCHEMA_VERSION,
        kind=DERIVED_KIND,
        source=DerivedSource(
            meta_sha256=_sha256_file(directory / CAPTURE_META),
            video_sha256=_sha256_file(directory / VIDEO_FILE),
        ),
        rules=rules,
        frames=columns,
        reference_check=reference_check,
    )


def _check_document(check: ReferenceCheck) -> dict[str, Any]:
    return {
        "capture_digest": check.capture_digest,
        "rows": list(check.rows),
        "search": check.search,
        "pages": check.pages,
        "skipped": check.skipped,
        "offsets": dict(check.offsets),
        "pixel_equal": {"min": check.pixel_equal.min, "median": check.pixel_equal.median},
        "exact_pages": check.exact_pages,
        "split_pages": check.split_pages,
        "band_pages": check.band_pages,
    }


def _derived_document(derived: VideoDerived) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schema_version": derived.schema_version,
        "kind": derived.kind,
        "source": {
            "meta_sha256": derived.source.meta_sha256,
            "video_sha256": derived.source.video_sha256,
        },
        "rules": {
            "render_tick": derived.rules.render_tick,
            "palette_step": derived.rules.palette_step,
        },
        "frames": {
            "render_tick": list(derived.frames.render_tick),
            "palette_step": list(derived.frames.palette_step),
        },
    }
    if derived.reference_check is not None:
        document["reference_check"] = _check_document(derived.reference_check)
    return document


def _bool_column(value: Any, path: Path | None, field_name: str) -> tuple[bool, ...]:
    return tuple(
        _as_bool(item, path, f"{field_name}[{index}]")
        for index, item in enumerate(_as_array(value, path, field_name))
    )


def _check_object(value: Any, path: Path | None) -> ReferenceCheck:
    entry = _as_object(value, path, "reference_check")
    rows = _as_array(entry.get("rows"), path, "reference_check.rows")
    if len(rows) != 2:
        raise _wrong_type(path, "reference_check.rows", "a first and a last row")
    offsets = _as_object(entry.get("offsets"), path, "reference_check.offsets")
    equal = _as_object(entry.get("pixel_equal"), path, "reference_check.pixel_equal")
    return ReferenceCheck(
        capture_digest=_as_string(
            entry.get("capture_digest"), path, "reference_check.capture_digest"
        ),
        rows=(
            _as_unsigned(rows[0], path, "reference_check.rows[0]", _U32),
            _as_unsigned(rows[1], path, "reference_check.rows[1]", _U32),
        ),
        search=_as_unsigned(entry.get("search"), path, "reference_check.search", _U32),
        pages=_as_unsigned(entry.get("pages"), path, "reference_check.pages", _U64),
        skipped=_as_unsigned(entry.get("skipped"), path, "reference_check.skipped", _U64),
        offsets={
            key: _as_unsigned(count, path, f"reference_check.offsets.{key}", _U64)
            for key, count in offsets.items()
        },
        pixel_equal=PixelEqual(
            min=_as_float(equal.get("min"), path, "reference_check.pixel_equal.min"),
            median=_as_float(equal.get("median"), path, "reference_check.pixel_equal.median"),
        ),
        exact_pages=_as_unsigned(
            entry.get("exact_pages"), path, "reference_check.exact_pages", _U64
        ),
        split_pages=_as_unsigned(
            entry.get("split_pages"), path, "reference_check.split_pages", _U64
        ),
        band_pages=_as_unsigned(entry.get("band_pages"), path, "reference_check.band_pages", _U64),
    )


def read_video_derived(directory: Path) -> VideoDerived:
    """Read and validate a video capture directory's ``derived.json``."""
    path = directory / DERIVED_FILE
    document = _as_object(_read_json(path), path, "the derived document")
    source = _as_object(document.get("source"), path, "source")
    rules = _as_object(document.get("rules"), path, "rules")
    frames = _as_object(document.get("frames"), path, "frames")
    check = document.get("reference_check")
    derived = VideoDerived(
        schema_version=_as_unsigned(document.get("schema_version"), path, "schema_version", _U32),
        kind=_as_string(document.get("kind"), path, "kind"),
        source=DerivedSource(
            meta_sha256=_as_string(source.get("meta_sha256"), path, "source.meta_sha256"),
            video_sha256=_as_string(source.get("video_sha256"), path, "source.video_sha256"),
        ),
        rules=DerivedRules(
            render_tick=_as_string(rules.get("render_tick"), path, "rules.render_tick"),
            palette_step=_as_string(rules.get("palette_step"), path, "rules.palette_step"),
        ),
        frames=DerivedColumns(
            render_tick=tuple(
                _as_unsigned(item, path, f"frames.render_tick[{index}]", _U32)
                for index, item in enumerate(
                    _as_array(frames.get("render_tick"), path, "frames.render_tick")
                )
            ),
            palette_step=_bool_column(frames.get("palette_step"), path, "frames.palette_step"),
        ),
        reference_check=None if check is None else _check_object(check, path),
    )
    derived.validate(path)
    return derived


def write_video_derived(directory: Path, derived: VideoDerived) -> dict[str, Any]:
    """Validate and write ``derived.json`` beside the capture's ``meta.json``, returning it."""
    path = directory / DERIVED_FILE
    derived.validate(path)
    document = _derived_document(derived)
    _write_json(path, document)
    return document


def load_fresh_derived(directory: Path) -> VideoDerived:
    """``derived.json`` of *directory*, refused unless it was derived from the files beside it."""
    derived = read_video_derived(directory)
    derived.validate_against(
        load_video_capture(directory),
        _sha256_file(directory / CAPTURE_META),
        _sha256_file(directory / VIDEO_FILE),
        directory / DERIVED_FILE,
    )
    return derived
