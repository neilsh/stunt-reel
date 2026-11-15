"""`mise run site-prep`: the research site's content is written from site/published.toml."""

from __future__ import annotations

import importlib.util
import json
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
    _write(tmp_path / "GLOSSARY.md", "# Glossary\n\nSee [sod](research/formats/sod.md).\n")
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
