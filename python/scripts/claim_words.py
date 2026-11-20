#!/usr/bin/env python3
"""List rule 5's over-broad words on each line the branch adds under a rule 5 path.

AGENTS.md, Committing, rule 5 asks a fresh reviewer for any claim broader than its evidence and
names the paths whose changes need the pass. This task reads both from that rule, so AGENTS.md
is the one source, and lists every line the branch adds under a named path that holds one of the
words as a whole word, with the line and the nearest evidentiary tier tag on that line or in its
paragraph. Each hit is a line to check, not a failure: these words are often correct, so the run
exits 0 whatever it finds (2 when git or AGENTS.md cannot be read); it is not a hook or a gate
step.

Usage: mise run claim-words -- [<base>]. The base defaults to origin/main when that ref resolves,
else main; the changes are counted from its merge base with HEAD, working tree and untracked
files included, so a worker runs this before the rule 5 commit.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import gate
from formats_docs.catalog import EVIDENTIARY_TIERS

if TYPE_CHECKING:
    from collections.abc import Sequence

SECTION = "### Committing"
RULE_NUMBER = 5
_ITEM = re.compile(r"^(\d+)\. ")
_WORDS = re.compile(r"broader than its evidence \(([^)]*)\)")
_PATHS = re.compile(r"Before a push that changes (.+?), (?:a fresh reviewer|or before committing)")
_TICKED = re.compile(r"\x60([^\x60]+)\x60")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class Rule5Error(ValueError):
    """AGENTS.md no longer states rule 5 in the form this task reads."""


@dataclass(frozen=True)
class AddedLine:
    """One line the branch adds: repository-relative path, 1-based number, and text."""

    path: str
    number: int
    text: str


@dataclass(frozen=True)
class Hit:
    """An added line holding a rule word, and its nearest evidence tier, None when none."""

    path: str
    number: int
    word: str
    text: str
    tier: str | None


def rule_5(agents_md: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The over-broad words and change paths rule 5 names, read from the AGENTS.md file."""
    return parse_rule_5(agents_md.read_text(encoding="utf-8"))


def parse_rule_5(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The over-broad words and change paths AGENTS.md, Committing, rule 5 names."""
    item = _committing_item(text)
    words = _WORDS.search(item)
    paths = _PATHS.search(item)
    if words is None:
        raise Rule5Error("rule 5 no longer names its over-broad words in parentheses")
    if paths is None:
        raise Rule5Error("rule 5 no longer names its paths after 'Before a push that changes'")
    named = tuple(token.strip() for token in _TICKED.findall(words.group(1)))
    covered = tuple(token.strip() for token in _TICKED.findall(paths.group(1)))
    if not named or not covered:
        raise Rule5Error("rule 5 no longer states its words and paths in backticks")
    return named, covered


def _committing_item(text: str, number: int = RULE_NUMBER) -> str:
    """Item number of the Committing section, with its continuation lines."""
    lines = text.splitlines()
    heading = next((index for index, line in enumerate(lines) if line.strip() == SECTION), None)
    if heading is None:
        raise Rule5Error(f"AGENTS.md has no {SECTION!r} heading")
    item: list[str] = []
    for line in lines[heading + 1 :]:
        if line.startswith("#"):
            break
        numbered = _ITEM.match(line)
        if numbered is not None:
            if item:
                break
            if int(numbered.group(1)) == number:
                item.append(line)
        elif item:
            if not line.strip():
                break
            item.append(line)
    if not item:
        raise Rule5Error(f"AGENTS.md, {SECTION}, has no item {number}")
    return "\n".join(item)


def is_rule_5_path(path: str, patterns: Sequence[str]) -> bool:
    """Whether repository-relative path is one of the rule 5 patterns.

    A pattern ending in / covers that directory; another is matched with PurePosixPath.full_match,
    as doc_health.py reads these paths, so docs/*.md stays within docs/ and covers no subdirectory.
    """
    for pattern in patterns:
        if pattern.endswith("/"):
            if path.startswith(pattern):
                return True
        elif PurePosixPath(path).full_match(pattern):
            return True
    return False


def words_in(text: str, words: Sequence[str]) -> tuple[str, ...]:
    """The rule words text holds as whole words, case-insensitive, each once, in text order."""
    by_lower = {word.lower(): word for word in words}
    ordered = sorted(words, key=len, reverse=True)
    alternatives = "|".join(re.escape(word) for word in ordered)
    pattern = re.compile(r"\b(?:" + alternatives + r")\b", re.IGNORECASE)
    found: list[str] = []
    for match in pattern.finditer(text):
        word = by_lower[match.group(0).lower()]
        if word not in found:
            found.append(word)
    return tuple(found)


def nearest_tier(lines: Sequence[str], index: int, tiers: Sequence[str]) -> str | None:
    """The evidence-tier tag nearest line index in its paragraph, or None.

    A paragraph is the run of non-blank lines around index. A tag on the line wins ties, then the
    nearest line above or below; two tags on one line resolve by column.
    """
    if not 0 <= index < len(lines):
        return None
    start = index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = index
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    best: tuple[int, int, int, str] | None = None
    for at in range(start, end + 1):
        for tier in tiers:
            column = lines[at].find(tier)
            if column < 0:
                continue
            candidate = (abs(at - index), at, column, tier)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
    return None if best is None else best[3]


def _git(repo: Path, *args: str) -> str:
    """The stdout of git args in repo; raises CalledProcessError or OSError."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return done.stdout


def _untracked(repo: Path) -> set[str]:
    """The paths git does not track, relative to repo."""
    listed = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return {path for path in listed.split("\0") if path}


def _file_lines(repo: Path, path: str) -> list[str]:
    """The lines of the working-tree file at path, or none when it is gone."""
    try:
        return (repo / path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _diff_added(repo: Path, base: str, paths: Sequence[str]) -> list[AddedLine]:
    """The lines the tracked paths add between base and the working tree, renames followed.

    One diff over every path, so rename detection keeps a moved note's unchanged lines out of the
    result. A hunk is consumed by its line counts, so added content that looks like a header is
    still content.
    """
    output = _git(
        repo,
        "diff",
        "-M",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        base,
        "--",
        *paths,
    )
    added: list[AddedLine] = []
    path: str | None = None
    number = 0
    old_left = 0
    new_left = 0
    for line in output.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("+"):
                if path is not None:
                    added.append(AddedLine(path, number, line[1:]))
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith(" "):
                number += 1
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith(("+++ ", "diff --git ")):
            path = None
        hunk = _HUNK.match(line)
        if hunk is not None:
            number = int(hunk.group(3))
            old_left = int(hunk.group(2) or 1)
            new_left = int(hunk.group(4) or 1)
    return added


def added_lines(repo: Path, base: str | None, patterns: Sequence[str]) -> list[AddedLine]:
    """Every line the branch adds under a rule 5 path, in path order."""
    base = base or gate.default_base(repo)
    merge_base = _git(repo, "merge-base", "HEAD", base).strip()
    if not merge_base:
        raise gate.ChangedPathsError(f"no merge base between HEAD and {base}")
    untracked = _untracked(repo)
    covered = [path for path in gate.changed_paths(repo, base) if is_rule_5_path(path, patterns)]
    tracked = [path for path in covered if path not in untracked]
    found = _diff_added(repo, merge_base, tracked) if tracked else []
    for path in covered:
        if path in untracked:
            found.extend(
                AddedLine(path, number, text)
                for number, text in enumerate(_file_lines(repo, path), start=1)
            )
    found.sort(key=lambda line: (line.path, line.number))
    return found


def hits(
    repo: Path, lines: Sequence[AddedLine], words: Sequence[str], tiers: Sequence[str]
) -> list[Hit]:
    """The hit for each rule word on each added line, with its nearest evidence tier."""
    by_path: dict[str, list[AddedLine]] = {}
    for line in lines:
        by_path.setdefault(line.path, []).append(line)
    found: list[Hit] = []
    for path, path_lines in by_path.items():
        file_lines = _file_lines(repo, path)
        for line in path_lines:
            tier = nearest_tier(file_lines, line.number - 1, tiers)
            for word in words_in(line.text, words):
                found.append(Hit(path, line.number, word, line.text, tier))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """Print each hit and a one-line count; return 0 whatever it finds, 2 on a read error."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "base",
        nargs="?",
        help="the ref changes are counted from (default: origin/main, else main)",
    )
    args = parser.parse_args(argv)
    try:
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        words, patterns = rule_5(repo / "AGENTS.md")
        found = hits(repo, added_lines(repo, args.base, patterns), words, EVIDENTIARY_TIERS)
    except (
        OSError,
        UnicodeDecodeError,
        subprocess.CalledProcessError,
        gate.ChangedPathsError,
        Rule5Error,
    ) as error:
        print(f"claim-words: {error}", file=sys.stderr)
        return 2
    for hit in found:
        print(f"{hit.path}:{hit.number}: {hit.word}")
        print(f"  {hit.text.strip()}")
        print(f"  {hit.tier or 'no evidentiary tier'}")
    print(
        f"claim-words: {len(found)} hit(s); each is a line to check, not a failure.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
