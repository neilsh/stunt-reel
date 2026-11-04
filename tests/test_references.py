"""The reference pointer: a committed file pins a film's one capture by content hash."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from stunt_reel import capture_store, parity_layout, references
from stunt_reel.dataroot import REPO_ROOT

if TYPE_CHECKING:
    from pathlib import Path


PATCH3 = 'makeone = "patch3"\nplayone = "patch3"\n'


def _capture(root: Path, film: str, text: str = "{}") -> Path:
    directory = root / parity_layout.frames_path(f"vault-{film}")
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(text, encoding="utf-8")
    (directory / "tick_0001.idx").write_bytes(b"\x01\x02")
    return directory


def _point(root: Path, film: str, sha256: str) -> None:
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    pointers.write_text(f'[{film}]\nfilm = "vault-{film}"\nsha256 = "{sha256}"\n{PATCH3}', "utf-8")


def _open(root: Path, film: str) -> Path:
    with references.open_reference(root, film) as held:
        return held


def test_a_named_capture_with_the_recorded_hash_resolves(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", references.capture_digest(directory))
    with references.open_reference(tmp_path, "CTRY") as held:
        assert held.name.startswith("frames.read-")
        assert (held / "tick_0001.idx").read_bytes() == b""
    assert not held.exists()
    assert [p.name for p in directory.parent.iterdir() if p.suffix != ".lock"] == ["frames"]


def test_a_swap_while_the_reference_is_held_does_not_reach_the_holder(tmp_path: Path) -> None:
    """A capture-ref that publishes mid-run must not change what a scoring run reads (ADR 0031)."""
    directory = _capture(tmp_path, "ctry")
    pin = references.capture_digest(directory)
    _point(tmp_path, "ctry", pin)
    with references.open_reference(tmp_path, "ctry") as held:
        staged = capture_store.stage(directory)
        (staged / "meta.json").write_text('{"new": true}', encoding="utf-8")
        capture_store.publish(staged, directory)
        assert references.capture_digest(held) == pin
    assert references.capture_digest(directory) != pin
    with pytest.raises(references.ReferenceCaptureError, match="hash"):
        _open(tmp_path, "ctry")


def test_the_digest_follows_content_and_names(tmp_path: Path) -> None:
    first = _capture(tmp_path / "a", "ctry")
    same = _capture(tmp_path / "b", "ctry")
    other = _capture(tmp_path / "c", "ctry", text='{"frames": []}')
    assert references.capture_digest(first) == references.capture_digest(same)
    assert references.capture_digest(first) != references.capture_digest(other)


def test_an_absent_capture_is_named(tmp_path: Path) -> None:
    _point(tmp_path, "ctry", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"ctry is absent on this machine"):
        _open(tmp_path, "ctry")


def test_a_film_that_is_not_a_slug_is_refused(tmp_path: Path) -> None:
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    lines = ["[ctry]", 'film = "../x"', f'sha256 = "{"0" * 64}"']
    pointers.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(references.ReferenceCaptureError, match="not a slug"):
        _open(tmp_path, "ctry")


def test_a_replaced_capture_is_refused(tmp_path: Path) -> None:
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", "0" * 64)
    with pytest.raises(references.ReferenceCaptureError, match=r"ctry has hash.*repin"):
        _open(tmp_path, "ctry")
    assert [p.name for p in directory.parent.iterdir() if p.suffix != ".lock"] == ["frames"]


def test_a_missing_file_or_film_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(references, "REPO_ROOT", tmp_path / "empty-checkout")
    with pytest.raises(references.ReferenceCaptureError, match="does not exist"):
        _open(tmp_path, "ctry")
    _point(tmp_path, "intro", "0" * 64)
    with pytest.raises(
        references.ReferenceCaptureError, match="names no reference capture for ctry"
    ):
        _open(tmp_path, "ctry")


def test_a_data_root_without_a_pointer_reads_the_checkouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout, data = tmp_path / "checkout", tmp_path / "data"
    directory = _capture(data, "ctry")
    _point(checkout, "ctry", references.capture_digest(directory))
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    with references.open_reference(data, "ctry") as held:
        assert held.parent == directory.parent


def test_a_capture_replaced_in_place_gets_a_fresh_digest(tmp_path: Path) -> None:
    """The digest is not cached by path, because a new capture replaces the old one there."""
    directory = _capture(tmp_path, "ctry")
    _point(tmp_path, "ctry", references.capture_digest(directory))
    with references.open_reference(tmp_path, "ctry"):
        pass
    (directory / "tick_0001.idx").write_bytes(b"\x09")
    with pytest.raises(references.ReferenceCaptureError, match="hash"):
        _open(tmp_path, "ctry")


def test_the_loops_films_are_the_rows_that_pin_a_capture(tmp_path: Path) -> None:
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    rows = [
        ["[ctry]", 'film = "vault-ctry"', 'sha256 = "0"'],
        ["[exit]", 'film = "vault-exit"', 'playone = "patch3"'],
        ["[intro]", 'film = "vault-intro"', 'sha256 = "1"'],
    ]
    text = "\n\n".join("\n".join(row) for row in rows) + "\n"
    pointers.write_text(text, encoding="utf-8")
    assert references.reference_films(tmp_path) == ("ctry", "intro")


def _row(root: Path, *fields: str) -> None:
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(["[ctry]", 'film = "vault-ctry"', 'sha256 = "0"', *fields])
    pointers.write_text(body + "\n", encoding="utf-8")


def test_the_committed_rows_name_valid_builds() -> None:
    for film in references.reference_films(REPO_ROOT):
        builds = references.read_reference(REPO_ROOT, film).builds
        assert {builds.makeone, builds.playone} <= set(references.BUILD_NAMES)


def test_an_omitted_build_is_patch3(tmp_path: Path) -> None:
    _row(tmp_path)
    assert references.read_reference(tmp_path, "ctry").builds == references.Builds(
        "patch3", "patch3"
    )
    _row(tmp_path, 'makeone = "unpatched"', 'reason = "EXIT hangs"')
    assert references.read_reference(tmp_path, "ctry").builds.playone == "patch3"


def test_a_row_names_its_builds(tmp_path: Path) -> None:
    _row(tmp_path, 'makeone = "unpatched"', 'playone = "patch3"', 'reason = "EXIT hangs"')
    assert references.read_reference(tmp_path, "ctry").builds == references.Builds(
        "unpatched", "patch3", "EXIT hangs"
    )


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        (['makeone = "patch3"', 'playone = "patched"'], "playone build 'patched'"),
        (['makeone = "patch3"', "playone = 3"], "playone build 3"),
        (['makeone = "unpatched"', 'playone = "patch3"'], "needs a reason"),
    ],
)
def test_a_row_without_valid_builds_is_refused(
    tmp_path: Path, fields: list[str], match: str
) -> None:
    _row(tmp_path, *fields)
    with pytest.raises(references.ReferenceCaptureError, match=match):
        references.read_reference(tmp_path, "ctry")


def _archive(directory: Path, makeone: str) -> Path:
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text(json.dumps({"makeone_sha256": makeone}), "utf-8")
    return directory / "CTRY.ALL"


def test_the_makeone_build_comes_from_the_archives_meta(tmp_path: Path) -> None:
    by_build = {build: sha for sha, build in references.MAKEONE_BUILDS.items()}
    build = references.archive_makeone_build
    patch3 = _archive(tmp_path / "a", by_build["patch3"])
    assert build(tmp_path, "vault-ctry", patch3) == "patch3"
    unpatched = _archive(tmp_path / "b", by_build["unpatched"])
    assert build(tmp_path, "vault-ctry", unpatched) == "unpatched"
    unknown = references.UNKNOWN_BUILD
    assert build(tmp_path, "vault-ctry", _archive(tmp_path / "c", "0" * 64)) == unknown
    assert build(tmp_path, "vault-ctry", tmp_path / "none" / "CTRY.ALL") == unknown


def test_a_linked_archive_takes_its_build_from_the_manifest(tmp_path: Path) -> None:
    by_build = {build: sha for sha, build in references.MAKEONE_BUILDS.items()}
    manifest = tmp_path / parity_layout.manifest_path("vault-ctry")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(f'makeone_sha256 = "{by_build["patch3"]}"\n', encoding="utf-8")
    linked = tmp_path / parity_layout.linked_path("vault-ctry", "CTRY.FLM")
    assert references.archive_makeone_build(tmp_path, "vault-ctry", linked) == "patch3"
    # The same manifest says nothing about an archive that was not rebuilt from it.
    other = tmp_path / "elsewhere" / "CTRY.ALL"
    assert references.archive_makeone_build(tmp_path, "vault-ctry", other) == "unknown"


def test_a_shipped_archive_of_the_demo_or_retail_game_is_unpatched(tmp_path: Path) -> None:
    build = references.archive_makeone_build
    for tree in ("stisldem", "stuntisl"):
        shipped = tmp_path / "corpus" / tree / "VAULT" / "CTRY.ALL"
        assert build(tmp_path, "vault-ctry", shipped) == "unpatched"
    community = tmp_path / "corpus" / "siarchive" / "Films" / "NewPLAY" / "TOD.ALL"
    assert build(tmp_path, "vault-tod", community) == "unknown"


def test_the_committed_ctry_and_intro_rows_accept_their_shipped_demo_archives() -> None:
    for film in ("ctry", "intro"):
        shipped = REPO_ROOT / "corpus" / "stisldem" / "VAULT" / f"{film.upper()}.ALL"
        references.require_builds(
            REPO_ROOT,
            f"vault-{film}",
            playone="unpatched",
            makeone=references.archive_makeone_build(REPO_ROOT, f"vault-{film}", shipped),
        )


def test_an_archive_of_unknown_build_is_refused_when_the_row_names_one(tmp_path: Path) -> None:
    _row(tmp_path, 'makeone = "unpatched"', 'reason = "x"')
    with pytest.raises(references.ReferenceCaptureError, match="cannot be determined"):
        references.require_builds(tmp_path, "vault-ctry", makeone=references.UNKNOWN_BUILD)
    references.require_builds(tmp_path, "vault-other", makeone=references.UNKNOWN_BUILD)


def test_a_matching_pair_is_accepted(tmp_path: Path) -> None:
    _row(tmp_path, 'makeone = "unpatched"', 'playone = "patch3"', 'reason = "x"')
    references.require_builds(tmp_path, "vault-ctry", playone="patch3", makeone="unpatched")
    references.require_builds(tmp_path, "vault-ctry", playone="patch3")  # makeone not used
    references.require_builds(tmp_path, "vault-other", playone="unpatched")  # no row, no pair


def test_a_mismatched_pair_is_refused(tmp_path: Path) -> None:
    by_build = {build: sha for sha, build in references.MAKEONE_BUILDS.items()}
    _row(tmp_path, 'makeone = "patch3"', 'playone = "patch3"')
    with pytest.raises(references.ReferenceCaptureError, match=r"unpatched PLAYONE.*names patch3"):
        references.require_builds(tmp_path, "vault-ctry", playone="unpatched")
    archive = _archive(tmp_path / "arch", by_build["unpatched"])
    with pytest.raises(references.ReferenceCaptureError, match=r"unpatched MAKEONE.*names patch3"):
        references.require_builds(
            tmp_path,
            "vault-ctry",
            makeone=references.archive_makeone_build(tmp_path, "vault-ctry", archive),
        )
