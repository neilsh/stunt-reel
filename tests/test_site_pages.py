"""The research site's page URLs, link rewriting and front matter."""

from __future__ import annotations

lazy from pathlib import Path

import pytest

from stunt_reel.site_pages import (
    REPO_URL,
    Site,
    link_target,
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
