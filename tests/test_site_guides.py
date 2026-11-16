"""The rules every page under `site/guides/` keeps: plain prose, no code, ends with a reading list."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from stunt_reel.frontmatter import read_frontmatter

pytestmark = pytest.mark.docs

GUIDES = Path(__file__).resolve().parent.parent / "site" / "guides"
_MERMAID = re.compile(r"^```mermaid[ \t]*\n.*?^```[ \t]*$", re.MULTILINE | re.DOTALL)
_HEX = re.compile(r"\b0x[0-9A-Fa-f]+\b|\b[0-9][0-9A-Fa-f]*h\b")
_READ_NEXT_ITEM = re.compile(r"^- \[[^\]]+\]\([^)]+\.md(#[^)]*)?\)")


def _pages() -> list[Path]:
    return sorted(GUIDES.glob("*.md"))


def _read(path: Path) -> tuple[dict[str, str | int], str]:
    """The front matter and the body with its mermaid fences removed."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")  # a CRLF checkout
    fields, body = read_frontmatter(text)
    return fields, _MERMAID.sub("", body)


def test_the_five_guides_exist() -> None:
    assert {p.stem for p in _pages()} == {"films", "drawing", "island", "reconstruction", "process"}


def test_guides_have_a_title_and_the_cards_order() -> None:
    orders = {}
    for page in _pages():
        fields, _ = _read(page)
        assert isinstance(fields.get("title"), str), page.name
        orders[page.stem] = fields.get("order")
    # The order of the home page's cards (site/index.md).
    assert orders == {"films": 1, "drawing": 2, "island": 3, "reconstruction": 4, "process": 5}


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
def test_guides_hold_no_code(page: Path) -> None:
    _, body = _read(page)
    assert "`" not in body


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
def test_guides_hold_no_hex(page: Path) -> None:
    _, body = _read(page)
    assert _HEX.findall(body) == []


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
def test_guides_stay_under_1000_words(page: Path) -> None:
    _, body = _read(page)
    assert len(body.split()) < 1000


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.stem)
def test_guides_end_with_read_next(page: Path) -> None:
    _, body = _read(page)
    lines = body.splitlines()
    headings = [i for i, line in enumerate(lines) if line.startswith("## ")]
    assert headings, page.name
    assert lines[headings[-1]] == "## Read next"
    items = [line for line in lines[headings[-1] + 1 :] if line.strip()]
    assert items, page.name
    for line in items:
        assert _READ_NEXT_ITEM.match(line), line
