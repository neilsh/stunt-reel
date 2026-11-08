"""Reading Markdown's prose: the text outside fenced code blocks and inline code."""

from __future__ import annotations

import re

__all__ = ["prose"]

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
