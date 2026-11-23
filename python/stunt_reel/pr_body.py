"""A pull request body's link to the issue its work belongs to.

A body names that issue on a ``Fixes``, ``Closes`` or ``Part of`` line.
``pr_lint`` fails a body without one and ``merge_bar`` reads the links it names, so both
match the one pattern defined here (#983).
"""

from __future__ import annotations

import re

#: A body's closing keyword and issue number; ``Fixes #8630`` does not link issue 863.
LINKED = re.compile(r"(?:Fixes|Closes|Part of) #(\d+)(?!\d)")


def issue_links(body: str) -> list[re.Match[str]]:
    """Every ``Fixes``, ``Closes`` or ``Part of #N`` link in *body*, in body order."""
    return list(LINKED.finditer(body))
