"""Offline tests for ``derived.json`` in the Python parity artifact adapter (synthetic documents)."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from artifact_helpers import write_json
from stunt_reel.parity_artifacts import (
    DERIVED_FILE,
    VIDEO_FILE,
    ArtifactError,
    DerivedSource,
    PixelEqual,
    ReferenceCheck,
    VideoDerived,
    derive_columns,
    derive_video,
    load_fresh_derived,
    load_video_capture,
    read_video_derived,
    render_tick,
    write_video_derived,
)

FIXTURE = Path(__file__).parent / "fixtures" / "parity" / "video" / "with-slots"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def capture_dir(tmp_path: Path) -> Path:
    """The slot-word fixture with a stand-in ``capture.avi``, so both source files exist."""
    shutil.copy(FIXTURE / "meta.json", tmp_path / "meta.json")
    (tmp_path / VIDEO_FILE).write_bytes(b"not a real avi")
    return tmp_path


def test_render_tick_is_the_slot_clock_less_the_ticks_word_plus_one() -> None:
    capture = load_video_capture(FIXTURE)
    rules, columns = derive_columns(capture)
    assert rules.render_tick == "adr-0057"
    assert columns.render_tick == (6, 5, 5, 7)


def test_render_tick_falls_back_to_the_tag() -> None:
    assert render_tick(9, None, None) == 9
    assert render_tick(9, 5, None) == 9
    assert render_tick(9, 5, 6) == 9
    assert render_tick(9, 5, 5) == 1
    capture = load_video_capture(FIXTURE)
    bare = replace(capture, log=replace(capture.log, slot_clock=None, slot_ticks=None))
    rules, columns = derive_columns(bare)
    assert rules.render_tick == "film-tick"
    assert columns.render_tick == bare.log.film_tick


def test_palette_step_marks_the_frame_a_write_took_effect() -> None:
    _, columns = derive_columns(load_video_capture(FIXTURE))
    assert columns.palette_step == (False, False, True, False)


def test_the_columns_are_as_long_as_the_log() -> None:
    capture = load_video_capture(FIXTURE)
    _, columns = derive_columns(capture)
    rows = len(capture.log.frame)
    assert (len(columns.render_tick), len(columns.palette_step)) == (rows, rows)


def test_the_committed_fixture_is_derived_from_its_meta_json() -> None:
    derived = read_video_derived(FIXTURE)
    capture = load_video_capture(FIXTURE)
    assert derived.source.meta_sha256 == sha256(FIXTURE / "meta.json")
    assert capture.video is not None
    assert derived.source.video_sha256 == capture.video.sha256
    derived.validate_against(
        capture, derived.source.meta_sha256, derived.source.video_sha256, FIXTURE
    )
    assert derived.reference_check is not None


def test_derive_video_hashes_the_two_files_beside_it(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    assert derived.source == DerivedSource(
        meta_sha256=sha256(capture_dir / "meta.json"),
        video_sha256=sha256(capture_dir / VIDEO_FILE),
    )
    write_video_derived(capture_dir, derived)
    assert read_video_derived(capture_dir) == derived
    assert load_fresh_derived(capture_dir) == derived


def test_a_changed_file_makes_the_derived_document_stale(capture_dir: Path) -> None:
    write_video_derived(capture_dir, derive_video(capture_dir))
    (capture_dir / VIDEO_FILE).write_bytes(b"another recording")
    with pytest.raises(ArtifactError, match="stale"):
        load_fresh_derived(capture_dir)
    write_video_derived(capture_dir, derive_video(capture_dir))
    meta = (capture_dir / "meta.json").read_text(encoding="utf-8")
    (capture_dir / "meta.json").write_text(meta.replace('"SYNTH.FLM"', '"OTHER.FLM"'), "utf-8")
    with pytest.raises(ArtifactError, match="stale"):
        load_fresh_derived(capture_dir)


def test_a_column_that_disagrees_with_the_rule_is_refused(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    wrong = replace(derived, frames=replace(derived.frames, render_tick=(7, 5, 5, 7)))
    write_video_derived(capture_dir, wrong)
    with pytest.raises(ArtifactError, match="render_tick"):
        load_fresh_derived(capture_dir)


def test_columns_of_different_length_are_refused(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    short = replace(
        derived, frames=replace(derived.frames, palette_step=derived.frames.palette_step[:3])
    )
    with pytest.raises(ArtifactError, match="length"):
        write_video_derived(capture_dir, short)


def test_the_source_hashes_must_be_hex(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    bad = replace(derived, source=replace(derived.source, meta_sha256="AB"))
    with pytest.raises(ArtifactError, match="meta_sha256"):
        bad.validate()


def test_the_kind_and_version_are_checked(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    with pytest.raises(ArtifactError, match="kind"):
        replace(derived, kind="video").validate()
    with pytest.raises(ArtifactError, match="schema version 9"):
        replace(derived, schema_version=9).validate()


def check(**changes: Any) -> ReferenceCheck:
    base = ReferenceCheck(
        capture_digest="cd" * 32,
        rows=(0, 184),
        search=8,
        pages=3,
        skipped=1,
        offsets={"-1": 1, "0": 1},
        pixel_equal=PixelEqual(min=0.96, median=0.9997),
        exact_pages=1,
        split_pages=1,
        band_pages=0,
    )
    return replace(base, **changes)


def test_the_reference_check_counts_must_agree(capture_dir: Path) -> None:
    derived = derive_video(capture_dir)
    replace(derived, reference_check=check()).validate()
    for bad in (
        check(pages=5),
        check(exact_pages=3),
        check(band_pages=1),
        check(rows=(9, 1)),
        check(capture_digest="x"),
    ):
        with pytest.raises(ArtifactError):
            replace(derived, reference_check=bad).validate()


def test_a_reference_check_round_trips(capture_dir: Path) -> None:
    derived = replace(derive_video(capture_dir), reference_check=check())
    write_video_derived(capture_dir, derived)
    assert read_video_derived(capture_dir) == derived


def test_a_document_missing_a_column_is_refused(tmp_path: Path) -> None:
    write_json(tmp_path / DERIVED_FILE, {"schema_version": 1, "kind": "video-derived"})
    with pytest.raises(ArtifactError):
        read_video_derived(tmp_path)


def test_video_derived_is_a_dataclass_of_its_parts() -> None:
    derived = read_video_derived(FIXTURE)
    assert isinstance(derived, VideoDerived)
