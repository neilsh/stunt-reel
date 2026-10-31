"""``mise run capture-digest``: the hash a promotion pins, and the entry to paste."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel import parity_layout, references

if TYPE_CHECKING:
    import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import capture_digest  # noqa: E402


def _capture(root: Path, slug: str, run: str) -> Path:
    directory = root / parity_layout.frames_path(slug, run)
    directory.mkdir(parents=True)
    (directory / "meta.json").write_text("{}", encoding="utf-8")
    (directory / "tick_0001.idx").write_bytes(b"\x01\x02")
    return directory


def test_prints_the_digest_and_the_entry_that_promotes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = _capture(tmp_path, "vault-ctry", "999")
    digest = references.capture_digest(directory)
    assert capture_digest.main(["vault-ctry", "999"], root=tmp_path) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "build/parity/captures/vault-ctry/frames/999"
    assert out[1] == f'sha256 = "{digest}"'
    # The committed references.toml has a [ctry] entry for vault-ctry, so the block follows.
    block = out[out.index("[ctry]") :]
    assert block == ["[ctry]", 'film = "vault-ctry"', 'capture = "999"', f'sha256 = "{digest}"']


def test_the_dir_form_hashes_the_same(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    directory = _capture(tmp_path, "vault-intro", "999")
    assert capture_digest.main(["--dir", str(directory)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[1] == f'sha256 = "{references.capture_digest(directory)}"'
    assert "[intro]" in out


def test_the_current_pin_is_recognised() -> None:
    lines = capture_digest.report("vault-ctry", "004", _pinned("ctry"))
    assert lines[-1] == "[ctry] already names this capture with this hash"


def test_a_directory_without_meta_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert capture_digest.main(["vault-ctry", "404"], root=tmp_path) == 1
    assert "not a capture" in capsys.readouterr().err


def _pinned(film: str) -> str:
    entries = capture_digest._entries()
    return str(entries[film]["sha256"])
