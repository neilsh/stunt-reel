"""`mise run site-prep`: the research site's content is written from site/published.toml."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.site_pages import load_sections, prepare

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
PUBLISHED = """\
[[section]]
source = "research"
dest = "research"
label = "Research notes"

[[section]]
source = "GLOSSARY.md"
dest = "glossary.md"
label = "Glossary"
title = "Glossary"
"""


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("site_prep", SCRIPTS / "site_prep.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


site_prep = _load()


def _write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode() if isinstance(text, str) else text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _write(tmp_path / "site/published.toml", PUBLISHED)
    _write(tmp_path / "site/index.md", '---\ntitle: "Home"\n---\n')
    _write(tmp_path / "site/reading.md", '---\ntitle: "Reading"\n---\n')
    _write(tmp_path / "GLOSSARY.md", "# Stunt Reel\n\nSee [sod](research/formats/sod.md).\n")
    _write(tmp_path / "research/formats/INDEX.md", "# Formats\n\n[sod](sod.md)\n")
    _write(
        tmp_path / "research/formats/sod.md",
        "# Sod\n\n![a](../parity/error-examples/a.png)\n\n[g](../../GLOSSARY.md)\n",
    )
    _write(tmp_path / "research/parity/error-examples/a.png", b"\x89PNG")
    return tmp_path


def test_load_sections_rejects_bad_paths() -> None:
    bad = [
        '[[section]]\nsource = "a"\ndest = "a"\n',
        '[[section]]\nsource = "/a"\ndest = "a"\nlabel = "A"\n',
        '[[section]]\nsource = "C:/a"\ndest = "a"\nlabel = "A"\n',
        '[[section]]\nsource = "a/../b"\ndest = "a"\nlabel = "A"\n',
        '[[section]]\nsource = "a"\ndest = "../a"\nlabel = "A"\n',
        '[[section]]\nsource = "research\\\\formats"\ndest = "a"\nlabel = "A"\n',
        '[[section]]\nsource = "a"\ndest = "a\\\\b"\nlabel = "A"\n',
    ]
    for text in bad:
        with pytest.raises(ValueError, match="section 1"):
            load_sections(text)


def test_prepare_writes_pages_media_and_sidebar(repo: Path) -> None:
    pages, images = prepare(repo, repo / "site")
    assert (pages, images) == (5, 1)
    docs = repo / "site/src/content/docs"
    assert (docs / "research/formats/sod.md").is_file()
    names = {p.name for p in (docs / "research/formats").iterdir()}
    assert "index.md" in names  # INDEX.md, lower-cased
    assert (docs / "glossary.md").is_file()
    assert (docs / "index.md").is_file()
    assert (repo / "site/public/media/research/parity/error-examples/a.png").is_file()
    sidebar = json.loads((repo / "site/src/generated/sidebar.json").read_text())
    assert sidebar == [
        {"slug": "reading"},
        {"label": "Research notes", "items": [{"autogenerate": {"directory": "research"}}]},
        {"label": "Glossary", "slug": "glossary"},
    ]


def test_prepare_removes_stale_output(repo: Path) -> None:
    prepare(repo, repo / "site")
    (repo / "research/formats/sod.md").unlink()
    prepare(repo, repo / "site")
    assert not (repo / "site/src/content/docs/research/formats/sod.md").exists()


def test_prepare_writes_posix_urls(repo: Path) -> None:
    prepare(repo, repo / "site")
    docs = repo / "site/src/content/docs"
    sod = (docs / "research/formats/sod.md").read_text(encoding="utf-8")
    assert "(/stunt-reel/media/research/parity/error-examples/a.png)" in sod
    assert "(/stunt-reel/glossary/)" in sod
    for page in docs.rglob("*.md"):
        assert "\\" not in page.read_text(encoding="utf-8")
        assert b"\r" not in page.read_bytes()


def test_cli_exits_1_naming_the_bad_note(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(repo / "research" / "formats" / "bad.md", "no heading\n")
    assert site_prep.main(["--root", str(repo)]) == 1
    assert "bad.md" in capsys.readouterr().err


def test_cli_reports_the_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert site_prep.main(["--root", str(repo)]) == 0
    assert capsys.readouterr().out == "wrote 5 pages and 1 images to site/\n"


def test_load_sections_names_the_file_for_bad_toml() -> None:
    with pytest.raises(ValueError, match=r"site/published\.toml"):
        load_sections("[[section")


def test_prepare_titles_a_file_section_by_its_title_key(repo: Path) -> None:
    prepare(repo, repo / "site")
    glossary = (repo / "site/src/content/docs/glossary.md").read_text(encoding="utf-8")
    assert glossary.startswith('---\ntitle: "Glossary"\n')


def test_prepare_refuses_two_sources_for_one_path_by_case(repo: Path) -> None:
    _write(repo / "NOTES.md", "# N\n")
    extra = '\n[[section]]\nsource = "NOTES.md"\ndest = "Glossary.md"\nlabel = "N"\n'
    _write(repo / "site/published.toml", PUBLISHED + extra)
    with pytest.raises(ValueError, match=r"GLOSSARY\.md and NOTES\.md both write Glossary\.md"):
        prepare(repo, repo / "site")


def test_prepare_refuses_a_section_over_a_hand_written_page(repo: Path) -> None:
    _write(repo / "NOTES.md", "# N\n")
    published = PUBLISHED + '\n[[section]]\nsource = "NOTES.md"\ndest = "reading.md"\nlabel = "N"\n'
    _write(repo / "site/published.toml", published)
    with pytest.raises(ValueError, match=r"NOTES\.md and site/reading\.md both write reading\.md"):
        prepare(repo, repo / "site")


def test_cli_names_a_missing_published_file(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "site/reading.md").unlink()
    assert site_prep.main(["--root", str(repo)]) == 1
    assert "reading.md" in capsys.readouterr().err


GROUPED = (
    PUBLISHED
    + """
[[section]]
source = "docs/SPEC.md"
dest = "docs/spec.md"
label = "Spec"
group = "Project docs"

[[section]]
source = "NOTES.md"
dest = "notes.md"
label = "Notes"

[[section]]
source = "docs/adr"
dest = "docs/adr"
label = "Decisions"
group = "Project docs"
"""
)


def _grouped(repo: Path) -> None:
    _write(repo / "docs/SPEC.md", "# SPEC: Stunt Reel, a long title\n")
    _write(repo / "docs" / "adr" / "0041-dated.md", "# Dated records\n")
    _write(repo / "NOTES.md", "# N\n")
    _write(repo / "site/published.toml", GROUPED)
    prepare(repo, repo / "site")


def test_prepare_nests_a_group_at_its_first_member(repo: Path) -> None:
    _grouped(repo)
    sidebar = json.loads((repo / "site/src/generated/sidebar.json").read_text())
    assert sidebar[3:] == [
        {
            "label": "Project docs",
            "items": [
                {"label": "Spec", "slug": "docs/spec"},
                {"label": "Decisions", "items": [{"autogenerate": {"directory": "docs/adr"}}]},
            ],
        },
        {"label": "Notes", "slug": "notes"},
    ]


def test_prepare_keeps_a_file_sections_own_title(repo: Path) -> None:
    _grouped(repo)
    spec = (repo / "site/src/content/docs/docs/spec.md").read_text(encoding="utf-8")
    assert spec.startswith('---\ntitle: "SPEC: Stunt Reel, a long title"\n')


def test_prepare_refuses_a_title_on_a_folder_section(repo: Path) -> None:
    published = PUBLISHED.replace(
        'label = "Research notes"', 'label = "Research notes"\ntitle = "R"'
    )
    _write(repo / "site/published.toml", published)
    with pytest.raises(ValueError, match=r"research: title is for a file section"):
        prepare(repo, repo / "site")


def test_load_sections_rejects_a_non_string_group() -> None:
    text = '[[section]]\nsource = "a"\ndest = "a"\nlabel = "A"\ngroup = 1\n'
    with pytest.raises(ValueError, match="section 1"):
        load_sections(text)


def _workflow_paths(workflow: Path) -> list[str]:
    """The quoted `- "..."` entries under the `paths: &paths` line, read line by line."""
    found: list[str] = []
    reading = False
    for line in workflow.read_text(encoding="utf-8").splitlines():
        if line.strip() == "paths: &paths":
            reading = True
        elif reading and line.strip().startswith('- "'):
            found.append(line.strip().removeprefix('- "').removesuffix('"'))
        elif reading:
            break
    return found


def test_pages_workflow_watches_every_published_source() -> None:
    root = SCRIPTS.parent.parent
    sections = load_sections((root / "site/published.toml").read_text(encoding="utf-8"))
    paths = _workflow_paths(root / ".github/workflows/pages.yml")
    assert paths
    watched = [_github_glob(p) for p in paths]
    for section in sections:
        source = root / section.source
        files = sorted(source.rglob("*.md")) if source.is_dir() else [source]
        assert files, section.source
        for file in files:
            rel = file.relative_to(root).as_posix()
            assert any(glob.fullmatch(rel) for glob in watched), rel


def _github_glob(pattern: str) -> re.Pattern[str]:
    """*pattern* as GitHub's path filters read it: ``*`` stops at ``/``, ``**`` does not."""
    parts = re.split(r"(\*\*|\*|\?)", pattern)
    wild = {"**": ".*", "*": "[^/]*", "?": "[^/]"}
    return re.compile("".join(wild.get(part, re.escape(part)) for part in parts))


def test_prepare_publishes_guides_with_their_order(repo: Path) -> None:
    _write(repo / "site/guides/b.md", '---\ntitle: "B"\norder: 1\n---\n\nBody b.\n')
    _write(repo / "site/guides/a.md", '---\ntitle: "A"\norder: 2\n---\n\nBody a.\n')
    published = PUBLISHED.replace(
        '[[section]]\nsource = "research"',
        '[[section]]\nsource = "site/guides"\ndest = "guides"\nlabel = "Guides"\n\n'
        '[[section]]\nsource = "research"',
        1,
    )
    _write(repo / "site/published.toml", published)
    prepare(repo, repo / "site")
    docs = repo / "site/src/content/docs/guides"
    for name, order in (("b", 1), ("a", 2)):
        text = (docs / f"{name}.md").read_text(encoding="utf-8")
        assert f"\n  order: {order}\n---" in text
    sidebar = json.loads((repo / "site/src/generated/sidebar.json").read_text())
    assert sidebar[1:3] == [
        {"label": "Guides", "items": [{"autogenerate": {"directory": "guides"}}]},
        {"label": "Research notes", "items": [{"autogenerate": {"directory": "research"}}]},
    ]
