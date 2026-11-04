"""`mise run debug-x`: arguments, refusals before launch, and the summary."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import debug_x
import pytest

import dbx_stubs

if TYPE_CHECKING:
    from collections.abc import Iterator

PLANS = Path(__file__).resolve().parent.parent / "tools/dosbox-x/plans"


def test_parse_args_defaults() -> None:
    args = debug_x.parse_args(["--plan", "p.toml"])
    assert args.plan == Path("p.toml")
    assert args.build == "unpatched"
    assert args.film.name == "CTRY.FLM"
    assert args.out.name == "debug"


def test_unknown_build_rejected() -> None:
    with pytest.raises(SystemExit):
        debug_x.parse_args(["--plan", "p.toml", "--build", "beta"])


@contextmanager
def _no_boot(*_a: object, **_k: object) -> Iterator[None]:
    called = True
    if called:
        pytest.fail("booted must not be called")
    yield


def test_patched_unmappable_exits_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(debug_x, "ensure_links_or_report", lambda _p: True)
    monkeypatch.setattr(debug_x, "load_image", lambda _p: dbx_stubs.image())
    monkeypatch.setattr(debug_x, "pair_images", lambda _a, _b: dbx_stubs.pairing())
    monkeypatch.setattr(debug_x, "booted", _no_boot)
    assert debug_x.main(["--plan", str(PLANS / "smoke.toml"), "--build", "patched"]) == 2


def test_bad_plan_exits_2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(debug_x, "ensure_links_or_report", lambda _p: True)
    monkeypatch.setattr(debug_x, "booted", _no_boot)
    bad = tmp_path / "bad.toml"
    bad.write_text('[[probe]]\nname = "p"\nkind = "break"\n', encoding="utf-8")
    assert debug_x.main(["--plan", str(bad)]) == 2


def test_summary_rows() -> None:
    records: list[dict[str, Any]] = [
        {"type": "run", "plan": "smoke", "build": "unpatched"},
        {"type": "hit", "probe": "light", "return_far_image": 0x2350, "writer": None},
        {"type": "hit", "probe": "light", "return_far_image": 0x2350, "writer": None},
        {"type": "hit", "probe": "w", "return_far_image": None, "writer": {"image": 0x43E6}},
        {"type": "end", "reason": "spent", "hits": {"light": 2, "w": 1}, "spurious": 3, "ignored": {"light": 0, "w": 4}},
    ]  # fmt: skip
    text = "\n".join(debug_x.summary(records))
    assert "light" in text
    assert "0x2350 x2" in text
    assert "0x43e6 x1" in text
    assert "spurious 3" in text
    assert "spent" in text
    assert len(debug_x.summary(records)) <= debug_x.SUMMARY_LINES
