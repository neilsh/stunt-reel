"""The batch ledger: one JSON line per stage outcome, read back for resume and summary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from stunt_reel import batch_ledger
from stunt_reel.batch_ledger import Record

if TYPE_CHECKING:
    from pathlib import Path


def _record(slug: str, stage: str, status: str, message: str = "", **extra: float) -> Record:
    return Record(
        slug=slug,
        stage=stage,
        status=status,
        message=message,
        seconds=1.5,
        at="2026-10-30T00:00:00+00:00",
        **extra,
    )


def test_append_then_read_roundtrips(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    written = _record("vault-ctry", "score", "ok", ssim=0.91, iou=0.5)
    batch_ledger.append(ledger, written)
    batch_ledger.append(ledger, _record("vault-ctry", "render", "error", "boom"))
    assert batch_ledger.read(ledger) == [
        written,
        _record("vault-ctry", "render", "error", "boom"),
    ]


def test_read_missing_file_is_empty(tmp_path: Path) -> None:
    assert batch_ledger.read(tmp_path / "absent.jsonl") == []


def test_read_skips_a_malformed_line(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    batch_ledger.append(ledger, _record("a", "archive", "ok"))
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write("not json at all\n")
    batch_ledger.append(ledger, _record("b", "archive", "skipped"))
    assert [r.slug for r in batch_ledger.read(ledger)] == ["a", "b"]


def test_latest_returns_the_last_record_for_slug_and_stage() -> None:
    records = [
        _record("a", "capture", "error", "first"),
        _record("a", "capture", "ok"),
        _record("b", "capture", "error", "other film"),
    ]
    latest = batch_ledger.latest(records, "a", "capture")
    assert latest is not None
    assert latest.status == "ok"
    assert batch_ledger.latest(records, "a", "score") is None


def test_summarize_lists_each_failed_slug_once_with_its_stage() -> None:
    records = [
        _record("vault-ctry", "capture", "error", "timeout"),
        _record("vault-ctry", "render", "error", "exit 3"),
        _record("vault-ctry", "capture", "ok"),
    ]
    summary = batch_ledger.summarize(records)
    failure_lines = [line for line in summary.splitlines() if line.startswith("vault-ctry")]
    assert len(failure_lines) == 1
    assert "render" in failure_lines[0]
    assert "exit 3" in failure_lines[0]
    assert "timeout" not in summary
