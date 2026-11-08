#!/usr/bin/env python3
"""Report, worst first, the evergreen docs and work items that need gardening.

A report, never a gate. It finds:

* ``size``: an evergreen file (``research/**/*.md``, ``docs/*.md``, ``docs/agents/*.md``,
  ``docs/howto/*.md``, but not ``research/MAP.md``, ``research/formats/sod-opcode-coverage.md``
  or ``docs/adr/**``) over 20480 bytes on disk;
* ``summary``: a research note (``stunt_reel.research_notes``) without a ``summary:``;
* ``heading``: a heading in an evergreen file, outside fenced code, that contains an ISO date
  or an ordinal round ("Second round"), or whose words after any section number start with
  Update, Follow-up, Handoff or Session;
* ``stale-issue``: a work folder whose issue is open and whose last commit is 14 or more days
  old (a folder never committed is not stale);
* ``missing-outcome``: a work folder whose issue is closed and whose ``outcome`` is empty;
* ``folder``: a work folder that breaks the layout (``stunt_reel.work_items``).

A size finding weighs its byte count, every other finding 1; findings print heaviest first.
The two issue checks read status through one ``gh`` call; when ``gh`` is missing or fails they
are skipped and one note on stderr says so, as it does when ``git log`` fails.

Usage: ``mise run doc-health`` for a table, or ``mise run doc-health -- --json`` for a JSON
list of ``{path, kind, detail, weight}``; either takes ``--root DIR`` for a checkout other than
this one. Exit status: ``0`` whatever it finds, ``2`` for bad arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal
lazy from collections.abc import Iterator, Sequence

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.markdown_links import prose
from stunt_reel.research_notes import note_paths, note_summary
from stunt_reel.work_items import (
    MONTH_PATTERN,
    Runner,
    WorkFolder,
    WorkFolderError,
    issue_statuses,
    parse_folder,
    run_command,
)

type Kind = Literal["size", "summary", "heading", "stale-issue", "missing-outcome", "folder"]

SIZE_BUDGET = 20480
STALE_DAYS = 14
EVERGREEN = ("research/**/*.md", "docs/*.md", "docs/agents/*.md", "docs/howto/*.md")
EXEMPT = ("research/MAP.md", "research/formats/sod-opcode-coverage.md", "docs/adr/**")
#: Ties in weight print in this order of kind.
KINDS: tuple[Kind, ...] = (
    "size",
    "summary",
    "heading",
    "stale-issue",
    "missing-outcome",
    "folder",
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ORDINAL_ROUND = re.compile(
    r"\b(first|second|third|fourth|fifth|\d+(st|nd|rd|th))\s+round\b", re.IGNORECASE
)
_SESSION_START = re.compile(r"(update|follow-up|handoff|session)\b", re.IGNORECASE)
_SECTION_NUMBER = re.compile(r"\d+(?:\.\d+)*\.?\s+")


@dataclass(frozen=True)
class Finding:
    """One thing to garden: *path* is relative to the checkout, with ``/`` separators."""

    path: str
    kind: Kind
    detail: str
    weight: int


def collect(repo_root: Path, run: Runner, today: date) -> list[Finding]:
    """Every finding in the checkout at *repo_root*, heaviest first, with *run* for gh and git.

    Prints a note on stderr for each check it has to skip.
    """
    findings: list[Finding] = []
    for path in _evergreen(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        if (size := len(path.read_bytes())) > SIZE_BUDGET:
            detail = f"{size} bytes, over the {SIZE_BUDGET}-byte budget"
            findings.append(Finding(relative, "size", detail, size))
        text = path.read_text(encoding="utf-8", errors="replace")
        findings += [Finding(relative, "heading", line, 1) for line in _session_headings(text)]
    research = repo_root / "research"
    if research.is_dir():
        for note in note_paths(research):
            if note_summary(research / note) is None:
                relative = (research / note).relative_to(repo_root).as_posix()
                findings.append(Finding(relative, "summary", "no summary: in its frontmatter", 1))
    findings += _work_findings(repo_root, run, today)
    return sorted(findings, key=lambda f: (-f.weight, KINDS.index(f.kind)))


def main(
    argv: Sequence[str] | None = None, run: Runner = run_command, today: date | None = None
) -> int:
    """Print the report *argv* asks for, with *run* for gh and git and *today* as the date."""
    parser = argparse.ArgumentParser(
        prog="mise run doc-health --",
        description="Report oversized, unsummarised and session-style docs and stale work items.",
    )
    parser.add_argument("--json", action="store_true", help="print a JSON list of findings")
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="the checkout (default: this one)"
    )
    args = parser.parse_args(argv)
    root: Path = args.root
    if not root.is_dir():
        parser.error(f"{root} is not a directory")
    findings = collect(root, run, today or datetime.now().astimezone().date())
    if args.json:
        print(json.dumps([asdict(finding) for finding in findings], indent=2))
    elif not findings:
        print("doc-health: nothing to report")
    else:
        kinds = max(len(finding.kind) for finding in findings)
        paths = max(len(finding.path) for finding in findings)
        for finding in findings:
            print(f"{finding.kind.ljust(kinds)}  {finding.path.ljust(paths)}  {finding.detail}")
    return 0


def _evergreen(repo_root: Path) -> list[Path]:
    """The files the evergreen globs match under *repo_root*, less the exempt ones, sorted."""
    found = {
        path
        for pattern in EVERGREEN
        for path in repo_root.glob(pattern, case_sensitive=True)
        if path.is_file()
    }
    kept = (
        path
        for path in found
        if not any(
            PurePosixPath(path.relative_to(repo_root).as_posix()).full_match(pattern)
            for pattern in EXEMPT
        )
    )
    return sorted(kept, key=lambda path: path.relative_to(repo_root).as_posix())


def _session_headings(text: str) -> Iterator[str]:
    """``line N: <heading>`` for each session-style heading in *text* outside fenced code."""
    lines = enumerate(zip(prose(text).split("\n"), text.split("\n"), strict=True), start=1)
    for number, (blanked, line) in lines:
        # The blanked line says whether it is a heading; the line keeps its inline code.
        heading = _HEADING.match(line) if _HEADING.match(blanked) else None
        if heading and _is_session_style(heading[2]):
            yield f"line {number}: {line.strip()}"


def _is_session_style(heading: str) -> bool:
    """Whether *heading*, a heading's text without its ``#`` marks, reads as a dated record."""
    words = heading[number.end() :] if (number := _SECTION_NUMBER.match(heading)) else heading
    return bool(
        _ISO_DATE.search(heading) or _ORDINAL_ROUND.search(heading) or _SESSION_START.match(words)
    )


def _work_findings(repo_root: Path, run: Runner, today: date) -> list[Finding]:
    """The stale-issue, missing-outcome and folder findings for *repo_root*'s ``work/``."""
    findings: list[Finding] = []
    folders: list[WorkFolder] = []
    for path in _work_folder_paths(repo_root / "work"):
        try:
            folders.append(parse_folder(path))
        except WorkFolderError as error:
            relative = path.relative_to(repo_root).as_posix()
            findings.append(Finding(relative, "folder", str(error), 1))
    issues = [(folder.issue, folder) for folder in folders if folder.issue is not None]
    if not issues:
        return findings
    statuses = issue_statuses((issue for issue, _folder in issues), run)
    if statuses is None:
        print(
            "doc-health: gh unavailable or signed out, so the stale-issue and missing-outcome "
            "checks were skipped",
            file=sys.stderr,
        )
        return findings
    git_works = True
    for issue, folder in issues:
        relative = folder.path.relative_to(repo_root).as_posix()
        status = statuses.get(issue)
        if status == "active" and git_works:
            try:
                last = _last_commit(repo_root, relative, run)
            except OSError, subprocess.CalledProcessError, ValueError:
                print(
                    "doc-health: git log failed, so the stale-issue check was skipped",
                    file=sys.stderr,
                )
                git_works = False
                continue
            if last is not None and (today - last).days >= STALE_DAYS:
                detail = f"issue #{issue} is open and no commit has touched the folder since {last}"
                findings.append(Finding(relative, "stale-issue", detail, 1))
        elif status in ("landed", "abandoned") and not folder.outcome.strip():
            detail = f"issue #{issue} is closed ({status}) and outcome is empty"
            findings.append(Finding(relative, "missing-outcome", detail, 1))
    return findings


def _work_folder_paths(work_root: Path) -> list[Path]:
    """The directories in *work_root*'s ``YYYY-MM`` directories, sorted."""
    if not work_root.is_dir():
        return []
    months = [d for d in work_root.iterdir() if d.is_dir() and MONTH_PATTERN.fullmatch(d.name)]
    return sorted(path for month in months for path in month.iterdir() if path.is_dir())


def _last_commit(repo_root: Path, folder: str, run: Runner) -> date | None:
    """The date of the last commit touching *folder*; None when none has.

    Raises OSError or subprocess.CalledProcessError when git fails, ValueError when its answer
    is not a date.
    """
    answer = run(["git", "-C", str(repo_root), "log", "-1", "--format=%cs", "--", folder])
    return date.fromisoformat(answer.strip()) if answer.strip() else None


if __name__ == "__main__":
    sys.exit(main())
