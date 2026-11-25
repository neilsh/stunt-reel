"""``label_sync`` diffs canonical labels against GitHub REST pages; nothing calls ``gh``."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

lazy import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import label_sync as ls  # noqa: E402
import labels  # noqa: E402
from gh_api import GhError  # noqa: E402


def _remote(spec: labels.LabelSpec, **overrides: Any) -> dict[str, Any]:
    return {"name": spec.name, "color": spec.color, "description": spec.description, **overrides}


def test_plan_sync_finds_missing_drifted_and_extra_labels() -> None:
    first, second, third = labels.CATALOG[:3]
    existing = [
        _remote(first),
        {"name": second.name.upper(), "color": "ffffff", "description": "old"},
        {"name": "type:tooling", "color": "5319E7", "description": "retired"},
    ]
    actions, extras = ls.plan_sync(existing, catalog=(first, second, third))
    assert [(a.kind, a.spec.name, a.reasons) for a in actions] == [
        (
            "update",
            second.name,
            (
                f"name '{second.name.upper()}' -> '{second.name}'",
                f"color FFFFFF -> {second.color}",
                "description",
            ),
        ),
        ("create", third.name, ()),
    ]
    assert extras == ["type:tooling"]


def test_plan_sync_is_empty_when_remote_matches_catalog() -> None:
    existing = [_remote(spec, color=spec.color.lower()) for spec in labels.CATALOG]
    actions, extras = ls.plan_sync(existing)
    assert actions == []
    assert extras == []


def test_fetch_labels_reads_numbered_rest_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ls, "PER_PAGE", 2)
    calls: list[tuple[str, ...]] = []
    pages = [
        [{"name": "a"}, {"name": "b"}],
        [{"name": "c"}],
    ]

    def gh(*args: str) -> Any:
        calls.append(args)
        page = int(args[-1].rsplit("page=", 1)[1])
        return pages[page - 1]

    monkeypatch.setattr(ls, "gh_json", gh)
    assert [entry["name"] for entry in ls.fetch_labels("o/r")] == ["a", "b", "c"]
    assert calls == [
        ("api", "repos/o/r/labels?per_page=2&page=1"),
        ("api", "repos/o/r/labels?per_page=2&page=2"),
    ]


def test_main_dry_run_makes_no_writes_and_apply_posts_and_patches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = labels.CATALOG[:2]
    monkeypatch.setattr(labels, "CATALOG", (first, second))
    writes: list[tuple[str, ...]] = []

    def gh(*args: str) -> Any:
        if "-X" not in args:
            return [
                {"name": first.name, "color": "000000", "description": first.description},
                {"name": "type:tooling", "color": "5319E7", "description": "retired"},
            ]
        writes.append(args)
        return {}

    monkeypatch.setattr(ls, "gh_json", gh)

    assert ls.main(["--repo", "o/r"]) == 0
    assert writes == []
    out = capsys.readouterr().out
    assert f"update: {first.name} #{first.color} (color 000000 -> {first.color})" in out
    assert f"create: {second.name} #{second.color}" in out
    assert "extra on remote: type:tooling" in out

    assert ls.main(["--apply", "--repo", "o/r"]) == 0
    out_apply = capsys.readouterr().out
    assert f"updated: {first.name} #{first.color}" in out_apply
    assert f"created: {second.name} #{second.color}" in out_apply
    assert writes == [
        (
            "api",
            "-X",
            "PATCH",
            "repos/o/r/labels/status%3Aneeds-triage",
            "-f",
            f"new_name={first.name}",
            "-f",
            f"color={first.color}",
            "-f",
            f"description={first.description}",
        ),
        (
            "api",
            "-X",
            "POST",
            "repos/o/r/labels",
            "-f",
            f"name={second.name}",
            "-f",
            f"color={second.color}",
            "-f",
            f"description={second.description}",
        ),
    ]


def test_main_prints_unchanged_when_already_synced(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ls, "gh_json", lambda *_a: [_remote(spec) for spec in labels.CATALOG])
    assert ls.main([]) == 0
    assert capsys.readouterr().out == "unchanged: all canonical labels match\n"


def test_main_apply_reports_completed_actions_before_gh_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second = labels.CATALOG[:2]
    monkeypatch.setattr(labels, "CATALOG", (first, second))
    writes = 0

    def gh(*args: str) -> Any:
        nonlocal writes
        if "-X" not in args:
            return [{"name": first.name, "color": "000000", "description": first.description}]
        writes += 1
        if writes == 1:
            return {}
        raise GhError("HTTP 422")

    monkeypatch.setattr(ls, "gh_json", gh)
    assert ls.main(["--apply", "--repo", "o/r"]) == 2
    captured = capsys.readouterr()
    assert f"updated: {first.name} #{first.color}" in captured.out
    assert f"created: {second.name}" not in captured.out
    assert captured.err == "label-sync: HTTP 422\n"


def test_main_exits_2_on_gh_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*_args: str) -> Any:
        raise GhError("HTTP 403")

    monkeypatch.setattr(ls, "gh_json", fail)
    assert ls.main([]) == 2
    assert capsys.readouterr().err == "label-sync: HTTP 403\n"
