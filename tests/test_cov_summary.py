"""``cov_summary.py`` groups lcov and ``coverage json`` files into per-crate and per-package tables."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import cov_summary

if TYPE_CHECKING:
    from pathlib import Path

LCOV = r"""
SF:E:\work\crates\stunt-core\src\lib.rs
FNF:4
FNH:3
LF:10
LH:8
end_of_record
SF:/work/crates/stunt-core/src/vfs.rs
FNF:1
FNH:1
LF:5
LH:5
end_of_record
SF:/work/crates/stunt-gltf/src/lib.rs
FNF:0
FNH:0
LF:0
LH:0
end_of_record
SF:/home/.cargo/registry/src/dep/src/lib.rs
LF:99
LH:1
end_of_record
"""


def _entry(hit: int, total: int, branch_hit: int, branch_total: int) -> dict[str, dict[str, int]]:
    return {
        "summary": {
            "covered_lines": hit,
            "num_statements": total,
            "covered_branches": branch_hit,
            "num_branches": branch_total,
        }
    }


def test_lcov_sums_each_crate_and_drops_files_outside_crates() -> None:
    groups = cov_summary.lcov_groups(LCOV)
    assert sorted(groups) == ["crates/stunt-core", "crates/stunt-gltf"]
    core = groups["crates/stunt-core"]
    assert (core.lines_hit, core.lines_total) == (13, 15)
    assert (core.other_hit, core.other_total) == (4, 5)


def test_json_groups_split_the_package_from_the_scripts() -> None:
    report = {
        "files": {
            r"python\stunt_reel\a.py": _entry(3, 4, 1, 2),
            "python/stunt_reel/sub/b.py": _entry(1, 1, 0, 0),
            "python/scripts/gate.py": _entry(2, 8, 0, 4),
            "tests/test_x.py": _entry(9, 9, 0, 0),
        }
    }
    groups = cov_summary.json_groups(report)
    assert sorted(groups) == ["python/scripts", "python/stunt_reel"]
    assert (groups["python/stunt_reel"].lines_hit, groups["python/stunt_reel"].lines_total) == (
        4,
        5,
    )
    assert groups["python/scripts"].other_total == 4


def test_percent_of_an_empty_total_is_not_a_number() -> None:
    assert cov_summary.percent(0, 0) == "n/a"
    assert cov_summary.percent(1, 8) == "12.5%"


def test_render_prints_both_tables_and_a_total(tmp_path: Path) -> None:
    (tmp_path / "lcov.info").write_text(LCOV, encoding="utf-8")
    report = {"files": {"python/scripts/gate.py": _entry(2, 8, 1, 4)}}
    (tmp_path / "coverage.json").write_text(json.dumps(report), encoding="utf-8")
    text, ok = cov_summary.render(tmp_path)
    assert ok
    assert "| `crates/stunt-core` | 13 / 15 | 86.7% | 4 / 5 | 80.0% |" in text
    assert "| `python/scripts` | 2 / 8 | 25.0% | 1 / 4 | 25.0% |" in text
    assert "| **total** | 13 / 15 |" in text


def test_a_missing_file_is_named_and_fails_the_exit_status(tmp_path: Path) -> None:
    (tmp_path / "lcov.info").write_text(LCOV, encoding="utf-8")
    text, ok = cov_summary.render(tmp_path)
    assert not ok
    assert "coverage.json" in text
    assert "`crates/stunt-core`" in text
    assert cov_summary.main(["--dir", str(tmp_path)]) == 1


def test_an_unparseable_file_is_named_and_the_other_table_still_prints(tmp_path: Path) -> None:
    (tmp_path / "lcov.info").write_text(LCOV, encoding="utf-8")
    (tmp_path / "coverage.json").write_text(
        '{"files": {"python/scripts/gate.py": ', encoding="utf-8"
    )
    text, ok = cov_summary.render(tmp_path)
    assert not ok
    assert "coverage.json" in text
    assert "could not be read" in text
    assert "| `crates/stunt-core` | 13 / 15 |" in text
    assert cov_summary.main(["--dir", str(tmp_path)]) == 1


def test_a_report_of_the_wrong_shape_is_named_not_raised(tmp_path: Path) -> None:
    (tmp_path / "lcov.info").write_text(LCOV, encoding="utf-8")
    (tmp_path / "coverage.json").write_text("{}", encoding="utf-8")
    text, ok = cov_summary.render(tmp_path)
    assert not ok
    assert "could not be read" in text
