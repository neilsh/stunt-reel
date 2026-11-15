"""The research site's page URLs, link rewriting and front matter."""

from __future__ import annotations

import json
lazy from pathlib import Path

import pytest

from stunt_reel.site_pages import (
    REPO_URL,
    Site,
    link_target,
    page_text,
    page_url,
    rewrite_links,
)

_FILES = [
    "research/formats/INDEX.md",
    "research/formats/sod.md",
    "research/README.md",
    "research/parity/error-examples/a.png",
    "research/x.ksy",
    "docs/SPEC.md",
    "work/2026-11/1_a/images/b.png",
]
_DIRS = ["crates/core", "research/noindex"]


@pytest.fixture
def site(tmp_path: Path) -> Site:
    for name in _FILES:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    for name in _DIRS:
        (tmp_path / name).mkdir(parents=True)
    pages = {n: n for n in _FILES if n.startswith("research/") and n.endswith(".md")}
    pages["GLOSSARY.md"] = "glossary.md"
    return Site(root=tmp_path, pages=pages, published_dirs=("research",))


def test_page_url_lowercases_and_folds_index() -> None:
    assert page_url("research/formats/sod.md") == "/stunt-reel/research/formats/sod/"
    assert page_url("research/formats/INDEX.md") == "/stunt-reel/research/formats/"
    assert page_url("research/README.md") == "/stunt-reel/research/readme/"
    assert page_url("index.md") == "/stunt-reel/"


def test_page_url_rejects_unslugged_names() -> None:
    with pytest.raises(ValueError, match=r"a b.md"):
        page_url("research/a b.md")


_SRC = "research/formats/sod.md"
_CASES = [
    ("INDEX.md#magic", "/stunt-reel/research/formats/#magic"),
    ("../../GLOSSARY.md", "/stunt-reel/glossary/"),
    ("../formats/", "/stunt-reel/research/formats/"),
    ("../", "/stunt-reel/research/readme/"),
    ("../noindex/", f"{REPO_URL}/tree/main/research/noindex"),
    ("../x.ksy", f"{REPO_URL}/blob/main/research/x.ksy"),
    ("../../docs/SPEC.md#24-evidentiary", f"{REPO_URL}/blob/main/docs/SPEC.md#24-evidentiary"),
    ("../../crates/core/", f"{REPO_URL}/tree/main/crates/core"),
    (
        "../../work/2026-11/1_a/images/b.png",
        f"{REPO_URL}/blob/main/work/2026-11/1_a/images/b.png",
    ),
    (
        "../parity/error-examples/a.png",
        "/stunt-reel/media/research/parity/error-examples/a.png",
    ),
    ("https://example.com/a.md", "https://example.com/a.md"),
    ("#local", "#local"),
]


@pytest.mark.parametrize(("target", "expected"), _CASES)
def test_link_target(site: Site, target: str, expected: str) -> None:
    images: set[str] = set()
    assert link_target(target, _SRC, site, images) == expected
    wanted = {"research/parity/error-examples/a.png"} if "/media/" in expected else set()
    assert images == wanted


def test_link_target_refuses_escape(site: Site) -> None:
    with pytest.raises(ValueError, match=r"research/formats/sod.md"):
        link_target("../../../../x.md", _SRC, site, set())


def test_rewrite_links_inline_reference_and_code(site: Site) -> None:
    text = (
        "See [`sod` v2](sod.md) and [spec].\n\n[spec]: ../../docs/SPEC.md#tiers\n\n"
        "`[no](sod.md)`\n```\n[no](sod.md)\n```\n"
    )
    out = rewrite_links(text, _SRC, site, set())
    assert "[`sod` v2](/stunt-reel/research/formats/sod/)" in out
    assert f"[spec]: {REPO_URL}/blob/main/docs/SPEC.md#tiers" in out
    assert out.count("[no](sod.md)") == 2


def _fields(page: str) -> tuple[dict[str, object], str]:
    head, _, body = page.removeprefix("---\n").partition("\n---\n")
    fields: dict[str, object] = {}
    section = ""
    for line in head.splitlines():
        if line.startswith("  "):
            key, _, value = line.strip().partition(": ")
            fields[f"{section}.{key}"] = json.loads(value)
            continue
        key, _, value = line.partition(":")
        section = key
        if value.strip():
            fields[key] = json.loads(value.strip())
    return fields, body


NOTE = (
    '---\nsummary: "`.SOD` model: a **VM**."\n---\n'
    "# Spec: `.SOD` [format](x.md) **bytecode**\n\nBody [l](sod.md).\n"
)


def test_page_text_title_from_h1_and_description_from_summary(site: Site) -> None:
    fields, body = _fields(page_text(NOTE, _SRC, site, set()))
    assert fields["title"] == "Spec: .SOD format bytecode"
    assert fields["description"] == "`.SOD` model: a **VM**."
    assert fields["editUrl"] == f"{REPO_URL}/blob/main/research/formats/sod.md"
    assert not body.lstrip().startswith("# ")
    assert "[l](/stunt-reel/research/formats/sod/)" in body


def test_page_text_sidebar_labels(site: Site) -> None:
    text = "# T\n"
    for source, label in [
        ("research/formats/sod.md", "sod"),
        ("research/formats/INDEX.md", "Index"),
        ("research/README.md", "About this folder"),
    ]:
        fields, _ = _fields(page_text(text, source, site, set()))
        assert fields["sidebar.label"] == label


def test_page_text_without_frontmatter_drops_leading_comment(site: Site) -> None:
    text = "<!-- Generated by mise run fix; do not edit. -->\n\n# Research map\n\n- x\n"
    fields, body = _fields(page_text(text, "research/MAP.md", site, set()))
    assert fields["title"] == "Research map"
    assert "description" not in fields
    assert "<!--" not in body


def test_page_text_keeps_a_handwritten_title(site: Site) -> None:
    text = '---\ntitle: "How to read these notes"\n---\n\n# Evidence tags\n'
    fields, body = _fields(page_text(text, "site/reading.md", site, set()))
    assert fields["title"] == "How to read these notes"
    assert "# Evidence tags" in body
    assert fields["editUrl"] == f"{REPO_URL}/blob/main/site/reading.md"


def test_page_text_h1_inside_code_is_not_the_title(site: Site) -> None:
    text = "```\n# not a title\n```\n\n# Real\n"
    fields, body = _fields(page_text(text, _SRC, site, set()))
    assert fields["title"] == "Real"
    assert "# not a title" in body


def test_page_text_without_a_title_names_the_source(site: Site) -> None:
    with pytest.raises(ValueError, match=r"research/formats/sod.md"):
        page_text("no heading\n", _SRC, site, set())
