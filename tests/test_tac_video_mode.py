"""Reading the VGA mode: the parser, the framed transport and the mock's settable mode."""

from __future__ import annotations

import pytest

from stunt_reel.tac.transport import MockTransport, _FramedTransport, parse_video_mode

#: A real reply line, from the MAKEONE spike (2026-10-29).
GRAPHICS_REPLY = "VGA mode info: | mode=M_VGA vref=70.087Hz href=31468.750Hz chrclk=3146875.000Hz dotclk=25175000.000Hz"
TEXT_REPLY = "VGA mode info: | mode=M_TEXT vref=70.087Hz href=31468.750Hz"


def test_parse_video_mode_reads_the_mode_token() -> None:
    assert parse_video_mode([GRAPHICS_REPLY]) == "M_VGA"
    assert parse_video_mode(["noise", TEXT_REPLY]) == "M_TEXT"


def test_parse_video_mode_rejects_a_reply_without_a_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        parse_video_mode(["*** Debugger command not recognized"])


def test_the_framed_transport_asks_the_debugger() -> None:
    asked: list[str] = []

    class Canned(_FramedTransport):
        def request(self, command: str) -> list[str]:
            asked.append(command)
            return [TEXT_REPLY]

    assert Canned().video_mode() == "M_TEXT"
    assert asked == ["VGA MODE"]


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
