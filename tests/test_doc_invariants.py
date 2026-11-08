"""Automated validation that every documentation anchor resolves.

Two directions, driven by the registry in ``stunt_reel.doc_anchors``:

* every registered anchor has a heading with the registered text in its home file;
* every anchor cited anywhere in code, tests or documents is registered.
"""

import bisect
import functools
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from stunt_reel.doc_anchors import ANCHORS, BY_ID, CITATION_REGEX
from stunt_reel.markdown_links import (
    LINK_DEFINITION_REGEX,
    MARKDOWN_LINK_REGEX,
    URL_SCHEME_REGEX,
    prose,
)
from stunt_reel.work_items import is_dated

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.docs

REPO_ROOT = Path(__file__).parent.parent

CITATION_ROOTS = ("crates", "python", "tests", "docs", "research")
CITATION_TOP_LEVEL = ("AGENTS.md", "README.md", "GLOSSARY.md")
CITATION_SUFFIXES = frozenset({".rs", ".py", ".md", ".ksy", ".toml"})
SKIPPED_DIRS = frozenset(
    {".cache", ".pytest_cache", "target", ".venv", "__pycache__", "node_modules", "build"}
)


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
    """Heading texts of a Markdown file outside fenced code, without the leading ``#`` marks."""
    text = path.read_text(encoding="utf-8")
    return {
        line.lstrip("#").strip()
        for blanked, line in zip(prose(text).splitlines(), text.splitlines(), strict=True)
        if blanked.startswith("#")
    }


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


# .superpowers is agent scratch, not docs.
LINK_SKIPPED_DIRS = SKIPPED_DIRS | {".git", "corpus", "worktrees", ".superpowers"}
HTML_ID_REGEX = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"")
HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_DOC_PATH_REGEX = re.compile(r"(?<![\w./-])((?:research|docs|work)/[\w./-]+?\.md)\b")
CODE_SUFFIXES = frozenset({".rs", ".py", ".wgsl", ".toml"})

#: Work folders. Only its month directories (``work/<YYYY-MM>/``) hold dated records, frozen once
#: their work lands and not a source of truth; the README beside them is evergreen.
WORK_DIR = REPO_ROOT / "work"
#: Repo-relative path prefixes whose own links ``test_markdown_links_resolve`` leaves unchecked
#: while a move is half done; the rule on links into dated records still reads them.
LINK_SOURCES_SKIPPED: tuple[str, ...] = ()
#: A link from an evergreen file to a dated record is allowed after a provenance marker on its
#: line (``_Source:`` or a legacy ``_Found <date>``, italic with ``_`` or ``*``, at the line's
#: start or after whitespace), or under a Ruled out heading, until the next heading of the same
#: or higher level.
PROVENANCE_REGEX = re.compile(r"(?<!\S)[_*](?:Source:|Found )")
#: A Ruled out heading's whole text: any case, after an optional section number (``5.``, ``4.1``).
#: The section number has the shape of ``_SECTION_NUMBER`` in ``python/scripts/doc_health.py``.
RULED_OUT_HEADING_REGEX = re.compile(r"\A(?:\d+(?:\.\d+)*\.?\s+)?ruled out\Z", re.IGNORECASE)
#: A dated folder's pictures, which an evergreen file may cite anywhere.
IMAGES_DIR_NAME = "images"
#: ADRs cite the spec and plan they came from freely.
ADR_PREFIX = "docs/adr/"


def _code_files(root: Path = REPO_ROOT) -> list[Path]:
    """Code files under *root* whose document citations are checked; dated records are not."""
    return [
        path
        for path in _walk(root, LINK_SKIPPED_DIRS)
        if path.suffix in CODE_SUFFIXES and not is_dated(path.relative_to(root).as_posix())
    ]


def _link_sources(root: Path, skipped: tuple[str, ...] = ()) -> list[Path]:
    """Markdown files under *root* whose links are checked, less those under a *skipped* prefix."""
    return [
        path
        for path in _walk(root, LINK_SKIPPED_DIRS)
        if path.suffix == ".md" and not path.relative_to(root).as_posix().startswith(skipped)
    ]


def _slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


@functools.cache
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


def _is_ruled_out_heading(text: str) -> bool:
    """Whether *text*, a heading without its ``#`` marks, opens a Ruled out section."""
    return RULED_OUT_HEADING_REGEX.match(text) is not None


def _links(path: Path) -> Iterator[tuple[str, bool]]:
    """(target, allowed) for each inline or reference-style link in *path*'s prose.

    Allowed means the link follows a provenance marker on its line, or sits in a ``Ruled out``
    section.
    """
    text = prose(path.read_text(encoding="utf-8"))
    line_starts: list[int] = []
    allowed_from: list[int] = []  # per line, the prose offset where allowed links begin
    offset = 0
    ruled_out_level = 0  # the open Ruled out heading's level; 0 when none is open
    for line in text.split("\n"):
        if heading := HEADING_REGEX.match(line):
            level = len(heading.group(1))
            if level <= ruled_out_level:
                ruled_out_level = 0
            if not ruled_out_level and _is_ruled_out_heading(heading.group(2)):
                ruled_out_level = level
        marker = PROVENANCE_REGEX.search(line)
        line_starts.append(offset)
        if ruled_out_level:
            allowed_from.append(offset)
        elif marker:
            allowed_from.append(offset + marker.start())
        else:
            allowed_from.append(len(text) + 1)
        offset += len(line) + 1
    for regex in (MARKDOWN_LINK_REGEX, LINK_DEFINITION_REGEX):
        for match in regex.finditer(text):
            index = bisect.bisect_right(line_starts, match.start()) - 1
            yield match.group(1), match.start() >= allowed_from[index]


def _is_dated(path: Path, work: Path) -> bool:
    """Whether *path* is a dated record: in a month directory of *work*, the ``work/`` directory
    of a checkout. Both are resolved."""
    root = work.parent
    return path.is_relative_to(root) and is_dated(path.relative_to(root).as_posix())


def _is_dated_image(path: Path, work: Path) -> bool:
    """Whether *path* is in a dated folder's pictures, ``<YYYY-MM>/<folder>/images/``, under *work*."""
    return _is_dated(path, work) and path.relative_to(work).parts[2:3] == (IMAGES_DIR_NAME,)


def _check_link(source: Path, target: str, work_dir: Path) -> str | None:
    """Why *target*, linked from *source*, does not resolve; None when it does or is a URL.

    A link from a dated record under *work_dir* to an evergreen file is checked for the file
    only, so renaming a heading in a note never breaks a frozen record; every other ``.md``
    fragment must name a heading.
    """
    if URL_SCHEME_REGEX.match(target):
        return None
    file_part, _, fragment = target.partition("#")
    resolved = (source.parent / file_part).resolve() if file_part else source.resolve()
    if not resolved.exists():
        return "no such file"
    if not fragment or resolved.suffix != ".md":
        return None
    work = work_dir.resolve()
    if _is_dated(source.resolve(), work) and not _is_dated(resolved, work):
        return None
    return None if fragment in _anchors(resolved) else "no such heading"


def _work_links(root: Path = REPO_ROOT) -> set[tuple[str, str, bool]]:
    """(source, target, allowed) for every link from an evergreen Markdown file to a dated record.

    Evergreen is every Markdown file under *root* that is not a dated record, including one
    ``LINK_SOURCES_SKIPPED`` names; paths are relative to *root*.
    Allowed means a provenance span, a ``Ruled out`` section, an ADR, or a picture in a dated
    folder's ``images/``.
    """
    work = (root / WORK_DIR.name).resolve()
    found: set[tuple[str, str, bool]] = set()
    for path in _link_sources(root):
        if _is_dated(path.resolve(), work):
            continue
        source = path.relative_to(root).as_posix()
        for target, allowed in _links(path):
            file_part = target.partition("#")[0]
            if not file_part or URL_SCHEME_REGEX.match(file_part):
                continue
            resolved = (path.parent / file_part).resolve()
            if _is_dated(resolved, work):
                relative = resolved.relative_to(root.resolve()).as_posix()
                exempt = source.startswith(ADR_PREFIX) or _is_dated_image(resolved, work)
                found.add((source, relative, allowed or exempt))
    return found


def _heading_citations(text: str) -> list[str]:
    """Each document path in *text* followed by a ``#heading``, with the fragment."""
    citations: list[str] = []
    for match in CODE_DOC_PATH_REGEX.finditer(text):
        if fragment := re.match(r"#[\w-]*", text[match.end() :]):
            citations.append(match.group(1) + fragment.group())
    return citations


def test_markdown_links_resolve() -> None:
    """Every relative Markdown link points at an existing file and, for .md targets, heading.

    A link from a dated record (``work/<YYYY-MM>/``) to an evergreen file is checked for the file
    only (``_check_link``). Files under ``LINK_SOURCES_SKIPPED`` are not sources here alone.
    """
    broken = [
        f"{path.relative_to(REPO_ROOT).as_posix()}: {target} ({problem})"
        for path in _link_sources(REPO_ROOT, LINK_SOURCES_SKIPPED)
        for target, _ in _links(path)
        if (problem := _check_link(path, target, WORK_DIR))
    ]
    assert not broken, "Broken Markdown links:\n" + "\n".join(sorted(broken))


def test_code_cited_docs_exist() -> None:
    """Every docs/, research/ or work/ Markdown path named in code outside dated records exists."""
    missing: list[str] = []
    for path in _code_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CODE_DOC_PATH_REGEX.finditer(text):
            if not (REPO_ROOT / match.group(1)).exists():
                missing.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {match.group(1)}")
    assert not missing, "Code cites missing documents:\n" + "\n".join(sorted(set(missing)))


# AGENTS.md: process documents are never cited for a fact about the system. These are the
# sources of truth that must not lean on one.
PROCESS_DIR = REPO_ROOT / "docs" / "process"
PROCESS_FREE = ("research", "docs/SPEC.md", "docs/ARCHITECTURE.md")

# Links that point at where work was tracked or planned rather than citing a fact through it.
# This list may only shrink: a new link fails, and so does an entry that no longer exists.
PROCESS_POINTERS = frozenset(
    {
        ("docs/ARCHITECTURE.md", "docs/process/plans/architecture-deepening/README.md"),
        ("docs/SPEC.md", "docs/process/TEAM_SHEET.md"),
        ("research/makeone-exe/driving.md", "docs/process/plans/make-all-2026-10-29.md"),
        ("research/parity/batch.md", "docs/process/plans/batch-parity-2026-10-30.md"),
        ("research/parity/method.md", "docs/process/TEAM_SHEET.md"),
        (
            "research/playone-exe/dosbox-x-legacy.md",
            "docs/process/plans/dosbox-automation-switch-2026-10-30.md",
        ),
    }
)


def _process_links() -> set[tuple[str, str]]:
    """(source, target) for every Markdown link from a source of truth into docs/process/."""
    sources: list[Path] = []
    for entry in PROCESS_FREE:
        path = REPO_ROOT / entry
        if path.is_file():
            sources.append(path)
        else:
            sources.extend(_walk(path, LINK_SKIPPED_DIRS))
    found: set[tuple[str, str]] = set()
    for path in sources:
        if path.suffix != ".md":
            continue
        text = prose(path.read_text(encoding="utf-8"))
        targets = [m.group(1) for m in MARKDOWN_LINK_REGEX.finditer(text)]
        targets += [m.group(1) for m in LINK_DEFINITION_REGEX.finditer(text)]
        for target in targets:
            file_part = target.partition("#")[0]
            if not file_part or re.match(r"[a-z][a-z0-9+.-]*:", file_part):
                continue
            resolved = (path.parent / file_part).resolve()
            if resolved.is_relative_to(PROCESS_DIR.resolve()):
                found.add(
                    (
                        path.relative_to(REPO_ROOT).as_posix(),
                        resolved.relative_to(REPO_ROOT.resolve()).as_posix(),
                    )
                )
    return found


def test_sources_of_truth_do_not_link_into_process_docs() -> None:
    """research/, SPEC.md and ARCHITECTURE.md link into docs/process/ only through the pointers."""
    links = _process_links()
    new = sorted(links - PROCESS_POINTERS)
    assert not new, (
        "A source of truth links into docs/process/ (AGENTS.md: never cite a process document "
        "for a fact about the system); move the fact into the note:\n"
        + "\n".join(f"{source} -> {target}" for source, target in new)
    )
    stale = sorted(PROCESS_POINTERS - links)
    assert not stale, "PROCESS_POINTERS lists links that are gone; drop them:\n" + "\n".join(
        f"{source} -> {target}" for source, target in stale
    )


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


#: The work folder the link fixtures point into. Fixture paths are built from parts so this file
#: names no document path of its own for ``test_code_cited_docs_exist`` to look up.
FIXTURE_FOLDER = "work/2026-11/x"


def test_provenance_and_ruled_out_links_into_work_are_allowed(tmp_path: Path) -> None:
    """A provenance line or a Ruled out section may link work/; a fenced heading opens no section."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "A fact.\n\n"
        "_Source: [e](../work/2026-11/x/journal.md#e)._\n"
        "*Source: [s](../work/2026-11/x/star.md).*\n\n"
        "```markdown\n## Ruled out\n```\n\n"
        "After the sample, [f](../work/2026-11/x/fenced.md).\n\n"
        "## Ruled out\n\n"
        "- Tried r; rejected ([r](../work/2026-11/x/ruled.md#r)).\n\n"
        "### Detail\n\n"
        "- Still ruled out: [d](../work/2026-11/x/deeper.md).\n\n"
        "[def]: ../work/2026-11/x/definition.md\n\n"
        "## Open questions\n\n"
        "- [q](../work/2026-11/x/after.md)\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/journal.md", True),
        (source, f"{FIXTURE_FOLDER}/star.md", True),
        (source, f"{FIXTURE_FOLDER}/fenced.md", False),
        (source, f"{FIXTURE_FOLDER}/ruled.md", True),
        (source, f"{FIXTURE_FOLDER}/deeper.md", True),
        (source, f"{FIXTURE_FOLDER}/definition.md", True),
        (source, f"{FIXTURE_FOLDER}/after.md", False),
    }


def test_other_links_from_evergreen_files_into_work_fail(tmp_path: Path) -> None:
    """A body link or reference-style definition into work/ from an evergreen file is not allowed."""
    _write(tmp_path / "README.md", "# R\n\nSee [the plan](./work/2026-11/x/plan.md).\n")
    guide = _write(
        tmp_path / "docs" / "guide.md",
        "# G\n\n**Source:** [b](../work/2026-11/x/bold.md)\n\n[p]: ../work/2026-11/x/spec.md#goal\n",
    )
    _write(tmp_path / "work" / "2026-11" / "x" / "plan.md", "# P\n\n[s](spec.md)\n")
    source = guide.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        ("README.md", f"{FIXTURE_FOLDER}/plan.md", False),
        (source, f"{FIXTURE_FOLDER}/bold.md", False),
        (source, f"{FIXTURE_FOLDER}/spec.md", False),
    }


def test_adrs_may_cite_work_freely(tmp_path: Path) -> None:
    """An ADR cites the spec and plan it came from anywhere in its text."""
    adr = _write(
        tmp_path / "docs" / "adr" / "0001-x.md",
        "# 1. X\n\nFrom [the spec](../../work/2026-11/x/spec.md).\n",
    )
    assert _work_links(tmp_path) == {
        (adr.relative_to(tmp_path).as_posix(), f"{FIXTURE_FOLDER}/spec.md", True)
    }


def test_legacy_found_lines_may_cite_work(tmp_path: Path) -> None:
    """A ``_Found <date>`` line is provenance, as ``_Source:`` is; a body paragraph is not."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "_Found 2026-11-02; see the [parity log](../work/2026-11/x/log.md)._\n"
        "*Found 2026-11-03; see the [parity log](../work/2026-11/x/star.md).*\n\n"
        "The rows are in the [parity log](../work/2026-11/x/body.md).\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/log.md", True),
        (source, f"{FIXTURE_FOLDER}/star.md", True),
        (source, f"{FIXTURE_FOLDER}/body.md", False),
    }


def test_a_provenance_span_runs_from_its_marker_to_the_line_end(tmp_path: Path) -> None:
    """A paragraph ending in a ``_Found`` sentence cites from there on; earlier links are body."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "A fact, measured with [the probe](../work/2026-11/x/body.md). "
        "_Found 2026-11-02; see the [parity log](../work/2026-11/x/log.md)._\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/body.md", False),
        (source, f"{FIXTURE_FOLDER}/log.md", True),
    }


def test_a_source_link_with_underscores_in_its_path_is_provenance(tmp_path: Path) -> None:
    """Underscores in a work folder's name do not end the span."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n_Source: [e](../work/2026-11/307_docs-streamline/journal.md#e)._\n",
    )
    folder = "work/2026-11/307_docs-streamline"
    assert _work_links(tmp_path) == {
        (note.relative_to(tmp_path).as_posix(), f"{folder}/journal.md", True)
    }


def test_a_marker_inside_a_word_opens_no_span(tmp_path: Path) -> None:
    """A marker counts at the start of a line or after whitespace, not inside a word."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\nThe x_Found flag is set; see [the run](../work/2026-11/x/mid.md).\n",
    )
    assert _work_links(tmp_path) == {
        (note.relative_to(tmp_path).as_posix(), f"{FIXTURE_FOLDER}/mid.md", False)
    }


def test_image_citations_into_work_are_allowed_anywhere(tmp_path: Path) -> None:
    """A link or embed into a work folder's images/ is allowed anywhere; other dated files are not."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "![shot](../work/2026-11/x/images/embed.png)\n\n"
        "See [the shot](../work/2026-11/x/images/link.png).\n\n"
        "![not an image set](../work/2026-11/x/outside.png)\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/images/embed.png", True),
        (source, f"{FIXTURE_FOLDER}/images/link.png", True),
        (source, f"{FIXTURE_FOLDER}/outside.png", False),
    }


@pytest.mark.parametrize(
    ("heading", "opens"),
    [
        ("Ruled out", True),
        ("Ruled Out", True),
        ("RULED OUT", True),
        ("5. Ruled Out", True),
        ("4.1 Ruled out", True),
        ("4.1. Ruled out", True),
        ("Ruled out hypotheses", False),
        ("Not ruled out", False),
        ("Ruled out: framing", False),
        ("5.Ruled out", False),
        ("v2 Ruled out", False),
    ],
)
def test_ruled_out_heading_text(heading: str, opens: bool) -> None:
    """Ruled out in any case, after an optional section number; nothing else around it."""
    assert _is_ruled_out_heading(heading) is opens


def test_a_numbered_ruled_out_heading_opens_a_section(tmp_path: Path) -> None:
    """A note's numbered ``4.1 Ruled out`` allows work/ links until the next heading at its level."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "## 4. Open Questions & Analysis Backlog\n\n"
        "### 4.1 Ruled out\n\n"
        "- [ruled](../work/2026-11/x/ruled.md)\n\n"
        "### 4.2 Open questions\n\n"
        "- [after](../work/2026-11/x/after.md)\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/ruled.md", True),
        (source, f"{FIXTURE_FOLDER}/after.md", False),
    }


def test_a_nested_ruled_out_heading_keeps_the_outer_section_open(tmp_path: Path) -> None:
    """A Ruled out heading inside an open section opens nothing, so its sibling does not close it."""
    note = _write(
        tmp_path / "research" / "n.md",
        "# Note\n\n"
        "## Ruled out\n\n"
        "### Ruled out\n\n"
        "### Other\n\n"
        "- [still](../work/2026-11/x/still.md)\n\n"
        "## Open questions\n\n"
        "- [after](../work/2026-11/x/after.md)\n",
    )
    source = note.relative_to(tmp_path).as_posix()
    assert _work_links(tmp_path) == {
        (source, f"{FIXTURE_FOLDER}/still.md", True),
        (source, f"{FIXTURE_FOLDER}/after.md", False),
    }


def test_links_from_work_check_the_file_not_the_heading(tmp_path: Path) -> None:
    """A dated record survives a heading rename in the note it links; between records, full check."""
    work = tmp_path / "work"
    _write(tmp_path / "research" / "n.md", "# N\n")
    _write(work / "2026-11" / "x" / "other.md", "# Other\n")
    journal = _write(work / "2026-11" / "x" / "journal.md", "# J\n")
    assert _check_link(journal, "../../../research/n.md#gone", work) is None
    assert _check_link(journal, "../../../research/missing.md", work) == "no such file"
    assert _check_link(journal, "other.md#other", work) is None
    assert _check_link(journal, "other.md#gone", work) == "no such heading"


def test_links_into_work_check_the_heading(tmp_path: Path) -> None:
    """Frozen headings never change, so a fragment into work/ must name one."""
    work = tmp_path / "work"
    _write(work / "2026-11" / "x" / "journal.md", "# J\n\n## e\n")
    note = _write(tmp_path / "research" / "n.md", "# N\n")
    assert _check_link(note, "../work/2026-11/x/journal.md#e", work) is None
    assert _check_link(note, "../work/2026-11/x/journal.md#missing", work) == "no such heading"


def test_work_readme_is_evergreen(tmp_path: Path) -> None:
    """Only work/<YYYY-MM>/ is dated: work/'s README links and is linked like any evergreen file."""
    work = tmp_path / "work"
    journal = _write(work / "2026-11" / "x" / "journal.md", "# J\n")
    readme = _write(
        work / "README.md",
        "# Work\n\n## Layout\n\nSee [j](./2026-11/x/journal.md) and [n](../research/n.md#gone).\n",
    )
    note = _write(
        tmp_path / "research" / "n.md",
        "# N\n\nRead [the layout](../work/README.md#layout), then [j](../work/2026-11/x/journal.md).\n",
    )
    assert _work_links(tmp_path) == {
        (note.relative_to(tmp_path).as_posix(), f"{FIXTURE_FOLDER}/journal.md", False),
        (readme.relative_to(tmp_path).as_posix(), f"{FIXTURE_FOLDER}/journal.md", False),
    }
    assert _check_link(note, "../work/README.md#layout", work) is None
    assert _check_link(note, "../work/README.md#gone", work) == "no such heading"
    assert _check_link(readme, "../research/n.md#gone", work) == "no such heading"
    assert _check_link(journal, "../../README.md#gone", work) is None


def test_the_work_link_rule_ignores_the_move_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A half-done move pauses the resolve check only; work/'s README still may not cite a record."""
    monkeypatch.setattr(sys.modules[__name__], "LINK_SOURCES_SKIPPED", ("work/",))
    _write(tmp_path / "work" / "2026-11" / "x" / "journal.md", "# J\n")
    readme = _write(tmp_path / "work" / "README.md", "# Work\n\nSee [j](./2026-11/x/journal.md).\n")
    assert _work_links(tmp_path) == {
        (readme.relative_to(tmp_path).as_posix(), f"{FIXTURE_FOLDER}/journal.md", False)
    }
    assert readme not in _link_sources(tmp_path, LINK_SOURCES_SKIPPED)


def test_code_citation_walks_skip_dated_records(tmp_path: Path) -> None:
    """A dated record's script or moves file names paths as they were then, so it is not checked."""
    for relative in (
        "python/a.py",
        "work/tool.py",
        f"{FIXTURE_FOLDER}/plan_moves.py",
        f"{FIXTURE_FOLDER}/moves.toml",
    ):
        _write(tmp_path / relative, "")
    assert sorted(path.relative_to(tmp_path).as_posix() for path in _code_files(tmp_path)) == [
        "python/a.py",
        "work/tool.py",
    ]


#: Links from evergreen files to dated records that point at where work was tracked rather than cite a
#: fact through it. This list may only shrink: a new link fails, and so does an entry that no
#: longer exists.
WORK_POINTERS: frozenset[tuple[str, str]] = frozenset()


def test_evergreen_files_link_into_work_only_where_allowed() -> None:
    """Outside ADRs, an evergreen link to a dated record sits on a provenance line or under Ruled out."""
    disallowed = {(source, target) for source, target, allowed in _work_links() if not allowed}
    new = sorted(disallowed - WORK_POINTERS)
    assert not new, (
        "An evergreen file links to a dated record under work/ outside a provenance line or a "
        "Ruled out section; "
        "state the fact in the evergreen file and cite the record from its _Source: line:\n"
        + "\n".join(f"{source} -> {target}" for source, target in new)
    )
    stale = sorted(WORK_POINTERS - disallowed)
    assert not stale, "WORK_POINTERS lists links that are gone; drop them:\n" + "\n".join(
        f"{source} -> {target}" for source, target in stale
    )


def test_a_code_citation_with_a_heading_is_found() -> None:
    """The heading check sees a fragment after a cited path, and only there."""
    # Built at run time so this file does not itself cite a heading.
    cited = "docs/SPEC.md"
    assert _heading_citations(f"// see {cited}#goals, then {cited}.") == [f"{cited}#goals"]


def test_code_citations_name_no_heading() -> None:
    """Code cites a document by path or anchor token, never by heading, so distilling breaks none."""
    found = [
        f"{path.relative_to(REPO_ROOT).as_posix()}: {citation}"
        for path in _code_files()
        for citation in _heading_citations(path.read_text(encoding="utf-8", errors="replace"))
    ]
    assert not found, (
        "Code cites a document by heading; cite the path, or a registered anchor token:\n"
        + "\n".join(sorted(set(found)))
    )


def test_no_docs_superpowers_directory() -> None:
    """A skill's default spec location is unused: specs and plans go in the work item's folder."""
    assert not (REPO_ROOT / "docs" / "superpowers").exists(), (
        "docs/superpowers/ exists; move its files into the work item's folder under work/"
    )


def test_reference_style_definitions_are_read_as_links() -> None:
    """``[p]: ../docs/process/X.md`` links as surely as ``[p](../docs/process/X.md)``."""
    text = "See [the plan][p].\n\n[p]: ../../docs/process/TEAM_SHEET.md#tickets\n"
    assert [m.group(1) for m in LINK_DEFINITION_REGEX.finditer(text)] == [
        "../../docs/process/TEAM_SHEET.md#tickets"
    ]
    assert not MARKDOWN_LINK_REGEX.search("[p]: ../../docs/process/TEAM_SHEET.md")


def test_the_walk_skips_pytests_own_temporary_files(tmp_path: Path) -> None:
    """Another xdist worker's basetemp under .pytest_cache vanishes mid-walk (a gate flake)."""
    (tmp_path / ".pytest_cache" / "basetemp-1" / "case0").mkdir(parents=True)
    (tmp_path / ".pytest_cache" / "basetemp-1" / "case0" / "notes.md").write_text("x")
    (tmp_path / "kept.md").write_text("x")
    assert [p.name for p in _walk(tmp_path, SKIPPED_DIRS)] == ["kept.md"]


AGENTS_MD_MAX_BYTES = 8192
SKILL_MAX_WORDS = 500


def test_adr_numbers_are_unique() -> None:
    """Two ADRs never share a number; a branch that collides with main takes the next free one."""
    by_number: dict[str, list[str]] = {}
    for path in sorted((REPO_ROOT / "docs" / "adr").glob("[0-9][0-9][0-9][0-9]-*.md")):
        by_number.setdefault(path.name[:4], []).append(path.name)
    clashes = {number: names for number, names in by_number.items() if len(names) > 1}
    assert not clashes, f"ADR numbers used twice; renumber the later one: {clashes}"


def test_agents_md_fits_its_budget() -> None:
    """AGENTS.md loads on every turn, so it stays within 8 KiB; move detail to the doc it routes to."""
    size = len((REPO_ROOT / "AGENTS.md").read_bytes())
    assert size <= AGENTS_MD_MAX_BYTES, (
        f"AGENTS.md is {size} bytes, over {AGENTS_MD_MAX_BYTES}; move detail to the document "
        "that owns it and leave a pointer"
    )


def test_skills_fit_their_budget() -> None:
    """A SKILL.md stays under 500 words (``wc -w``); longer procedures go in files beside it."""
    over = {
        path.relative_to(REPO_ROOT).as_posix(): words
        for path in sorted((REPO_ROOT / ".agents" / "skills").glob("*/SKILL.md"))
        if (words := len(path.read_text(encoding="utf-8").split())) >= SKILL_MAX_WORDS
    }
    assert not over, (
        f"Skills at or over {SKILL_MAX_WORDS} words; move detail into a file beside SKILL.md "
        f"and link it: {over}"
    )
