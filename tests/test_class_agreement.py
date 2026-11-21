"""Tests for the class agreement figures, their file, the flags and the due rule (#908)."""

from __future__ import annotations

import datetime as dt
import subprocess
import tomllib
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from stunt_reel import class_agreement as ca
from stunt_reel.class_agreement import Agreement, FilmAgreement, Flag, Residue

if TYPE_CHECKING:
    from pathlib import Path

DAY = dt.date(2026, 11, 21)


def film(name: str = "ctry", mean: float = 4.0, hot: dict[int, int] | None = None) -> FilmAgreement:
    hot = hot or {}
    largest, largest_tick = max(((count, tick) for tick, count in hot.items()), default=(30, 0))
    return FilmAgreement(name, 100, 20, mean, largest, largest_tick, hot)


def agreement(*films: FilmAgreement, **changes: object) -> Agreement:
    base = Agreement(
        crates="9d08971" + "0" * 33,
        date=DAY,
        gpu_adapter="NVIDIA GeForce RTX 4070 Laptop GPU",
        gpu_driver="610.88",
        lavapipe_adapter="llvmpipe (LLVM 20.1.2, 256 bits)",
        lavapipe_driver="25.2.8-0ubuntu0.24.04.5",
        films={entry.film: entry for entry in films or (film(),)},
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_differing_pixels_counts_only_changed_bytes() -> None:
    """A plane of 12 pixels with two of them changed differs on two pixels."""
    assert ca.differing_pixels(bytes(12), bytes(12)) == 0
    assert ca.differing_pixels(bytes(12), bytes([0, 0, 255] + [0] * 9)) == 1
    assert ca.differing_pixels(b"\x00\x01", b"\x01\x00") == 2
    with pytest.raises(ValueError, match="planes of 2 and 3 bytes"):
        ca.differing_pixels(b"\x00\x01", b"\x00\x01\x02")


def test_from_residue_keeps_ticks_over_hot_threshold() -> None:
    summary = FilmAgreement.from_residue(Residue("ctry", [1, 2, 3, 4], [0, 501, 500, 1200]))
    assert summary.hot == {2: 501, 4: 1200}
    assert summary.differing_ticks == 3
    assert (summary.largest, summary.largest_tick) == (1200, 4)
    assert summary.ticks == 4
    assert summary.mean == pytest.approx(550.25)


def test_from_residue_of_no_ticks_is_empty() -> None:
    summary = FilmAgreement.from_residue(Residue("ctry", [], []))
    assert (summary.ticks, summary.differing_ticks, summary.largest, summary.hot) == (0, 0, 0, {})


TWO_FILMS = agreement(
    film("intro", 8.937, {416: 2075, 3830: 600}), film("ctry", 6.3), accepted="first baseline"
)

EXPECTED = (
    ca.HEADER
    + """\
[measured]
crates = "9d08971000000000000000000000000000000000"
date = 2026-11-21
gpu_adapter = "NVIDIA GeForce RTX 4070 Laptop GPU"
gpu_driver = "610.88"
lavapipe_adapter = "llvmpipe (LLVM 20.1.2, 256 bits)"
lavapipe_driver = "25.2.8-0ubuntu0.24.04.5"
accepted = "first baseline"

[ctry]
ticks = 100
differing_ticks = 20
mean = 6.30
largest = 30
largest_tick = 0

[intro]
ticks = 100
differing_ticks = 20
mean = 8.94
largest = 2075
largest_tick = 416

[intro.hot]
"416" = 2075
"3830" = 600
"""
)


def test_format_is_stable() -> None:
    assert ca.format_agreement(TWO_FILMS, ["ctry", "intro"]) == EXPECTED


def test_format_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "agreement.toml"
    path.write_bytes(ca.format_agreement(TWO_FILMS, ["ctry", "intro"]).encode())
    read = ca.read_agreement(path)
    assert read is not None
    assert read.pair() == TWO_FILMS.pair()
    assert (read.crates, read.date, read.accepted) == (TWO_FILMS.crates, DAY, "first baseline")
    assert read.films["intro"].hot == {416: 2075, 3830: 600}
    assert read.films["intro"].mean == pytest.approx(8.94)
    assert read.films["ctry"].hot == {}
    assert list(read.films) == ["ctry", "intro"]


def test_format_puts_unordered_films_last_by_name() -> None:
    text = ca.format_agreement(agreement(film("b"), film("a"), film("c")), ["c"])
    assert text.index("[c]") < text.index("[a]") < text.index("[b]")


def test_format_escapes_quotes() -> None:
    text = ca.format_agreement(agreement(accepted='new "driver"'), [])
    assert 'accepted = "new \\"driver\\""' in text


def test_read_agreement_malformed_raises_value_error(tmp_path: Path) -> None:
    path = tmp_path / "agreement.toml"
    path.write_text("[ctry]\nticks = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not an agreement file"):
        ca.read_agreement(path)
    path.write_text("[measured\n", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        ca.read_agreement(path)


def test_read_agreement_absent_is_none(tmp_path: Path) -> None:
    assert ca.read_agreement(tmp_path / "agreement.toml") is None


def only(found: list[Flag] | str) -> list[str]:
    assert isinstance(found, list)
    return [flag.title() for flag in found]


@pytest.mark.parametrize(
    ("before", "after", "flagged"),
    [(4.0, 5.1, True), (8.0, 9.5, False), (0.5, 1.2, False), (4.0, 3.0, False)],
)
def test_mean_rise_flags_only_above_ratio_and_minimum(
    before: float, after: float, flagged: bool
) -> None:
    found = ca.flags(agreement(film(mean=before)), agreement(film(mean=after)), {})
    assert only(found) == (["Agreement: ctry mean"] if flagged else [])


def test_tick_rise_flags_against_pinned_or_hot_threshold() -> None:
    pinned = agreement(film(hot={10: 800}))
    within = agreement(film(hot={10: 1700, 20: 1400}))
    assert only(ca.flags(pinned, within, {})) == []
    over = agreement(film(hot={10: 1900, 20: 1600}))
    found = ca.flags(pinned, over, {})
    assert only(found) == ["Agreement: ctry ticks 10-20"]
    assert isinstance(found, list)
    assert found[0].ticks == (10, 20)


def test_a_film_new_to_the_pin_flags_only_its_ssim_gap() -> None:
    measured = agreement(film(), film("bomb", 40.0, {5: 3000}))
    assert only(ca.flags(agreement(film()), measured, {"bomb": 0.003})) == [
        "Agreement: bomb ssim gap"
    ]


@pytest.mark.parametrize(("gap", "flagged"), [(-0.0021, True), (0.0019, False), (0.0021, True)])
def test_ssim_gap_flags_above_limit(gap: float, flagged: bool) -> None:
    found = ca.flags(agreement(), agreement(), {"ctry": gap})
    assert only(found) == (["Agreement: ctry ssim gap"] if flagged else [])


def test_changed_adapter_gives_reason_not_flags() -> None:
    reason = ca.flags(agreement(), agreement(gpu_adapter="AMD Radeon"), {"ctry": 0.01})
    assert isinstance(reason, str)
    assert "NVIDIA GeForce RTX 4070 Laptop GPU" in reason
    assert "AMD Radeon" in reason
    assert "--accept" in reason


def test_changed_driver_gives_reason_not_flags() -> None:
    reason = ca.flags(agreement(), agreement(lavapipe_driver="25.2.8-0ubuntu0.24.04.6"), {})
    assert isinstance(reason, str)
    assert "25.2.8-0ubuntu0.24.04.5" in reason
    assert "25.2.8-0ubuntu0.24.04.6" in reason
    assert "--accept" in reason


def test_nothing_pinned_gives_reason_not_flags() -> None:
    reason = ca.flags(None, agreement(), {})
    assert isinstance(reason, str)
    assert "--accept" in reason


def test_due_after_five_renderer_commits() -> None:
    assert ca.due(agreement(), ["c"] * 4, DAY) is None
    reason = ca.due(agreement(), ["c"] * 5, DAY)
    assert reason is not None
    assert "5 renderer commits" in reason


def test_due_after_seven_days_with_one_commit() -> None:
    assert ca.due(agreement(), ["c"], DAY + dt.timedelta(days=6)) is None
    assert ca.due(agreement(), ["c"], DAY + dt.timedelta(days=7)) is not None


def test_not_due_without_renderer_commits() -> None:
    assert ca.due(agreement(), [], DAY + dt.timedelta(days=60)) is None


def test_due_when_nothing_pinned() -> None:
    assert ca.due(None, [], DAY) is not None


def test_due_when_the_pinned_tree_is_not_on_the_branch() -> None:
    reason = ca.due(agreement(), None, DAY)
    assert reason is not None
    assert "not on the branch" in reason


def test_hot_share() -> None:
    assert ca.hot_share({1: 0.01, 2: 0.03, 3: -0.02}, {2: 900}) == pytest.approx(0.75)
    assert ca.hot_share({1: -0.01, 2: 0.0}, {2: 900}) is None


class Repo:
    """A scratch repository whose ``crates/`` holds a renderer file and a scorer file."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        hooks = root.parent / "no-hooks"
        hooks.mkdir()
        self._config = [
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}",
        ]  # fmt: skip
        self.git("init", "-q", "-b", "main")
        self.change("crates/render.rs", "fn a() {}\n")

    def git(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(self.root), *self._config, *args],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def change(self, name: str, text: str) -> str:
        """Commits *name* holding *text*; the new commit."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-qm", f"change {name}")
        return self.git("rev-parse", "HEAD")

    def tree(self) -> str:
        return self.git("rev-parse", "HEAD:crates")


SCORER = "crates/stunt-score/src/parity/score.rs"


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


def test_renderer_commits_since_skips_scorer_only_commits(repo: Repo) -> None:
    pinned = repo.tree()
    first = repo.change("crates/render.rs", "fn b() {}\n")
    repo.change(SCORER, "fn score() {}\n")
    repo.change("README.md", "docs\n")
    second = repo.change("crates/render.rs", "fn c() {}\n")
    assert ca.renderer_commits_since(pinned, rev="main", repo=repo.root) == [second, first]


def test_renderer_commits_since_the_current_tree_is_empty(repo: Repo) -> None:
    repo.change("crates/render.rs", "fn b() {}\n")
    repo.change("README.md", "docs\n")
    assert ca.renderer_commits_since(repo.tree(), rev="main", repo=repo.root) == []


def test_renderer_commits_since_counts_a_merge_once(repo: Repo) -> None:
    pinned = repo.tree()
    repo.git("checkout", "-q", "-b", "side")
    repo.change("crates/render.rs", "fn b() {}\n")
    repo.change("crates/render.rs", "fn c() {}\n")
    repo.git("checkout", "-q", "main")
    repo.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
    merge = repo.git("rev-parse", "HEAD")
    assert ca.renderer_commits_since(pinned, rev="main", repo=repo.root) == [merge]


def test_renderer_commits_since_an_unknown_tree_is_none(repo: Repo) -> None:
    assert ca.renderer_commits_since("0" * 40, rev="main", repo=repo.root) is None
    assert ca.renderer_commits_since(repo.tree(), rev="nope", repo=repo.root) is None
