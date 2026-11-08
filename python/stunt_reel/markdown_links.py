"""Reading Markdown's prose: the text outside fenced and inline code, its links and headings."""

from __future__ import annotations

import re

__all__ = [
    "HEADING_REGEX",
    "LINK_DEFINITION_REGEX",
    "MARKDOWN_LINK_REGEX",
    "SECTION_NUMBER_REGEX",
    "URL_SCHEME_REGEX",
    "prose",
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

_FENCE = "```"
_INLINE_CODE = re.compile(r"`[^`\n]*`")


def prose(text: str) -> str:
    """*text* with fenced blocks, their fence lines and inline code spans blanked to spaces.

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
        else:
            content = _INLINE_CODE.sub(lambda code: " " * len(code[0]), content)
        out.append(content + ending)
    return "".join(out)
