"""Reading Markdown's prose: its text outside code, and its links, headings and anchors."""

from __future__ import annotations

import bisect
import functools
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from stunt_reel.git_env import isolated_env

__all__ = [
    "HEADING_REGEX",
    "HTML_ANCHOR_REGEX",
    "LINK_DEFINITION_REGEX",
    "MARKDOWN_LINK_REGEX",
    "SECTION_NUMBER_REGEX",
    "TOKEN_REGEX",
    "URL_SCHEME_REGEX",
    "Link",
    "ResolvedTarget",
    "anchor_matches",
    "anchors",
    "anchors_of",
    "extract_links",
    "headings",
    "ignore_rules",
    "prose",
    "resolve_target",
    "slug",
]

#: An ATX heading line, as GitHub renders one: group 1 is its ``#`` marks, group 2 its text
#: without the spaces around it. Match it against a `prose` line, so fenced code holds none.
HEADING_REGEX = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
#: A section number opening a heading's text, ``5.``, ``4.1`` or ``4.1.``, and the spaces after.
SECTION_NUMBER_REGEX = re.compile(r"\d+(?:\.\d+)*\.?\s+")

#: An inline or image link, ``[text](target "title")``; group 1 is the target, without ``<>``.
MARKDOWN_LINK_REGEX = re.compile(r"!?\[[^\]\n]*\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)")
#: A reference-style link definition, ``[label]: target``, which the inline regex does not see;
#: group 1 is the target. A footnote, ``[^1]: text``, is not one.
LINK_DEFINITION_REGEX = re.compile(r"^ {0,3}\[(?!\^)[^\]\n]+\]:\s*<?([^\s>]+)>?", re.MULTILINE)
#: The scheme that starts a link target which is a URL (``https:``, ``mailto:``), not a repo path.
URL_SCHEME_REGEX = re.compile(r"[a-z][a-z0-9+.-]*:")
#: An HTML anchor: any element's ``id="x"`` or ``name="x"``, single- or double-quoted; group 1 is
#: the anchor. A fenced sample is prose-blanked, so it defines none.
HTML_ANCHOR_REGEX = re.compile(r"""<[A-Za-z][^>]*?\s(?:id|name)=["']([^"']+)["']""")
#: A bracketed anchor token, ``[MEM-SOD-VM]``, which a fragment may name; group 1 is the token.
TOKEN_REGEX = re.compile(r"\[([A-Za-z0-9_-]+)\]")

_FENCE = "```"
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True)
class Link:
    """One link target in a Markdown document: *target*, its prose offset, and its 1-based *line*."""

    target: str
    start: int
    line: int


@dataclass(frozen=True)
class ResolvedTarget:
    """A link resolved against its source: the file it names, its repo path, and its fragment.

    *relative* is the lexical path inside the repository, which keeps a target under a data-root
    junction inside it, so the repository's ignore rules answer for it; None when it lies outside.
    """

    file: Path
    relative: str | None
    fragment: str


def slug(heading: str) -> str:
    """GitHub's heading anchor for *heading* text: lower case, punctuation dropped, spaces to
    hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def prose(text: str, *, inline_code: bool = True) -> str:
    """*text* with fenced blocks, their fence lines and, when *inline_code*, code spans blanked.

    Every line ending stays, so an offset or line number in the result is the same in *text*.
    A line whose stripped text starts with three backticks opens or closes a block.
    """
    out: list[str] = []
    in_block = False
    for line in text.splitlines(keepends=True):
        content = line.splitlines()[0]
        ending = line[len(content) :]
        if content.strip().startswith(_FENCE):
            in_block = not in_block
            content = " " * len(content)
        elif in_block:
            content = " " * len(content)
        elif inline_code:
            content = _INLINE_CODE.sub(lambda code: " " * len(code[0]), content)
        out.append(content + ending)
    return "".join(out)


def headings(text: str) -> list[str]:
    """The text of each ATX heading outside fenced code, in document order, duplicates kept."""
    visible = prose(text)
    found: list[str] = []
    for blanked, line in zip(visible.splitlines(), text.splitlines(), strict=True):
        if not HEADING_REGEX.match(blanked):
            continue
        # The blanked line says whether it is a heading; the line keeps its inline code.
        heading = HEADING_REGEX.match(line)
        if heading is not None:
            found.append(heading.group(2))
    return found


def anchors(text: str) -> set[str]:
    """Every fragment *text* defines.

    Heading slugs are numbered like GitHub's, in document order: a second ``About`` is
    ``about-1``. HTML ``id``/``name`` values and bracketed tokens count too, tokens lower-cased.
    Fenced blocks and inline code define none.
    """
    visible = prose(text)
    found: set[str] = set()
    for heading in headings(text):
        base = slug(heading)
        candidate = base
        number = 0
        while candidate in found:
            number += 1
            candidate = f"{base}-{number}"
        found.add(candidate)
    found.update(HTML_ANCHOR_REGEX.findall(visible))
    found.update(token.lower() for token in TOKEN_REGEX.findall(visible))
    return found


@functools.cache
def anchors_of(path: Path) -> set[str]:
    """The anchors of the Markdown file at *path*, read once."""
    return anchors(path.read_text(encoding="utf-8"))


def anchor_matches(fragment: str, found: set[str]) -> bool:
    """Whether *fragment*, from a link, names one of *found*'s anchors."""
    return fragment in found or fragment.lower() in found or slug(fragment) in found


def extract_links(text: str) -> list[Link]:
    """Every inline and reference-style link target in *text*'s prose, in document order."""
    visible = prose(text)
    newlines = [match.end() for match in re.finditer("\n", visible)]
    found: list[Link] = []
    for regex in (MARKDOWN_LINK_REGEX, LINK_DEFINITION_REGEX):
        for match in regex.finditer(visible):
            start = match.start()
            found.append(Link(match.group(1), start, bisect.bisect_right(newlines, start) + 1))
    found.sort(key=lambda link: link.start)
    return found


def resolve_target(source: Path, target: str, root: Path) -> ResolvedTarget | None:
    """Resolve *target*, linked from *source*, against *root*; None when it is a URL."""
    if URL_SCHEME_REGEX.match(target):
        return None
    file_part, _, fragment = target.partition("#")
    if file_part:
        lexical = Path(os.path.normpath(source.parent / file_part))
        file = (source.parent / file_part).resolve()
    else:
        lexical = Path(os.path.normpath(source))
        file = source.resolve()
    try:
        relative = lexical.relative_to(root).as_posix()
    except ValueError:
        relative = None
    return ResolvedTarget(file=file, relative=relative, fragment=fragment)


def _leading_link(repo_root: Path, path: str) -> str | None:
    """The shallowest leading component of *path* that is a symbolic link, in POSIX form.

    ``git check-ignore`` refuses a pathname that leads through a symbolic link, and with
    ``--stdin`` it refuses the whole batch rather than the one path, so a path beyond a link is
    asked about by the link instead. A link at the leaf needs no detour: git answers for the
    entry itself, and a junction is a directory to git, so nothing is found here on Windows.
    """
    parts = path.split("/")
    for index in range(1, len(parts)):
        candidate = "/".join(parts[:index])
        if (repo_root / candidate).is_symlink():
            return candidate
    return None


def _check_ignore(repo_root: Path, paths: set[str]) -> dict[str, str]:
    """The rule git reports for each ignored path in *paths*, keyed by the path git was given.

    A tree git cannot read yields no rules.
    """
    if not paths:
        return {}
    try:
        done = subprocess.run(
            ["git", "check-ignore", "-v", "-z", "--stdin"],  # noqa: S607 - git from PATH
            cwd=repo_root,
            env=isolated_env(keep_index=False),
            input="\0".join(sorted(paths)) + "\0",
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return {}
    if done.returncode not in (0, 1):
        return {}
    fields = done.stdout.split("\0")
    return {
        fields[index + 3]: f"{fields[index]}:{fields[index + 1]}:{fields[index + 2]}"
        for index in range(0, len(fields) - 3, 4)
        if not fields[index + 2].startswith("!")
    }


def ignore_rules(repo_root: Path, paths: set[str]) -> dict[str, str]:
    """The ignore rule each ignored repository-relative path in *paths* matches, as ``source:line:pattern``.

    A negation (``!pattern``) reports that a path is *not* ignored, so it contributes no rule. A
    tracked path is not ignored even where a rule matches, so a link to a committed file passes.
    A path that leads through a symbolic link is matched by its link's rule, which is what
    ``git check-ignore`` can answer for it. A tree git cannot read yields no rules.
    """
    probe = {path: _leading_link(repo_root, path) or path for path in paths}
    rules = _check_ignore(repo_root, set(probe.values()))
    return {path: rules[name] for path, name in probe.items() if name in rules}
