"""Which files under `research/` are notes, and each note's one-line `summary:`.

`research/MAP.md` and `mise run doc-health` both read these, so the map and the report agree
on which notes lack a summary.
"""

from __future__ import annotations

from pathlib import Path

from stunt_reel.frontmatter import FrontmatterError, read_frontmatter

__all__ = ["MAP_NAME", "note_paths", "note_summary"]

#: The generated map at the top of the research root, which is not a note.
MAP_NAME = "MAP.md"


def note_paths(research_root: Path) -> list[Path]:
    """Every ``.md`` file under *research_root* but a ``README.md`` and the top-level ``MAP.md``.

    Paths are relative to *research_root* and sorted by their ``/``-separated form. Matching and
    sorting are case-sensitive on every OS, so the map is the same bytes on each.
    """
    notes = [
        path.relative_to(research_root)
        for path in research_root.rglob("*.md", case_sensitive=True)
        if path.is_file()
    ]
    return sorted(
        (note for note in notes if note.name != "README.md" and note.as_posix() != MAP_NAME),
        key=Path.as_posix,
    )


def note_summary(path: Path) -> str | None:
    """The ``summary:`` in the frontmatter of the note at *path*.

    None when it is missing, empty or not a string, or when the file is not UTF-8 or its
    frontmatter does not parse.
    """
    try:
        fields, _body = read_frontmatter(path.read_text(encoding="utf-8"))
    except FrontmatterError, UnicodeDecodeError:
        return None
    summary = fields.get("summary")
    return summary if isinstance(summary, str) and summary else None
