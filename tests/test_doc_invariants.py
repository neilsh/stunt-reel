"""Automated validation that every documentation anchor resolves.

Two directions, driven by the registry in ``stunt_reel.doc_anchors``:

* every registered anchor has a heading with the registered text in its home file;
* every anchor cited anywhere in code, tests or documents is registered.
"""

from pathlib import Path

from stunt_reel.doc_anchors import ANCHORS, BY_ID, CITATION_REGEX

REPO_ROOT = Path(__file__).parent.parent

CITATION_ROOTS = ("crates", "python", "tests", "docs", "research")
CITATION_TOP_LEVEL = ("AGENTS.md", "README.md", "GLOSSARY.md")
CITATION_SUFFIXES = frozenset({".rs", ".py", ".md", ".ksy", ".toml"})
SKIPPED_DIRS = frozenset({"target", ".venv", "__pycache__", "node_modules", "build"})


def _heading_texts(path: Path) -> set[str]:
    """Heading texts of a Markdown file, without the leading ``#`` marks."""
    texts: set[str] = set()
    in_code_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        elif not in_code_block and line.startswith("#"):
            texts.add(line.lstrip("#").strip())
    return texts


def _citation_files() -> list[Path]:
    files = [REPO_ROOT / name for name in CITATION_TOP_LEVEL]
    for root in CITATION_ROOTS:
        files.extend(
            path
            for path in (REPO_ROOT / root).rglob("*")
            if path.is_file()
            and path.suffix in CITATION_SUFFIXES
            and not SKIPPED_DIRS.intersection(path.relative_to(REPO_ROOT).parts)
        )
    return files


def test_core_docs_exist() -> None:
    """Verify that all core documentation files exist."""
    for name in ("SPEC.md", "ARCHITECTURE.md", "TEAM_SHEET.md", "MEMORY_MAP.md"):
        assert (REPO_ROOT / "docs" / name).exists(), f"Required documentation file missing: {name}"


def test_registry_ids_are_unique_and_cover_all_invariants() -> None:
    """Each anchor id is registered once, and [I1] through [I8] are all present."""
    ids = [anchor.id for anchor in ANCHORS]
    assert len(ids) == len(set(ids)), "Duplicate anchor id in stunt_reel.doc_anchors"
    for number in range(1, 9):
        assert f"I{number}" in BY_ID, f"System invariant [I{number}] is not registered"


def test_registered_anchors_have_their_home_heading() -> None:
    """Every registry anchor is defined by a heading with the registered text in its home file."""
    headings_by_file: dict[str, set[str]] = {}
    for anchor in ANCHORS:
        home = REPO_ROOT / anchor.file
        assert home.exists(), f"Home file for {anchor.token} is missing: {anchor.file}"
        headings = headings_by_file.setdefault(anchor.file, _heading_texts(home))
        assert anchor.heading in headings, (
            f"{anchor.token} has no heading {anchor.heading!r} in {anchor.file}"
        )


def test_cited_anchors_are_registered() -> None:
    """Every anchor token cited in crates, python, tests, docs or research is registered."""
    unresolved: list[str] = []
    for path in _citation_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CITATION_REGEX.finditer(text):
            if match.group(1) not in BY_ID:
                rel = path.relative_to(REPO_ROOT).as_posix()
                unresolved.append(f"{rel}: [{match.group(1)}]")
    assert not unresolved, "Cited anchors missing from stunt_reel.doc_anchors:\n" + "\n".join(
        sorted(set(unresolved))
    )
