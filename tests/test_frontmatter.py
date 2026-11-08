"""A markdown file's leading `---` block reads as scalar fields and the body after it."""

from __future__ import annotations

import pytest

from stunt_reel.frontmatter import FrontmatterError, read_frontmatter


def test_reads_scalars_and_returns_the_body() -> None:
    fields, body = read_frontmatter(
        '---\ntitle: Docs streamline\nissue: 307\noutcome: ""\n---\n# H\n'
    )
    assert fields == {"title": "Docs streamline", "issue": 307, "outcome": ""}
    assert body == "# H\n"


def test_text_without_a_block_is_all_body() -> None:
    assert read_frontmatter("# H\n") == ({}, "# H\n")


def test_quoted_value_keeps_colons() -> None:
    assert read_frontmatter('---\nsummary: "a: b"\n---\n')[0] == {"summary": "a: b"}


def test_quoted_value_unescapes_quotes() -> None:
    assert read_frontmatter('---\nsummary: "say \\"hi\\""\n---\n')[0] == {"summary": 'say "hi"'}


def test_quoted_value_unescapes_backslashes() -> None:
    text = '---\ntitle: "C:\\\\dir\\\\ \\"q\\\\\\""\n---\n'
    assert read_frontmatter(text)[0] == {"title": 'C:\\dir\\ "q\\"'}


def test_an_unquoted_backslash_is_literal() -> None:
    assert read_frontmatter("---\ntitle: C:\\dir\n---\n")[0] == {"title": "C:\\dir"}


@pytest.mark.parametrize(
    "value", ['"`RES\\` items"', '"a\\nb"', '"tab\\t"', '"ends in \\"', '"\\\\\\x"']
)
def test_a_quoted_value_with_another_escape_raises(value: str) -> None:
    """GitHub's YAML rejects an unknown escape; ``\\n`` and ``\\t`` are valid YAML but never meant."""
    with pytest.raises(FrontmatterError, match=r"^line 2: "):
        read_frontmatter(f"---\nsummary: {value}\n---\n")


@pytest.mark.parametrize(
    "text", ["---\ntitle: x\n", "---\nnot a pair\n---\n", "---\na: 1\na: 2\n---\n"]
)
def test_malformed_blocks_raise(text: str) -> None:
    with pytest.raises(FrontmatterError):
        read_frontmatter(text)


@pytest.mark.parametrize(
    ("text", "line"),
    [("---\ntitle: x\n", 1), ("---\nnot a pair\n---\n", 2), ("---\na: 1\na: 2\n---\n", 3)],
)
def test_malformed_block_error_names_the_line(text: str, line: int) -> None:
    with pytest.raises(FrontmatterError, match=rf"^line {line}: "):
        read_frontmatter(text)
