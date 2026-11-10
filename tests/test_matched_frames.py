"""Offline tests for `stunt_reel.matched_frames`, over the parity bench and pairing fixtures."""

from __future__ import annotations

import json
import shutil
lazy from pathlib import Path

import pytest

from stunt_reel.matched_frames import Reference, pair
from stunt_reel.parity_artifacts import FrameReport, RenderStore, Report


@pytest.fixture
def reference(bench_fixture: Path, tmp_path: Path) -> Path:
    """The bench capture with the pairing fixture's `meta.json`: two matched, two not."""
    directory = tmp_path / "capture"
    shutil.copytree(bench_fixture / "capture", directory)
    shutil.copy(bench_fixture.parent / "pairing" / "meta.json", directory / "meta.json")
    return directory


def test_pairing_a_capture_with_a_render_in_memory(bench_fixture: Path, reference: Path) -> None:
    """Matched and unmatched frames are the shared fixture's expected lists."""
    expected = json.loads((bench_fixture.parent / "pairing" / "expected.json").read_text("utf-8"))
    result = pair(reference, RenderStore(bench_fixture / "render"))
    assert [m.ordinal for m in result.matched] == expected["matched"]
    assert [f.ordinal for f in result.unmatched] == expected["unmatched"]


def test_a_matched_frame_carries_its_files_and_the_render_page(
    bench_fixture: Path, reference: Path
) -> None:
    store = RenderStore(bench_fixture / "render")
    first = pair(reference, store).matched[1]
    assert first.film_tick == 20
    assert first.frame_path == reference / "tick_0002.idx"
    assert first.capture_indices() == first.frame_path.read_bytes()
    assert first.page.indices == store.frame(20).indices
    assert len(first.capture_palette()) == 256


def _report(*rows: tuple[int, int, bool | None]) -> Report:
    return Report(
        per_frame=tuple(
            FrameReport(film_tick=tick, ssim=1.0, iou=1.0, ordinal=ordinal, scored=scored)
            for ordinal, tick, scored in rows
        )
    )


def test_a_report_yields_only_its_scored_rows(bench_fixture: Path, reference: Path) -> None:
    source = Reference(reference, RenderStore(bench_fixture / "render"))
    report = _report((1, 10, True), (2, 20, False), (3, 30, None))
    assert [m.ordinal for m in source.from_report(report)] == [1]
    assert [
        m.ordinal
        for m in source.from_report(report.__class__(report.per_frame[:2]), scored_only=False)
    ] == [1, 2]


def test_a_row_the_capture_lacks_raises(bench_fixture: Path, reference: Path) -> None:
    source = Reference(reference, RenderStore(bench_fixture / "render"))
    with pytest.raises(ValueError, match="the capture has no ordinal 9"):
        list(source.from_report(_report((9, 10, True))))
    with pytest.raises(ValueError, match="the capture has no ordinal 9"):
        source.match(9)
