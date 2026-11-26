"""`stunt_reel.markdown_links`: Markdown prose with code blanked, the link and heading regexes."""

from __future__ import annotations

lazy from pathlib import Path

from stunt_reel.markdown_links import (
    HEADING_REGEX,
    LINK_DEFINITION_REGEX,
    MARKDOWN_LINK_REGEX,
    SECTION_NUMBER_REGEX,
    URL_SCHEME_REGEX,
    anchor_matches,
    anchors,
    extract_links,
    headings,
    prose,
    resolve_target,
    slug,
)


def _blank(line: str) -> str:
    return " " * len(line)


def test_blanks_fenced_blocks_and_inline_code_in_place() -> None:
    lines = ["# Title `code`", "", "```sh", "# 2026-11-06 sweep", "```", "See [a](b.md)."]
    blanked = ["# Title" + _blank(" `code`"), "", *map(_blank, lines[2:5]), lines[5]]
    assert prose("\n".join(lines) + "\n") == "\n".join(blanked) + "\n"


def test_inline_code_may_stay_unblanked() -> None:
    """The catalog checker reads links inside inline code, so it asks prose to leave them."""
    text = "a `code` b\n```\nfenced\n```\n"
    assert prose(text, inline_code=False) == "a `code` b\n   \n      \n   \n"


def test_a_heading_slug_is_githubs_anchor() -> None:
    """Lower case, punctuation dropped and spaces to hyphens, as GitHub names a heading."""
    assert (
        slug("2.1 Explicit scope boundaries & non-goals")
        == "21-explicit-scope-boundaries--non-goals"
    )
    assert slug("`stunt-core` crate") == "stunt-core-crate"
    assert slug("  [MEM-VSYNC-03DA]  ") == "mem-vsync-03da"


def test_keeps_every_line_ending() -> None:
    text = "a\r\n```\r\nb `c`\r\n```\r\nd"
    blanked = prose(text)
    assert len(blanked) == len(text)
    assert blanked.splitlines(keepends=True) == ["a\r\n", "   \r\n", "     \r\n", "   \r\n", "d"]


def test_an_unclosed_fence_blanks_to_the_end() -> None:
    assert prose("a\n```\nb\n") == "a\n   \n \n"


def test_reference_definitions_skip_footnotes() -> None:
    text = '[^1]: A note, not a link.\n[p]: ../plan.md#x\n   [q]: <../q.md> "Q"\n'
    assert [m.group(1) for m in LINK_DEFINITION_REGEX.finditer(text)] == ["../plan.md#x", "../q.md"]


def test_inline_links_take_the_target_without_brackets_or_title() -> None:
    text = 'See [a](a.md#x), ![b](<b.png> "B") and [c][p].'
    assert [m.group(1) for m in MARKDOWN_LINK_REGEX.finditer(text)] == ["a.md#x", "b.png"]


def test_a_url_scheme_starts_a_target_that_is_not_a_repo_path() -> None:
    assert [
        bool(URL_SCHEME_REGEX.match(t))
        for t in ("https://x", "mailto:a@b.c", "../a.md", "a.md#x:y")
    ] == [
        True,
        True,
        False,
        False,
    ]


def test_a_heading_is_one_to_six_marks_then_a_space() -> None:
    lines = ("# T", "###### T", "####### T", "#32 then wrapped", "#", " # T")
    assert [bool(HEADING_REGEX.match(line)) for line in lines] == [
        True,
        True,
        False,
        False,
        False,
        False,
    ]
    match = HEADING_REGEX.match("## 4.1 Ruled out  ")
    assert match is not None
    assert match.groups() == ("##", "4.1 Ruled out")


def test_a_section_number_is_digits_and_dots_then_a_space() -> None:
    texts = ("5. Ruled out", "4.1 Ruled out", "4.1. Ruled out", "5.Ruled out", "v2 Ruled out")
    assert [m[0] if (m := SECTION_NUMBER_REGEX.match(t)) else None for t in texts] == [
        "5. ",
        "4.1 ",
        "4.1. ",
        None,
        None,
    ]


def test_extract_links_reads_inline_and_reference_targets_in_order() -> None:
    """Both link forms count, at their document line."""
    text = 'See [a](a.md#x).\n\n![b](<b.png> "B")\n\n[p]: ../plan.md#goal\n'
    assert [(link.target, link.line) for link in extract_links(text)] == [
        ("a.md#x", 1),
        ("b.png", 3),
        ("../plan.md#goal", 5),
    ]


def test_extract_links_ignores_code_samples() -> None:
    """A link-shaped sample in inline code or a fenced block is prose."""
    text = "Use `[a](a.md)` here.\n\n```markdown\n[b](b.md)\n```\n"
    assert extract_links(text) == []


def test_headings_keep_duplicates_and_document_order() -> None:
    """A heading's text keeps its inline code, and two headings of the same text both appear."""
    assert headings("# A `x`\n```\n# B\n```\n## A\n") == ["A `x`", "A"]


def test_anchors_number_duplicate_headings_in_order() -> None:
    """A second and third ``Same`` become ``same-1`` and ``same-2``; a literal ``same-1`` counts."""
    assert anchors("# Same\n\n## Same\n\n### Same\n") == {"same", "same-1", "same-2"}
    assert anchors("# Same\n\n## Same-1\n\n### Same\n") == {"same", "same-1", "same-2"}


def test_anchors_include_html_ids_names_and_tokens() -> None:
    """An element's id, a name, and a bracketed token are all fragment targets."""
    text = "# T\n\n<a id=\"First\"></a>\n\n<span name='second'></span>\n\n[MEM-SOD-VM]\n"
    assert {"First", "second", "mem-sod-vm"} <= anchors(text)


def test_anchors_ignore_code_samples() -> None:
    """An anchor-shaped sample in code defines no anchor, nor does a token in backticks."""
    text = '```html\n<a id="sample"></a>\n```\n\n`<a id="inline"></a>` and `[MEM-SOD-VM]`\n'
    found = anchors(text)
    assert {"sample", "inline", "mem-sod-vm"}.isdisjoint(found)


def test_anchor_matches_case_insensitively_or_by_slug() -> None:
    """A fragment may name a token's case variant, an id exactly, or a heading's slug."""
    found = {"about", "mem-sod-vm", "First"}
    assert anchor_matches("about", found)
    assert anchor_matches("MEM-SOD-VM", found)
    assert anchor_matches("First", found)
    assert not anchor_matches("first", found)
    assert not anchor_matches("Other", found)


def test_resolve_target_keeps_the_lexical_path_and_fragment(tmp_path: Path) -> None:
    """A target is resolved for existence but normalized lexically for the repository's rules."""
    source = tmp_path / "docs" / "n.md"
    resolved = resolve_target(source, "../research/x.md#y", tmp_path)
    assert resolved is not None
    assert resolved.file == (tmp_path / "research" / "x.md").resolve()
    research = "research"
    assert resolved.relative == f"{research}/x.md"
    assert resolved.fragment == "y"
    assert resolve_target(source, "https://x", tmp_path) is None
    fragment_only = resolve_target(source, "#section", tmp_path)
    assert fragment_only is not None
    docs = "docs"
    assert fragment_only.relative == f"{docs}/n.md"
