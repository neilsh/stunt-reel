"""The report document: ``report.json``, the scored result of a parity run.

Reports keep serde-defaulted optional fields, so a report written before a field existed still
loads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from stunt_reel.parity_artifacts._fields import (
    _as_array,
    _as_bool,
    _as_float,
    _as_int,
    _as_object,
    _as_unsigned,
    _error,
    _number_map,
    _optional_bool,
    _optional_float,
    _parse_json,
    _read_json,
    _write_json,
    _wrong_type,
)
from stunt_reel.parity_artifacts.render import (
    RenderAdapter,
    _adapter_document,
    _adapter_object,
)

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class I6Gate:
    """Whether the scored mean SSIM reaches each I6 threshold."""

    initial: bool = False
    sign_off: bool = False


@dataclass(frozen=True)
class FrameReport:
    """One matched frame's measurements."""

    film_tick: int
    ssim: float
    iou: float
    ordinal: int = 0
    index_agreement: float | None = None
    loss_by_class: dict[str, float] | None = None
    fade_level: float | None = None
    authored_fade_level: float | None = None
    scored: bool | None = None


@dataclass(frozen=True)
class Report:
    """The ``report.json`` document."""

    per_frame: tuple[FrameReport, ...]
    reference_frames: int = 0
    frames: int = 0
    unmatched: int = 0
    sky_indices: tuple[int, int] = (0, 0)
    mean_ssim: float = 0.0
    min_ssim: float = 0.0
    mean_iou: float = 0.0
    min_fade_level: float = 0.0
    mean_ssim_scored: float | None = None
    i6_gate: I6Gate = field(default_factory=I6Gate)
    mean_iou_scored: float | None = None
    mean_index_agreement_scored: float | None = None
    mean_loss_by_class_scored: dict[str, float] | None = None
    scored_frames: int = 0
    excluded_frames: int = 0
    credits_missing_frames: int = 0
    #: Adapter the render was drawn on, from its ``render.json``; ``None`` when it does not say.
    adapter: RenderAdapter | None = None
    #: The render read another archive than the capture played, and the run waived that
    #: conflict; written only when true.
    archive_conflict_waived: bool = False

    def headline(self) -> tuple[float, float]:
        """Headline SSIM and mask IoU: the scored means, else every matched frame."""
        ssim = self.mean_ssim_scored if self.mean_ssim_scored is not None else self.mean_ssim
        iou = self.mean_iou_scored if self.mean_iou_scored is not None else self.mean_iou
        return ssim, iou

    def validate(self, path: Path | None = None) -> None:
        """Check the arithmetic identities the report promises."""
        if self.reference_frames != self.frames + self.unmatched:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: reference_frames must equal frames + unmatched",
                path,
            )
        if not 0 <= self.credits_missing_frames <= self.frames:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: credits_missing_frames must be from 0 to frames",
                path,
            )
        if self.frames != self.scored_frames + self.excluded_frames:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: frames must equal scored_frames + excluded_frames",
                path,
            )
        if (
            self.mean_ssim_scored is None or self.mean_iou_scored is None
        ) and self.scored_frames != 0:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: scored means must be present when scored_frames "
                "is non-zero",
                path,
            )
        if self.scored_frames == 0 and (
            self.mean_ssim_scored is not None or self.mean_iou_scored is not None
        ):
            raise _error(
                "report_inconsistent",
                "report is inconsistent: scored means must be null when no frame scored",
                path,
            )
        if self.scored_frames == 0 and self.i6_gate.initial:
            raise _error(
                "report_inconsistent",
                "report is inconsistent: the I6 gate cannot pass with no scored frame",
                path,
            )


def _frame_report_object(value: Any, path: Path | None, field_name: str) -> FrameReport:
    raw = _as_object(value, path, field_name)
    return FrameReport(
        film_tick=_as_int(raw.get("film_tick"), path, f"{field_name}.film_tick"),
        ssim=_as_float(raw.get("ssim"), path, f"{field_name}.ssim"),
        iou=_as_float(raw.get("iou"), path, f"{field_name}.iou"),
        ordinal=_as_int(raw.get("ordinal", 0), path, f"{field_name}.ordinal"),
        index_agreement=_optional_float(
            raw.get("index_agreement"), path, f"{field_name}.index_agreement"
        ),
        loss_by_class=_number_map(raw.get("loss_by_class"), path, f"{field_name}.loss_by_class"),
        fade_level=_optional_float(raw.get("fade_level"), path, f"{field_name}.fade_level"),
        authored_fade_level=_optional_float(
            raw.get("authored_fade_level"), path, f"{field_name}.authored_fade_level"
        ),
        scored=_optional_bool(raw.get("scored"), path, f"{field_name}.scored"),
    )


def _i6_gate_object(value: Any, path: Path | None, field_name: str) -> I6Gate:
    raw = _as_object(value, path, field_name)
    return I6Gate(
        initial=_as_bool(raw.get("initial", False), path, f"{field_name}.initial"),
        sign_off=_as_bool(raw.get("sign_off", False), path, f"{field_name}.sign_off"),
    )


def _sky_indices(value: Any, path: Path | None) -> tuple[int, int]:
    entries = _as_array(value, path, "sky_indices")
    if len(entries) != 2:
        raise _wrong_type(path, "sky_indices", "an array of 2 integers")
    return (
        _as_unsigned(entries[0], path, "sky_indices[0]", 0xFF),
        _as_unsigned(entries[1], path, "sky_indices[1]", 0xFF),
    )


def _report_object(document: Any, path: Path | None) -> Report:
    raw = _as_object(document, path, "the report")
    frames = _as_array(raw.get("per_frame"), path, "per_frame")
    return Report(
        per_frame=tuple(
            _frame_report_object(value, path, f"per_frame[{index}]")
            for index, value in enumerate(frames)
        ),
        reference_frames=_as_int(raw.get("reference_frames", 0), path, "reference_frames"),
        frames=_as_int(raw.get("frames", 0), path, "frames"),
        unmatched=_as_int(raw.get("unmatched", 0), path, "unmatched"),
        sky_indices=_sky_indices(raw.get("sky_indices", [0, 0]), path),
        mean_ssim=_as_float(raw.get("mean_ssim", 0.0), path, "mean_ssim"),
        min_ssim=_as_float(raw.get("min_ssim", 0.0), path, "min_ssim"),
        mean_iou=_as_float(raw.get("mean_iou", 0.0), path, "mean_iou"),
        min_fade_level=_as_float(raw.get("min_fade_level", 0.0), path, "min_fade_level"),
        mean_ssim_scored=_optional_float(raw.get("mean_ssim_scored"), path, "mean_ssim_scored"),
        i6_gate=_i6_gate_object(raw.get("i6_gate", {}), path, "i6_gate"),
        mean_iou_scored=_optional_float(raw.get("mean_iou_scored"), path, "mean_iou_scored"),
        mean_index_agreement_scored=_optional_float(
            raw.get("mean_index_agreement_scored"), path, "mean_index_agreement_scored"
        ),
        mean_loss_by_class_scored=_number_map(
            raw.get("mean_loss_by_class_scored"), path, "mean_loss_by_class_scored"
        ),
        scored_frames=_as_int(raw.get("scored_frames", 0), path, "scored_frames"),
        excluded_frames=_as_int(raw.get("excluded_frames", 0), path, "excluded_frames"),
        credits_missing_frames=_as_int(
            raw.get("credits_missing_frames", 0), path, "credits_missing_frames"
        ),
        adapter=_adapter_object(raw.get("adapter"), path),
        archive_conflict_waived=_as_bool(
            raw.get("archive_conflict_waived", False), path, "archive_conflict_waived"
        ),
    )


def _report_document(report: Report) -> dict[str, Any]:
    def frame_document(frame: FrameReport) -> dict[str, Any]:
        return {
            "ordinal": frame.ordinal,
            "film_tick": frame.film_tick,
            "ssim": frame.ssim,
            "iou": frame.iou,
            "index_agreement": frame.index_agreement,
            "loss_by_class": frame.loss_by_class,
            "fade_level": frame.fade_level,
            "authored_fade_level": frame.authored_fade_level,
            "scored": frame.scored,
        }

    document: dict[str, Any] = {
        "reference_frames": report.reference_frames,
        "frames": report.frames,
        "unmatched": report.unmatched,
        "sky_indices": list(report.sky_indices),
        "mean_ssim": report.mean_ssim,
        "min_ssim": report.min_ssim,
        "mean_iou": report.mean_iou,
        "min_fade_level": report.min_fade_level,
        "mean_ssim_scored": report.mean_ssim_scored,
        "i6_gate": {"initial": report.i6_gate.initial, "sign_off": report.i6_gate.sign_off},
        "mean_iou_scored": report.mean_iou_scored,
        "mean_index_agreement_scored": report.mean_index_agreement_scored,
        "mean_loss_by_class_scored": report.mean_loss_by_class_scored,
        "scored_frames": report.scored_frames,
        "excluded_frames": report.excluded_frames,
        "credits_missing_frames": report.credits_missing_frames,
        "adapter": None if report.adapter is None else _adapter_document(report.adapter),
    }
    if report.archive_conflict_waived:
        document["archive_conflict_waived"] = True
    document["per_frame"] = [frame_document(frame) for frame in report.per_frame]
    return document


def read_report(path: Path) -> Report:
    """Read a ``report.json``, including reports written before recent optional fields."""
    return _report_object(_read_json(path), path)


def parse_report(data: bytes, path: Path) -> Report:
    """Parse ``report.json`` bytes already read from *path*, so a caller can hash the same bytes."""
    return _report_object(_parse_json(data, path), path)


def write_report(path: Path, report: Report) -> None:
    """Validate and write a ``report.json`` through a temporary file and rename."""
    report.validate(path)
    _write_json(path, _report_document(report))
