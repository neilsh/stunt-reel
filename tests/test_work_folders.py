"""Every work folder under the repository's `work/` parses, and nothing else sits there."""

from __future__ import annotations

import pytest

from stunt_reel.work_items import MONTH_PATTERN, WORK_ROOT, WorkFolderError, scan

pytestmark = pytest.mark.docs


def test_every_work_folder_is_valid() -> None:
    try:
        scan()
    except WorkFolderError as error:
        pytest.fail(str(error))


def test_month_directories_hold_only_work_folders() -> None:
    stray: list[str] = []
    for entry in sorted(WORK_ROOT.iterdir()) if WORK_ROOT.is_dir() else []:
        if entry.is_dir() and MONTH_PATTERN.fullmatch(entry.name):
            stray += [f"{entry.name}/{e.name}" for e in sorted(entry.iterdir()) if not e.is_dir()]
        elif not (entry.is_file() and entry.name == "README.md"):
            stray.append(entry.name)
    assert not stray, (
        "work/ holds only README.md and YYYY-MM directories, which hold only work folders; "
        f"found: {', '.join(stray)}"
    )
