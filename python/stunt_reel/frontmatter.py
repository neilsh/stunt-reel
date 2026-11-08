"""The `---` block of `key: value` scalars that opens a markdown file.

Read with the standard library, so the docs tooling takes no YAML dependency: a value is a
string or an int, never a list or a map.
"""

from __future__ import annotations

__all__ = ["FrontmatterError", "read_frontmatter"]

_FENCE = "---"


class FrontmatterError(ValueError):
    """The frontmatter block is unclosed, holds a line that is not `key: value`, or repeats a key."""


def read_frontmatter(text: str) -> tuple[dict[str, str | int], str]:
    """The fields of *text*'s leading `---` block and the body after its closing `---` line.

    A *text* whose first line is not `---` is all body, `({}, text)`. A value of digits reads
    as an int, a double-quoted one is unquoted with `\\"` unescaped, any other is the stripped
    string. Raises FrontmatterError, naming the line, for an unclosed block, a line without
    `: ` or a repeated key.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != _FENCE:
        return {}, text
    fields: dict[str, str | int] = {}
    for number, line in enumerate(lines[1:], start=2):
        content = line.rstrip("\r\n")
        if content == _FENCE:
            return fields, "".join(lines[number:])
        key, sep, value = content.partition(": ")
        key = key.strip()
        if not sep or not key:
            raise FrontmatterError(f"line {number}: {content!r} is not a 'key: value' pair")
        if key in fields:
            raise FrontmatterError(f"line {number}: key {key!r} repeats")
        fields[key] = _scalar(value.strip())
    raise FrontmatterError("line 1: the '---' block is never closed")


def _scalar(value: str) -> str | int:
    if value.isascii() and value.isdecimal():
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"')
    return value
