#!/usr/bin/env python3
"""Reflow Markdown to one sentence per line, and check that the reflow changed nothing else.

One-off for #712, kept beside its plan as the record of how the reflow was made (plan.md, Task 2).

Usage: `mise exec -- uv run python work/2026-11/712_markdown-line-breaks/reflow.py
{selftest | scope | write PATH... | verify --base REF PATH...}`
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt

from stunt_reel.markdown_links import _INLINE_CODE, MARKDOWN_LINK_REGEX, prose

#: Paths `scope` leaves out (spec.md § Reflow scope).
EXCLUDED_PREFIXES = ("work/", "docs/adr/", "tests/fixtures/", "corpus/")
EXCLUDED_PATHS = {"research/MAP.md", ".github/pull_request_template.md"}

_FENCE = re.compile(r"^ *(`{3,}|~{3,})")
_ATX = re.compile(r"^ {0,3}#{1,6}(?:\s|$)")
_THEMATIC = re.compile(r"^ {0,3}([-*_])(?: *\1){2,} *$")
_SETEXT = re.compile(r"^ {0,3}(?:=+|-+) *$")
_LIST_ITEM = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)")
_BLOCKQUOTE = re.compile(r"^(?: {0,3}> ?)+")
_DEFINITION = re.compile(r"^ {0,3}\[[^\]]+\]:")
_TABLE_DELIMITER = re.compile(r"^ *\|? *:?-+:? *(?:\| *:?-+:? *)*\|? *$")
_HARD_BREAK = re.compile(r"(?:  |\\)$")

#: A sentence end: `.`, `?` or `!`, its closers, the spaces after, and what may start the next.
_SENTENCE_END = re.compile(r"[.?!][)\"*_]*( +)(?=[A-Z`\[(\"*_])")
#: What a split must not start a line with: it would turn prose into another block.
_BLOCK_START = re.compile(
    r"^(?:[-*+] |\d+[.)] |[#>|<]|```|~~~|\$\$|\[[^\]]*\]:|[*_](?: *[*_]){2,} *(?: |$))"
)
_ABBREVIATIONS = {"e.g.", "i.e.", "cf.", "vs.", "etc.", "approx.", "Fig.", "No."}
_LINK = re.compile(r"!?\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\])?")
_MATH = re.compile(r"\$(?=\S)[^$]*?(?<=\S)\$")
_HTML_TAG = re.compile(r"<[A-Za-z/!][^>]*>")
#: The markers after which `test_doc_invariants` allows a link to a dated record, to line end.
_PROVENANCE = re.compile(r"(?<!\S)[_*](?:Source:|Found )")

CASES = [
    ("One. Two.\n", "One.\nTwo.\n"),
    ("One two\nthree. Four.\n", "One two three.\nFour.\n"),  # hard wrap joined
    ("Why? Because! Yes.\n", "Why?\nBecause!\nYes.\n"),
    ("It **ends.** Next.\n", "It **ends.**\nNext.\n"),  # closing ** kept
    ("See e.g. Foo. Bar.\n", "See e.g. Foo.\nBar.\n"),  # abbreviation kept
    ("At 0x40. The end.\n", "At 0x40.\nThe end.\n"),
    ("Read [`a.md`](a.md). Then go.\n", "Read [`a.md`](a.md).\nThen go.\n"),
    ("[Do it. Now](x.md) ok.\n", "[Do it. Now](x.md) ok.\n"),  # not inside link text
    ("`a. B` c. D.\n", "`a. B` c.\nD.\n"),  # not inside a code span
    ("$a. B$ c.\n", "$a. B$ c.\n"),  # not inside inline math
    (
        "Claim. _Source: [A. B](../work/x.md)._\n",
        "Claim.\n_Source: [A. B](../work/x.md)._\n",
    ),  # not inside a _Source: span
    ("- One. Two.\n", "- One.\n  Two.\n"),
    ("- One two\n  three. Four.\n", "- One two three.\n  Four.\n"),  # hard-wrapped item
    ("1. One. Two.\n", "1. One.\n   Two.\n"),
    ("> One. Two\n> three. Four.\n", "> One.\n> Two three.\n> Four.\n"),
    ("One.  \nTwo. Three.\n", "One.  \nTwo.\nThree.\n"),  # hard break kept
    ("Done. 1. is odd.\n", "Done. 1. is odd.\n"),  # no split before a digit
    ("Done. [x]: y\n", "Done. [x]: y\n"),  # would start a definition
    ("| a. B | c. D |\n|---|---|\n", "| a. B | c. D |\n|---|---|\n"),
    ("# One. Two\n", "# One. Two\n"),
    ("```\nOne. Two.\n```\n", "```\nOne. Two.\n```\n"),
    ("---\nsummary: One. Two.\n---\nA. B.\n", "---\nsummary: One. Two.\n---\nA. B.\n"),
    ("One. Two\n---\n", "One. Two\n---\n"),  # setext heading untouched
]


def _code_spans(text: str) -> list[tuple[int, int]]:
    """Each code span's (start, end): a backtick run closed by the next run of the same length."""
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(text):
        if text[i] != "`":
            i += 1
            continue
        run_end = i
        while run_end < len(text) and text[run_end] == "`":
            run_end += 1
        closer = re.compile(rf"(?<!`){"`" * (run_end - i)}(?!`)")
        if match := closer.search(text, run_end):
            spans.append((i, match.end()))
            i = match.end()
        else:
            i = run_end
    return spans


def _protected(text: str) -> list[bool]:
    """Per character, whether a sentence split may not fall there."""
    mask = [False] * len(text)
    filled = list(text)
    for start, end in _code_spans(text):
        mask[start:end] = [True] * (end - start)
        filled[start:end] = "x" * (end - start)
    hidden = "".join(filled)
    for regex in (_LINK, _MATH, _HTML_TAG):
        for match in regex.finditer(hidden):
            mask[match.start() : match.end()] = [True] * (match.end() - match.start())
    if marker := _PROVENANCE.search(hidden):
        mask[marker.start() :] = [True] * (len(text) - marker.start())
    return mask


def _is_abbreviation(text: str, period: int) -> bool:
    word = text[: period + 1].rsplit(" ", 1)[-1].lstrip("([\"*_")
    return word in _ABBREVIATIONS or re.fullmatch(r"[A-Z]\.", word) is not None


def split_sentences(text: str) -> list[str]:
    """*text*, one paragraph line, cut after each sentence end that is safe to break at."""
    mask = _protected(text)
    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        if mask[match.start()] or mask[match.start(1)]:
            continue
        if text[match.start()] == "." and _is_abbreviation(text, match.start()):
            continue
        if _BLOCK_START.match(text[match.end() :]):
            continue
        pieces.append(text[start : match.start(1)])
        start = match.end()
    pieces.append(text[start:])
    return pieces


@dataclass
class _Paragraph:
    """A paragraph's source lines, and the prefixes its first and later lines take."""

    first_prefix: str
    later_prefix: str
    lines: list[str] = field(default_factory=list)  # content, prefixes removed
    raw: list[str] = field(default_factory=list)  # source lines as written
    verbatim: bool = False  # a setext heading or table header: written back unchanged

    def render(self, split: bool) -> list[str]:
        if self.verbatim:
            return self.raw
        segments: list[str] = []
        current: list[str] = []
        for line in self.lines:
            if _HARD_BREAK.search(line):
                current.append(line.strip(" ") if line.endswith("\\") else line.lstrip(" "))
                segments.append(" ".join(current))
                current = []
            else:
                current.append(line.strip(" "))
        if current:
            segments.append(" ".join(current))
        out: list[str] = []
        for segment in segments:
            for piece in split_sentences(segment) if split else [segment]:
                out.append((self.later_prefix if out else self.first_prefix) + piece)
        return out


def _transform(text: str, split: bool) -> str:
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    if lines and lines[0] == "---":
        end = next((n for n in range(1, len(lines)) if lines[n] in ("---", "...")), None)
        if end is not None:
            out.extend(lines[: end + 1])
            i = end + 1
    paragraph: _Paragraph | None = None
    fence: str | None = None  # the open fence's marker
    block_end: str | None = None  # what closes an open $$ block, HTML block or table: "" = blank
    list_indent = 0
    previous_blank = True

    def flush() -> None:
        nonlocal paragraph
        if paragraph is not None:
            out.extend(paragraph.render(split))
            paragraph = None

    while i < len(lines):
        line = lines[i]
        i += 1
        quote = _BLOCKQUOTE.match(line)
        prefix = quote[0] if quote else ""
        rest = line[len(prefix) :]
        blank = not rest.strip()
        if fence is not None:
            out.append(line)
            close = _FENCE.match(rest)
            if close and close[1][0] == fence[0] and len(close[1]) >= len(fence) and not rest.strip(" `~"):
                fence = None
            continue
        if block_end is not None:
            out.append(line)
            if (block_end == "" and blank) or (block_end and block_end in rest):
                block_end = None
                previous_blank = blank
            continue
        if blank:
            flush()
            out.append(line)
            previous_blank = True
            continue
        indent = len(rest) - len(rest.lstrip(" "))
        if previous_blank and paragraph is None and indent < list_indent and not _LIST_ITEM.match(rest):
            list_indent = 0
        stripped = rest.strip()
        following = lines[i] if i < len(lines) else ""
        following = following[len(m[0]) :] if (m := _BLOCKQUOTE.match(following)) else following
        is_table = stripped.startswith("|") or ("|" in rest and "|" in following and _TABLE_DELIMITER.match(following))
        if paragraph is not None and _SETEXT.match(rest) and prefix == paragraph.first_prefix[: len(prefix)]:
            paragraph.verbatim = True
            paragraph.raw.append(line)
            flush()
        elif (fence_open := _FENCE.match(rest)) or stripped.startswith("$$") or stripped.startswith("<") or is_table:
            flush()
            out.append(line)
            if fence_open:
                fence = fence_open[1]
            elif stripped.startswith("$$"):
                if not (len(stripped) > 2 and stripped.endswith("$$")):
                    block_end = "$$"
            elif stripped.startswith("<!--"):
                if "-->" not in stripped:
                    block_end = "-->"
            else:
                block_end = ""
        elif _ATX.match(rest) or _THEMATIC.match(rest) or _DEFINITION.match(rest):
            flush()
            out.append(line)
        elif item := _LIST_ITEM.match(rest):
            flush()
            content = rest[item.end() :]
            width = item.end()
            if not content.strip() or len(item[3]) > 4 or _BLOCK_START.match(content) or _FENCE.match(content):
                out.append(line)
                list_indent = width if content.strip() else len(item[1]) + len(item[2]) + 1
            else:
                list_indent = width
                paragraph = _Paragraph(prefix + rest[:width], prefix + " " * width)
                paragraph.lines.append(content)
                paragraph.raw.append(line)
        elif paragraph is not None and (not prefix or prefix == paragraph.first_prefix[: len(prefix)]):
            paragraph.lines.append(rest)
            paragraph.raw.append(line)
        elif paragraph is None and indent - list_indent >= 4:
            out.append(line)
        else:
            flush()
            lead = prefix + " " * indent
            paragraph = _Paragraph(lead, lead)
            paragraph.lines.append(rest)
            paragraph.raw.append(line)
        previous_blank = False
    flush()
    return "\n".join(out)


def join_paragraphs(text: str) -> str:
    """*text* with each paragraph's lines joined onto one line; nothing split."""
    return _transform(text, split=False)


def reflow_text(text: str) -> str:
    """*text* with each paragraph joined, then broken after each sentence."""
    return _transform(text, split=True)


def selftest() -> int:
    for given, want in CASES:
        got = reflow_text(given)
        if got != want:
            print(f"FAIL {given!r}\n  want {want!r}\n  got  {got!r}")
            return 1
    print(f"{len(CASES)} cases pass")
    return 0


def scope() -> list[str]:
    """The tracked Markdown paths the reflow covers."""
    listed = subprocess.run(["git", "ls-files", "*.md"], capture_output=True, text=True, check=True)
    return [
        path
        for path in listed.stdout.splitlines()
        if not path.startswith(EXCLUDED_PREFIXES) and path not in EXCLUDED_PATHS
    ]


def _body(text: str) -> str:
    """*text* without its YAML front matter."""
    match = re.match(r"---\n.*?\n(?:---|\.\.\.)\n", text, re.DOTALL)
    return text[match.end() :] if match else text


_RENDERER = MarkdownIt("commonmark").enable(["table", "strikethrough"])


def _html(text: str) -> str:
    return re.sub(r"\s+", " ", _RENDERER.render(_body(text))).strip()


def _counts(text: str) -> tuple[int, int]:
    return (
        len(MARKDOWN_LINK_REGEX.findall(prose(text))),
        len(_INLINE_CODE.findall(prose(text, inline_code=False))),
    )


def verify(base: str, paths: list[str]) -> int:
    """Exit status 1, naming each path whose HTML, links or code spans changed from *base*."""
    failed = 0
    for path in paths:
        old = subprocess.run(
            ["git", "show", f"{base}:{path}"], capture_output=True, text=True, check=True
        ).stdout
        new = Path(path).read_text(encoding="utf-8")
        if _html(old) != _html(new):
            print(f"{path}: rendered HTML differs")
            failed += 1
        elif _counts(join_paragraphs(old)) != _counts(new):
            print(f"{path}: links, code spans {_counts(join_paragraphs(old))} -> {_counts(new)}")
            failed += 1
    if failed:
        print(f"{failed} of {len(paths)} files failed")
        return 1
    print(f"{len(paths)} files: HTML, links and code spans unchanged")
    return 0


def main(argv: list[str]) -> int:
    match argv:
        case ["selftest"]:
            return selftest()
        case ["scope"]:
            print("\n".join(scope()))
            return 0
        case ["write", *paths] if paths:
            for path in paths:
                file = Path(path)
                file.write_text(reflow_text(file.read_text(encoding="utf-8")), encoding="utf-8")
            return 0
        case ["verify", "--base", base, *paths] if paths:
            return verify(base, paths)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
