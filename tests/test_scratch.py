"""Scratch directories are created with the default mode, not 0o700."""

from __future__ import annotations

from stunt_reel.scratch import scratch_dir


def test_scratch_dir_is_usable_and_removed() -> None:
    with scratch_dir(prefix="stunt-scratch-test-") as path:
        assert path.is_dir()
        (path / "probe.txt").write_text("x", encoding="utf-8")
        assert (path / "probe.txt").read_text(encoding="utf-8") == "x"
    assert not path.exists()
