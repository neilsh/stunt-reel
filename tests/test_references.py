"""The reference pointer: a committed file pins a film's one capture by content hash."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

import pytest

from stunt_reel import capture_store, dataroot, parity_layout, references
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
        reference = references.read_reference(REPO_ROOT, film)
        assert {reference.builds.makeone, reference.builds.playone} <= set(references.BUILD_NAMES)
        assert set(reference.expected) <= set(references.RENDERER_CLASSES)


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


def test_an_archive_with_the_manifests_bytes_takes_its_build_from_the_manifest(
    tmp_path: Path,
) -> None:
    """A copy elsewhere, such as a pinned sibling, is the manifest's archive by its hash."""
    by_build = {build: sha for sha, build in references.MAKEONE_BUILDS.items()}
    copy = tmp_path / "siarchive" / "CTRY.ALL"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b"built")
    manifest = tmp_path / parity_layout.manifest_path("vault-ctry")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f'all_sha256 = "{hashlib.sha256(b"built").hexdigest()}"\n'
        f'makeone_sha256 = "{by_build["patch3"]}"\n',
        encoding="utf-8",
    )
    assert references.archive_makeone_build(tmp_path, "vault-ctry", copy) == "patch3"
    copy.write_bytes(b"other bytes")
    assert references.archive_makeone_build(tmp_path, "vault-ctry", copy) == "unknown"


def test_a_shipped_archive_of_the_demo_or_retail_game_is_unpatched(tmp_path: Path) -> None:
    build = references.archive_makeone_build
    for tree in ("stisldem", "stuntisl"):
        shipped = dataroot.corpus_root() / tree / "VAULT" / "CTRY.ALL"
        assert build(tmp_path, "vault-ctry", shipped) == "unpatched"
    community = dataroot.corpus_root() / "siarchive" / "Films" / "NewPLAY" / "TOD.ALL"
    assert build(tmp_path, "vault-tod", community) == "unknown"


def test_the_committed_ctry_and_intro_rows_accept_their_shipped_demo_archives() -> None:
    for film in ("ctry", "intro"):
        shipped = dataroot.corpus_root() / "stisldem" / "VAULT" / f"{film.upper()}.ALL"
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


PIN = "9de1bc1e8dbe491a56edd899b7c333cb78e5251cbe1e4ed75610dbc081aeb9a9"


def test_a_row_pins_its_archive(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, f'all_sha256 = "{PIN}"')
    assert references.read_reference(tmp_path, "ctry").all_sha256 == PIN


def test_a_row_without_an_archive_pin_has_none(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3)
    assert references.read_reference(tmp_path, "ctry").all_sha256 is None


@pytest.mark.parametrize("value", ['"abc"', '"' + "G" * 64 + '"', "3"])
def test_a_malformed_archive_pin_is_refused(tmp_path: Path, value: str) -> None:
    _row(tmp_path, PATCH3, f"all_sha256 = {value}")
    with pytest.raises(references.ReferenceCaptureError, match=r"\[ctry\].*all_sha256"):
        references.read_reference(tmp_path, "ctry")


def test_read_pin_finds_the_row_by_slug(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, f'all_sha256 = "{PIN}"')
    assert references.read_pin(tmp_path, "vault-ctry") == PIN
    assert references.read_pin(tmp_path, "vault-land") is None


#: A measured ``crates/`` tree and capture pin, as an expected table records them.
TREE = "641cffd3bfc895719f6078b33d7a0232e5f1750c"
CAPTURE = "9869444de53c653214144b83c2bdbce4a686a16f5189a1f5a94f6eb19605ed49"


def _expected(renderer: str = "gpu", **changes: str | None) -> list[str]:
    """A ``[ctry.expected.<renderer>]`` table with *changes* to its fields; ``None`` drops one."""
    fields = {
        "ssim": "0.8725",
        "iou": "0.9897",
        "crates": f'"{TREE}"',
        "sha256": f'"{CAPTURE}"',
        "commit": '"740c608"',
        "adapter": '"NVIDIA GeForce RTX 4070"',
    } | changes
    lines = (f"{key} = {value}" for key, value in fields.items() if value is not None)
    return [f"[ctry.expected.{renderer}]", *lines]


def test_a_row_reads_its_expected_scores_and_noise_sigma(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, "noise_sigma = 0.000303", *_expected())
    reference = references.read_reference(tmp_path, "ctry")
    assert dict(reference.expected) == {
        "gpu": references.Expected(
            0.8725, 0.9897, TREE, CAPTURE, "NVIDIA GeForce RTX 4070", commit="740c608"
        )
    }
    assert "lavapipe" not in reference.expected
    assert reference.noise_sigma == 0.000303


def test_an_expected_table_without_a_commit_reads_its_tree_and_pins(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, *_expected(commit=None, all_sha256=f'"{PIN}"'))
    expected = references.read_reference(tmp_path, "ctry").expected["gpu"]
    assert (expected.crates, expected.sha256, expected.all_sha256) == (TREE, CAPTURE, PIN)
    assert expected.commit is None


def test_an_expected_table_may_name_a_sha256_tree(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, *_expected(crates=f'"{CAPTURE}"'))
    assert references.read_reference(tmp_path, "ctry").expected["gpu"].crates == CAPTURE


def test_a_row_without_expected_scores_reads_empty(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3)
    reference = references.read_reference(tmp_path, "ctry")
    assert dict(reference.expected) == {}
    assert reference.noise_sigma is None


def test_the_expected_scores_are_read_only(tmp_path: Path) -> None:
    _row(tmp_path, PATCH3, *_expected())
    expected = references.read_reference(tmp_path, "ctry").expected
    with pytest.raises(TypeError):
        expected["lavapipe"] = expected["gpu"]  # type: ignore[index]


def test_an_integer_score_reads_as_a_float(tmp_path: Path) -> None:
    """TOML writes a whole number without a point; ``1`` is a score as ``1.0`` is, a bool is not."""
    _row(tmp_path, PATCH3, "noise_sigma = 1", *_expected(ssim="1", iou="0"))
    reference = references.read_reference(tmp_path, "ctry")
    scores = reference.expected["gpu"]
    assert (scores.ssim, scores.iou, reference.noise_sigma) == (1.0, 0.0, 1.0)
    assert all(type(value) is float for value in (scores.ssim, scores.iou, reference.noise_sigma))


@pytest.mark.parametrize(
    ("lines", "field"),
    [
        (_expected("warp"), "expected.warp"),
        (_expected(ssim=None), "expected.gpu.ssim"),
        (_expected(ssim='"0.8725"'), "expected.gpu.ssim"),
        (_expected(ssim="1.5"), "expected.gpu.ssim"),
        (_expected(ssim="true"), "expected.gpu.ssim"),
        (_expected(iou="-0.1"), "expected.gpu.iou"),
        (_expected(commit='"xyz"'), "expected.gpu.commit"),
        (_expected(commit='"740C608"'), "expected.gpu.commit"),
        (_expected(crates=None), "expected.gpu.crates"),
        (_expected(crates='"641cffd"'), "expected.gpu.crates"),
        (_expected(crates=f'"{TREE.upper()}"'), "expected.gpu.crates"),
        (_expected(sha256=None), "expected.gpu.sha256"),
        (_expected(sha256='"0"'), "expected.gpu.sha256"),
        (_expected(all_sha256="1"), "expected.gpu.all_sha256"),
        (_expected(adapter='""'), "expected.gpu.adapter"),
        (_expected(noise_sigma="0.1"), "expected.gpu.noise_sigma"),
        (["[ctry.expected]", 'gpu = "x"'], "expected.gpu"),
        (["expected = 3"], "expected"),
        (["noise_sigma = 0"], "noise_sigma"),
        (["noise_sigma = -1"], "noise_sigma"),
    ],
)
def test_a_malformed_expected_entry_is_named(tmp_path: Path, lines: list[str], field: str) -> None:
    _row(tmp_path, PATCH3, *lines)
    with pytest.raises(references.ReferenceCaptureError) as refused:
        references.read_reference(tmp_path, "ctry")
    message = str(refused.value)
    assert str(tmp_path / parity_layout.REFERENCES_FILE) in message
    assert "[ctry]" in message
    assert field in message
