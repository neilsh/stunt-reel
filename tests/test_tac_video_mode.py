"""The mock transport's settable video mode."""

from __future__ import annotations

import pytest

from stunt_reel.tac.transport import MockTransport


def test_mock_video_mode_follows_its_source() -> None:
    modes = iter(["M_VGA", "M_TEXT"])
    mock = MockTransport()
    assert mock.video_mode() == "M_VGA"
    mock.video_mode_source = lambda: next(modes)
    assert [mock.video_mode(), mock.video_mode()] == ["M_VGA", "M_TEXT"]


def test_a_closed_mock_refuses_video_mode() -> None:
    mock = MockTransport()
    mock.close()
    with pytest.raises(ConnectionError):
        mock.video_mode()
