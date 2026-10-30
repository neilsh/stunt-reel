"""Claiming the next numbered run directory."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from stunt_reel import runs

if TYPE_CHECKING:
    from pathlib import Path


def test_first_and_next_run(tmp_path: Path) -> None:
    """An absent parent is created; the next run follows the greatest number."""
    parent = tmp_path / "frames"
    assert runs.run_numbers(parent) == []
    assert runs.claim_run(parent) == "001"
    assert runs.claim_run(parent) == "002"
    assert (parent / "002").is_dir()


def test_a_suffixed_sibling_holds_its_number(tmp_path: Path) -> None:
    """``003.lock`` and ``003.partial`` count, and other names are ignored."""
    (tmp_path / "003.lock").mkdir()
    (tmp_path / "notes").mkdir()
    assert runs.run_numbers(tmp_path) == [3]
    assert runs.claim_run(tmp_path, ".lock") == "004"
    assert (tmp_path / "004.lock").is_dir()


def test_numbers_sort_numerically_past_999(tmp_path: Path) -> None:
    """``1000`` follows ``999``, not ``100``."""
    (tmp_path / "999").mkdir()
    assert runs.claim_run(tmp_path) == "1000"
    assert runs.claim_run(tmp_path) == "1001"


def test_concurrent_claims_are_distinct(tmp_path: Path) -> None:
    """Sixteen simultaneous claimants each get their own directory."""
    with ThreadPoolExecutor(max_workers=16) as pool:
        claimed = list(pool.map(lambda _: runs.claim_run(tmp_path), range(16)))
    assert sorted(claimed) == [f"{n:03d}" for n in range(1, 17)]
