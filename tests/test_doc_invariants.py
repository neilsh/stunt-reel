"""Automated validation that every documentation anchor resolves.

Two directions, driven by the registry in ``stunt_reel.doc_anchors``:

* every registered anchor has a heading with the registered text in its home file;
* every anchor cited anywhere in code, tests or documents is registered.
"""

import os
import re
from collections.abc import Iterator
from pathlib import Path

from stunt_reel.doc_anchors import ANCHORS, BY_ID, CITATION_REGEX

REPO_ROOT = Path(__file__).parent.parent

CITATION_ROOTS = ("crates", "python", "tests", "docs", "research")
CITATION_TOP_LEVEL = ("AGENTS.md", "README.md", "GLOSSARY.md")
CITATION_SUFFIXES = frozenset({".rs", ".py", ".md", ".ksy", ".toml"})
SKIPPED_DIRS = frozenset({".cache", "target", ".venv", "__pycache__", "node_modules", "build"})


def _walk(root: Path, skipped: frozenset[str]) -> Iterator[Path]:
    """Files under *root*, never descending into a skipped directory.

    Pruning while walking matters: ``rglob`` would first read every nested
    worktree and every junction into the shared data root, then drop them.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skipped]
        for name in filenames:
            yield Path(dirpath) / name


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
            for path in _walk(REPO_ROOT / root, SKIPPED_DIRS)
            if path.suffix in CITATION_SUFFIXES
        )
    return files


def test_core_docs_exist() -> None:
    """Verify that all core documentation files exist."""
    for name in ("SPEC.md", "ARCHITECTURE.md", "process/TEAM_SHEET.md", "../research/README.md"):
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


LINK_SKIPPED_DIRS = SKIPPED_DIRS | {".git", "corpus", "target_bin", "worktrees"}
MARKDOWN_LINK_REGEX = re.compile(r"!?\[[^\]\n]*\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
HTML_ID_REGEX = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")
CODE_DOC_PATH_REGEX = re.compile(r"(?<![\w./-])((?:research|docs)/[\w./-]+?\.md)\b")
CODE_SUFFIXES = frozenset({".rs", ".py", ".wgsl", ".toml"})


def _repo_files(suffixes: frozenset[str]) -> list[Path]:
    return [path for path in _walk(REPO_ROOT, LINK_SKIPPED_DIRS) if path.suffix in suffixes]


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    """Every fragment a link may target in a Markdown file, duplicates numbered like GitHub."""
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    text = path.read_text(encoding="utf-8")
    for heading in _heading_texts(path):
        slug = _slug(heading)
        count = seen.get(slug, 0)
        anchors.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    anchors.update(HTML_ID_REGEX.findall(text))
    return anchors


def _prose(path: Path) -> str:
    """Markdown text with fenced blocks and inline code removed."""
    lines: list[str] = []
    in_code_block = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
        elif not in_code_block:
            lines.append(re.sub(r"`[^`\n]*`", "", line))
    return "\n".join(lines)


def test_markdown_links_resolve() -> None:
    """Every relative Markdown link points at an existing file and, for .md targets, heading."""
    anchors_by_file: dict[Path, set[str]] = {}
    broken: list[str] = []
    for path in _repo_files(frozenset({".md"})):
        for match in MARKDOWN_LINK_REGEX.finditer(_prose(path)):
            target = match.group(1)
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path.resolve()
            rel = path.relative_to(REPO_ROOT).as_posix()
            if not resolved.exists():
                broken.append(f"{rel}: {target} (no such file)")
            elif fragment and resolved.suffix == ".md":
                anchors = anchors_by_file.setdefault(resolved, _anchors(resolved))
                if fragment not in anchors:
                    broken.append(f"{rel}: {target} (no such heading)")
    assert not broken, "Broken Markdown links:\n" + "\n".join(sorted(broken))


def test_code_cited_docs_exist() -> None:
    """Every docs/ or research/ Markdown path named in code exists."""
    missing: list[str] = []
    for path in _repo_files(CODE_SUFFIXES):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CODE_DOC_PATH_REGEX.finditer(text):
            if not (REPO_ROOT / match.group(1)).exists():
                missing.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {match.group(1)}")
    assert not missing, "Code cites missing documents:\n" + "\n".join(sorted(set(missing)))
