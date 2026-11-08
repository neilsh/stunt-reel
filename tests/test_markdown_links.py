"""`stunt_reel.markdown_links.prose`: Markdown text with code blanked, every position kept."""

from __future__ import annotations

from stunt_reel.markdown_links import prose


def _blank(line: str) -> str:
    return " " * len(line)


def test_blanks_fenced_blocks_and_inline_code_in_place() -> None:
    lines = ["# Title `code`", "", "```sh", "# 2026-11-06 sweep", "```", "See [a](b.md)."]
    blanked = ["# Title" + _blank(" `code`"), "", *map(_blank, lines[2:5]), lines[5]]
    assert prose("\n".join(lines) + "\n") == "\n".join(blanked) + "\n"


def test_keeps_every_line_ending() -> None:
    text = "a\r\n```\r\nb `c`\r\n```\r\nd"
    blanked = prose(text)
    assert len(blanked) == len(text)
    assert blanked.splitlines(keepends=True) == ["a\r\n", "   \r\n", "     \r\n", "   \r\n", "d"]


def test_an_unclosed_fence_blanks_to_the_end() -> None:
    assert prose("a\n```\nb\n") == "a\n   \n \n"
