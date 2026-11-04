"""The make-all command: ids, refusals, validation and what gets published."""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

from archive_helpers import build_all
from stunt_reel import capture_store, dataroot, link, parity_layout
from stunt_reel.all_archive import ArchiveMeta
from tac_mock import StagedRepo, makeone_launcher

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
ARCHIVE = build_all([b"one", b"two"])


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("make_all", SCRIPTS / "make_all.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _load()
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    # The real poll interval is 2 s per wait; the mock guest answers at once.
    monkeypatch.setattr(
        module.makeone, "make_all", functools.partial(module.makeone.make_all, poll=0.0)
    )
    # The real extract builds and runs the release binary; tests that need it pass a fake.
    monkeypatch.setattr(module, "extract_with_binary", FakeExtract())
    return module


class FakeExtract:
    """Stands in for ``stuntreel link extract``: records its arguments, then writes or raises."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[Path, Path, str, str, Path]] = []

    def __call__(self, archive: Path, flm: Path, game: str, makeone_sha256: str, out: Path) -> None:
        self.calls.append((archive, flm, game, makeone_sha256, out))
        if self.error is not None:
            raise self.error
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("# manifest\n", encoding="utf-8")


def _args(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    film: Path,
    game_root: Path,
    *extra: str,
) -> Any:
    argv = [
        "make_all.py",
        "--film",
        str(film),
        "--game-root",
        str(game_root),
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return script.parse_args()


def _archives(slug: str = "vault-ctry") -> list[Path]:
    """The film's stored archive, as a list so a test can say there is exactly one or none."""
    stored = capture_store.current(dataroot.data_root() / parity_layout.archive_path(slug))
    return [] if stored is None else [stored]


def test_a_run_publishes_the_archive_with_meta(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--timeout", "30")

    assert script.run(args, launch) == 0

    (directory,) = _archives()
    assert (directory / "CTRY.ALL").read_bytes() == ARCHIVE
    meta = ArchiveMeta.from_json((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta.flm_sha256 == hashlib.sha256(staged_repo.film.read_bytes()).hexdigest()
    assert meta.all_sha256 == hashlib.sha256(ARCHIVE).hexdigest()
    assert dict(meta.game_files)["MAKEONE.EXE"] == (game_root / "MAKEONE.EXE").stat().st_size


def test_a_second_run_replaces_the_archive(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    first, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)
    assert script.run(args, first) == 0
    (directory,) = _archives()

    other = build_all([b"other"])
    second, _state = makeone_launcher(text_after=1, archive=other)
    assert script.run(args, second) == 0

    assert _archives() == [directory]
    assert (directory / "CTRY.ALL").read_bytes() == other
    assert [p.name for p in directory.parent.iterdir() if p.suffix != ".lock"] == ["archives"]


def test_name_overrides_the_derived_slug_and_a_bad_one_is_refused(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--name", "my-ctry")
    assert script.run(args, launch) == 0
    assert len(_archives("my-ctry")) == 1

    refused, refused_state = makeone_launcher(text_after=1, archive=ARCHIVE)
    bad = _args(script, monkeypatch, staged_repo.film, game_root, "--name", "Bad Name")
    assert script.run(bad, refused) == 2
    assert not refused_state.started


def test_a_non_archive_is_rejected_and_publishes_nothing(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=b"junk")
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch) == 1
    assert _archives() == []


def test_a_publish_failure_is_a_make_all_line_and_exit_1(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def full_disk(*_args: object, **_kwargs: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(script, "publish_archive", full_disk)
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch) == 1
    assert "[make-all] could not store the archive: disk full" in capsys.readouterr().err


def test_a_missing_game_file_is_a_make_all_line_and_exit_1(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)
    original = script.makeone.make_all

    def vanish(*a: Any, **k: Any) -> bytes:
        data: bytes = original(*a, **k)
        (game_root / "MAKEONE.EXE").unlink()
        return data

    monkeypatch.setattr(script.makeone, "make_all", vanish)

    assert script.run(args, launch) == 1
    assert "[make-all]" in capsys.readouterr().err
    assert _archives() == []


def test_a_timeout_exits_1_and_leaves_no_mount(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    launch, _state = makeone_launcher(text_after=None, archive=None)
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--timeout", "0.01")

    assert script.run(args, launch) == 1
    assert _archives() == []
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


def test_an_archives_directory_of_numbered_runs_is_refused_before_makeone(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    run = dataroot.data_root() / parity_layout.archive_path("vault-ctry") / "001"
    run.mkdir(parents=True)
    (run / "meta.json").write_text("{}", encoding="utf-8")
    launch, state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)
    assert script.run(args, launch) == 2
    assert not state.started
    assert (run / "meta.json").is_file()


def _stored_meta(slug: str = "vault-ctry") -> ArchiveMeta:
    (directory,) = _archives(slug)
    return ArchiveMeta.from_json((directory / "meta.json").read_text(encoding="utf-8"))


def _publish(script: Any, monkeypatch: pytest.MonkeyPatch, film: Path, game_root: Path) -> Path:
    """Runs make-all once with the fixture's no-op extract; returns the stored archive."""
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    assert script.run(_args(script, monkeypatch, film, game_root), launch) == 0
    (directory,) = _archives()
    return directory / "CTRY.ALL"


def test_a_run_writes_the_manifest_after_publishing(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inside = dataroot.REPO_ROOT / "corpus" / "stuntisl"
    shutil.copytree(game_root, inside)
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    extract = FakeExtract()

    assert script.run(_args(script, monkeypatch, staged_repo.film, inside), launch, extract) == 0

    (directory,) = _archives()
    manifest = dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")
    assert extract.calls == [
        (
            directory / "CTRY.ALL",
            staged_repo.film,
            "corpus/stuntisl",
            _stored_meta().makeone_sha256,
            manifest,
        )
    ]
    assert "[make-all] wrote manifest manifests/all/vault-ctry.toml" in capsys.readouterr().out


def test_a_not_linkable_archive_still_exits_0_and_says_why(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    extract = FakeExtract(link.NotLinkable("chunk 0x7E01 matches no item of any game file"))
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch, extract) == 0

    out = capsys.readouterr().out
    assert "no manifest" in out
    assert "0x7E01" in out
    assert not (dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")).exists()


def test_a_link_error_after_publish_warns_and_exits_0(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch, FakeExtract(link.LinkError("boom"))) == 0

    assert "warning" in capsys.readouterr().err
    assert len(_archives()) == 1


def test_manifest_only_extracts_from_the_stored_archive_without_makeone(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    stored = _publish(script, monkeypatch, staged_repo.film, game_root)
    launch, state = makeone_launcher(text_after=1, archive=ARCHIVE)
    extract = FakeExtract()
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--manifest-only")

    assert script.run(args, launch, extract) == 0

    assert not state.started
    [(archive, flm, _game, makeone_sha256, out)] = extract.calls
    assert (archive, flm, makeone_sha256) == (
        stored,
        staged_repo.film,
        _stored_meta().makeone_sha256,
    )
    assert out == dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")


def test_manifest_only_without_a_stored_archive_exits_2(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    extract = FakeExtract()
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--manifest-only")
    assert script.run(args, None, extract) == 2
    assert "mise run make-all -- --film" in capsys.readouterr().err
    assert extract.calls == []


def test_manifest_only_for_another_flm_exits_2(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish(script, monkeypatch, staged_repo.film, game_root)
    staged_repo.film.write_bytes(b"FILM-edited")
    extract = FakeExtract()
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--manifest-only")

    assert script.run(args, None, extract) == 2
    assert "another .FLM" in capsys.readouterr().err
    assert extract.calls == []


def test_manifest_only_not_linkable_exits_1(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    _publish(script, monkeypatch, staged_repo.film, game_root)
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--manifest-only")
    assert script.run(args, None, FakeExtract(link.NotLinkable("chunk 0x7E01"))) == 1


@pytest.mark.parametrize("error", [link.NotLinkable("chunk 0x7E01"), link.LinkError("boom")])
def test_manifest_only_keeps_the_old_manifest_when_extraction_fails(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    error: link.LinkError,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _publish(script, monkeypatch, staged_repo.film, game_root)
    manifest = dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("# reviewed and committed\n", encoding="utf-8")
    args = _args(script, monkeypatch, staged_repo.film, game_root, "--manifest-only")
    capsys.readouterr()

    assert script.run(args, None, FakeExtract(error)) == 1

    assert manifest.read_text(encoding="utf-8") == "# reviewed and committed\n"
    assert "still takes precedence" in capsys.readouterr().out


def test_a_not_linkable_rerun_removes_the_old_manifest(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("# from an earlier run\n", encoding="utf-8")
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch, FakeExtract(link.NotLinkable("chunk 0x7E01"))) == 0

    assert not manifest.exists()
    assert "removed" in capsys.readouterr().out


def test_a_link_error_removes_the_old_manifest_too(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = dataroot.REPO_ROOT / parity_layout.manifest_path("vault-ctry")
    manifest.parent.mkdir(parents=True)
    manifest.write_text("# from an earlier run\n", encoding="utf-8")
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root)

    assert script.run(args, launch, FakeExtract(link.LinkError("boom"))) == 0

    assert not manifest.exists()
    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert "removed" in captured.out


def test_game_arg_records_a_dotted_path_inside_the_checkout_relative(
    script: Any,
) -> None:
    dotted = dataroot.REPO_ROOT / "corpus" / ".." / "corpus" / "stuntisl"
    assert script.game_arg(dotted) == "corpus/stuntisl"
