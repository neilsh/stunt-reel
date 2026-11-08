"""The `---` block of `key: value` scalars that opens a markdown file.

Read with the standard library, so the docs tooling takes no YAML dependency: a value is a
string or an int, never a list or a map.
"""

from __future__ import annotations

__all__ = ["FrontmatterError", "read_frontmatter"]

_FENCE = "---"
#: The characters a backslash may escape in a double-quoted value.
_ESCAPABLE = frozenset('"\\')


class FrontmatterError(ValueError):
    """The frontmatter block is unclosed, holds a line that is not `key: value`, repeats a key,
    or quotes a value with a backslash escape other than `\\"` and `\\\\`."""


def read_frontmatter(text: str) -> tuple[dict[str, str | int], str]:
    """The fields of *text*'s leading `---` block and the body after its closing `---` line.

    A *text* whose first line is not `---` is all body, `({}, text)`. A value of digits reads
    as an int, a double-quoted one is unquoted with `\\"` and `\\\\` unescaped, any other is the
    stripped string, backslashes and all. Raises FrontmatterError, naming the line, for an
    unclosed block, a line without `: `, a repeated key or a double-quoted value holding any
    other backslash escape, which GitHub's YAML would reject or read differently.
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
        fields[key] = _scalar(value.strip(), number)
    raise FrontmatterError("line 1: the '---' block is never closed")


def _scalar(value: str, number: int) -> str | int:
    if value.isascii() and value.isdecimal():
        return int(value)
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return _unescaped(value, number)
    return value


def _unescaped(value: str, number: int) -> str:
    """Double-quoted *value*, from line *number*, without its quotes and escapes."""
    out: list[str] = []
    chars = iter(value[1:-1])
    for char in chars:
        if char != "\\":
            out.append(char)
            continue
        escaped = next(chars, "")
        if escaped not in _ESCAPABLE:
            raise FrontmatterError(
                f"line {number}: {value} holds the escape \\{escaped}; a quoted value may "
                'escape only " and \\, as \\" and \\\\'
            )
        out.append(escaped)
    return "".join(out)
