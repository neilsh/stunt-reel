"""The Python side of ``stuntreel link``: argv, exit codes, and the binary it runs."""

from __future__ import annotations

import subprocess
from pathlib import Path
lazy from collections.abc import Sequence

import pytest

from stunt_reel import link, parity_layout, parity_pipeline


class FakeRunner:
    """Records each call and answers with a chosen exit code and stderr."""

    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), cwd))
        return subprocess.CompletedProcess(list(argv), self.returncode, "", self.stderr)


def test_build_passes_manifest_game_and_out(tmp_path: Path) -> None:
    run = FakeRunner()
    manifest, game, out = tmp_path / "m.toml", tmp_path / "game", tmp_path / "X.ALL"

    link.build_archive(manifest, game, out, cwd=tmp_path, run=run)

    assert run.calls == [
        (
            [
                str(link.binary_path()),
                "link",
                "build",
                str(manifest),
                "--game",
                str(game),
                "-o",
                str(out),
            ],
            tmp_path,
        )
    ]


def test_extract_passes_its_flags(tmp_path: Path) -> None:
    run = FakeRunner()
    archive, flm, out = tmp_path / "X.ALL", tmp_path / "X.FLM", tmp_path / "m.toml"

    link.extract_manifest(archive, flm, "corpus/stuntisl", "ab" * 32, out, cwd=tmp_path, run=run)

    [(argv, cwd)] = run.calls
    assert cwd == tmp_path
    assert argv[:4] == [str(link.binary_path()), "link", "extract", str(archive)]
    flags = dict(zip(argv[4::2], argv[5::2], strict=True))
    assert flags == {
        "--flm": str(flm),
        "--game": "corpus/stuntisl",
        "--makeone-sha256": "ab" * 32,
        "-o": str(out),
    }


def test_exit_3_is_not_linkable_and_exit_1_is_an_error(tmp_path: Path) -> None:
    args = (tmp_path / "m.toml", tmp_path / "game", tmp_path / "X.ALL")
    with pytest.raises(link.NotLinkable, match="chunk 0x7E01"):
        link.build_archive(*args, cwd=tmp_path, run=FakeRunner(3, "not linkable: chunk 0x7E01\n"))
    with pytest.raises(link.LinkError, match="sha256 differs") as caught:
        link.build_archive(*args, cwd=tmp_path, run=FakeRunner(1, "sha256 differs\n"))
    assert not isinstance(caught.value, link.NotLinkable)


def test_ensure_binary_skips_cargo_when_the_binary_is_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = FakeRunner()
    monkeypatch.setattr(link, "binary_locked", lambda _path: True)
    assert link.ensure_binary(run=run) == link.binary_path()
    assert run.calls == []

    monkeypatch.setattr(link, "binary_locked", lambda _path: False)
    link.ensure_binary(run=run)
    assert [argv for argv, _ in run.calls] == [["cargo", "build", "--release", "-p", "stunt-cli"]]


def test_a_failed_cargo_build_is_a_link_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(link, "binary_locked", lambda _path: False)
    with pytest.raises(link.LinkError, match="could not compile"):
        link.ensure_binary(run=FakeRunner(101, "error: could not compile\n"))


def test_layout_paths() -> None:
    assert parity_layout.manifest_path("flmonly-balloon") == Path(
        "manifests/all/flmonly-balloon.toml"
    )
    assert parity_layout.linked_path("flmonly-balloon", "balloon.flm") == Path(
        "target/linked/flmonly-balloon/BALLOON.ALL"
    )


def test_build_release_and_ensure_binary_run_one_command() -> None:
    calls: list[list[str]] = []

    def fake(
        cmd: list[str], _env: dict[str, str] | None, _timeout: float | None
    ) -> tuple[int, str]:
        calls.append(cmd)
        return 0, ""

    parity_pipeline.build_release(run=fake)
    assert calls == [list(link.BUILD_ARGV)]


def test_a_missing_program_is_a_link_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(link, "binary_path", lambda: tmp_path / "no-such-stuntreel.exe")
    with pytest.raises(link.LinkError, match="no-such-stuntreel"):
        link.build_archive(tmp_path / "m.toml", tmp_path, tmp_path / "X.ALL", cwd=tmp_path)
