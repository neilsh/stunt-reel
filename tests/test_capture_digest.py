"""``mise run capture-digest``: the hash a promotion pins, and the entry to paste."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import dataroot, parity_layout, references

if TYPE_CHECKING:
    import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import capture_digest  # noqa: E402


def _capture(root: Path, slug: str) -> Path:
    directory = root / parity_layout.frames_path(slug)
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text("{}", encoding="utf-8")
    (directory / "tick_0001.idx").write_bytes(b"\x01\x02")
    return directory


def test_prints_the_digest_and_the_entry_that_promotes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _capture(tmp_path, "vault-ctry")
    digest = references.capture_digest(directory)
    assert capture_digest.main(["vault-ctry"], root=tmp_path) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "captures/vault-ctry/frames"
    assert out[1] == f'sha256 = "{digest}"'
    # The committed references.toml has a [ctry] entry for vault-ctry, so the block follows.
    block = out[out.index("[ctry]") :]
    assert block == ["[ctry]", 'film = "vault-ctry"', f'sha256 = "{digest}"']


def test_the_dir_form_hashes_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _capture(tmp_path, "vault-intro")
    pointers = tmp_path / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    pointers.write_text(
        (dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setattr(dataroot, "REPO_ROOT", tmp_path)
    assert capture_digest.main(["--dir", str(directory)], root=tmp_path) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == f'sha256 = "{references.capture_digest(directory)}"'
    assert "[intro]" in out


def test_a_dir_outside_the_checkout_gets_no_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A copy elsewhere is not what parity reads, so no entry may pin it."""
    directory = _capture(tmp_path / "elsewhere", "vault-intro")
    monkeypatch.setattr(dataroot, "REPO_ROOT", tmp_path / "checkout")
    assert capture_digest.main(["--dir", str(directory)], root=tmp_path / "checkout") == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == f'sha256 = "{references.capture_digest(directory)}"'
    assert "[intro]" not in out
    assert "no references.toml entry" in out[-1]


def test_the_current_pin_is_recognised() -> None:
    entry = capture_digest._entries()["ctry"]
    lines = capture_digest.report("vault-ctry", str(entry["sha256"]))
    assert lines[-1] == "[ctry] already pins this capture"


def test_a_directory_without_meta_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_digest.main(["vault-ctry"], root=tmp_path) == 1
    assert "not a capture" in capsys.readouterr().err


def test_without_a_root_the_capture_is_read_from_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No checkout link is read: a film slug and --dir both resolve in the data root (ADR 0036)."""
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    dataroot.data_root.cache_clear()
    directory = _capture(tmp_path, "vault-intro")
    assert capture_digest.main(["vault-intro"]) == 0
    assert capture_digest.main(["--dir", str(directory)]) == 0
    assert "no references.toml entry" not in capsys.readouterr().out


def test_a_relative_capture_directory_reads_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "data"))
    dataroot.data_root.cache_clear()
    monkeypatch.chdir(tmp_path)
    _capture(tmp_path / "data", "vault-intro")
    assert capture_digest.main(["--dir", "captures/vault-intro/frames"]) == 0
