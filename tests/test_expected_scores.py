"""A film's score beside its committed expected score, and drift only when the two compare."""

from __future__ import annotations

import subprocess
from types import MappingProxyType
from typing import TYPE_CHECKING, get_args

import pytest

from stunt_reel import parity_layout
from stunt_reel.expected_scores import CLASS_KEYS, changed_since, comparison_line
from stunt_reel.parity_artifacts import AdapterClass, RenderAdapter, Report
from stunt_reel.references import (
    RENDERER_CLASSES,
    Builds,
    Expected,
    Reference,
    read_reference,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

GPU = RenderAdapter("NVIDIA GeForce RTX 4070", "hardware")
LAVAPIPE = RenderAdapter("llvmpipe (LLVM 19.1.7, 256 bits)", "cpu")
COMMIT = "740c6080aaaabbbbccccddddeeeeffff00001111"
#: The expected CTRY score on the GPU: every comparison line below reads against it.
ON_GPU = Expected(ssim=0.8986, iou=0.9897, commit=COMMIT, adapter=GPU.name)
HEAD = "      gpu expected ssim 0.8986000  iou 0.9897000"
#: The tail of a drift verdict against :data:`ON_GPU` with CTRY's noise.
SIGMA_ON_GPU = "noise_sigma 0.0003030 on NVIDIA GeForce RTX 4070"

#: Variables that point git at another repository, which ``changed_since`` must ignore.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _reference(
    expected: dict[str, Expected] | None = None,
    *,
    film: str = "ctry",
    noise_sigma: float | None = 0.000303,
) -> Reference:
    return Reference(
        film,
        f"vault-{film}",
        "0" * 64,
        Builds("patch3", "patch3"),
        expected=MappingProxyType({"gpu": ON_GPU} if expected is None else expected),
        noise_sigma=noise_sigma,
    )


def _report(ssim: float | None, adapter: RenderAdapter | None = GPU) -> Report:
    """A report scoring *ssim* on *adapter*; ``None`` scores no frame."""
    scored = 0 if ssim is None else 100
    return Report(
        per_frame=(),
        frames=scored,
        scored_frames=scored,
        mean_ssim_scored=ssim,
        mean_iou_scored=None if ssim is None else 0.98,
        adapter=adapter,
    )


def _unchanged(commit: str, reference: Reference) -> str | None:
    assert (commit, reference.film) == (COMMIT, "ctry")
    return None


def _never(_commit: str, _reference: Reference) -> str | None:
    raise AssertionError("an earlier reason already makes the scores not comparable")


def test_the_class_keys_map_every_adapter_class_to_a_renderer_class() -> None:
    assert set(CLASS_KEYS) == set(get_args(AdapterClass))
    assert set(CLASS_KEYS.values()) == set(RENDERER_CLASSES)


def test_a_report_without_an_adapter_asks_for_a_re_render() -> None:
    assert (
        comparison_line(_reference(), _report(0.8987, adapter=None), changed=_never)
        == "      no adapter in the report: re-render to compare"
    )


def test_a_class_without_an_expected_score_asks_for_one() -> None:
    assert (
        comparison_line(_reference(), _report(0.8987, adapter=LAVAPIPE), changed=_never)
        == "      no expected score for lavapipe yet: add it"
    )


def test_a_cpu_report_reads_the_lavapipe_entry() -> None:
    on_cpu = Expected(ssim=0.75, iou=0.5, commit=COMMIT, adapter=LAVAPIPE.name)
    line = comparison_line(
        _reference({"gpu": ON_GPU, "lavapipe": on_cpu}),
        _report(0.75, adapter=LAVAPIPE),
        changed=_unchanged,
    )
    assert line == (
        "      lavapipe expected ssim 0.7500000  iou 0.5000000  delta +0.0000000  no drift"
    )


def test_a_report_that_scored_no_frame_is_not_compared() -> None:
    assert (
        comparison_line(_reference(), _report(None), changed=_never)
        == f"{HEAD}  delta n/a  not comparable: no frame scored"
    )


def test_another_adapter_of_the_same_class_is_not_compared() -> None:
    other = RenderAdapter("AMD Radeon(TM) Graphics", "hardware")
    assert (
        comparison_line(_reference(), _report(0.8987, adapter=other), changed=_never)
        == f"{HEAD}  delta +0.0001000  not comparable: other adapter "
        "(expected on NVIDIA GeForce RTX 4070)"
    )


@pytest.mark.parametrize("flag", ["--retime", "--reuse"])
def test_a_rescored_tree_is_not_compared(flag: str) -> None:
    assert (
        comparison_line(_reference(), _report(0.8987), rescored=flag, changed=_never)
        == f"{HEAD}  delta +0.0001000  not comparable: scored with {flag}"
    )


def test_a_change_since_the_measured_commit_is_not_compared() -> None:
    asked: list[tuple[str, Reference]] = []

    def changed(commit: str, reference: Reference) -> str | None:
        asked.append((commit, reference))
        return "crates/ changed since 740c608"

    reference = _reference()
    assert (
        comparison_line(reference, _report(0.8987), changed=changed)
        == f"{HEAD}  delta +0.0001000  not comparable: crates/ changed since 740c608"
    )
    assert asked == [(COMMIT, reference)]


@pytest.mark.parametrize(
    ("report", "rescored", "reason"),
    [
        (_report(None, RenderAdapter("other", "hardware")), "--reuse", "no frame scored"),
        (
            _report(0.8987, RenderAdapter("other", "hardware")),
            "--reuse",
            "other adapter (expected on NVIDIA GeForce RTX 4070)",
        ),
    ],
)
def test_the_first_reason_that_applies_is_the_one_printed(
    report: Report, rescored: str, reason: str
) -> None:
    line = comparison_line(_reference(), report, rescored=rescored, changed=_never)
    assert line.endswith(f"  not comparable: {reason}")


def test_a_film_without_noise_sigma_prints_its_delta_unjudged() -> None:
    line = comparison_line(
        _reference(film="intro", noise_sigma=None), _report(0.8987), changed=lambda *_a: None
    )
    assert line == f"{HEAD}  delta +0.0001000  drift not judged: intro has no noise_sigma"


@pytest.mark.parametrize(
    ("ssim", "line"),
    [
        (0.8980, f"{HEAD}  delta -0.0006000  DRIFT: |delta| 0.0006000 > {SIGMA_ON_GPU}"),
        (0.8991, f"{HEAD}  delta +0.0005000  DRIFT: |delta| 0.0005000 > {SIGMA_ON_GPU}"),
        # At six decimals this read |delta| 0.000303 > noise_sigma 0.000303.
        (0.8989031, f"{HEAD}  delta +0.0003031  DRIFT: |delta| 0.0003031 > {SIGMA_ON_GPU}"),
        (0.8987, f"{HEAD}  delta +0.0001000  no drift"),
        (0.8984, f"{HEAD}  delta -0.0002000  no drift"),
    ],
)
def test_drift_is_a_delta_beyond_noise_sigma(ssim: float, line: str) -> None:
    assert comparison_line(_reference(), _report(ssim), changed=_unchanged) == line


def test_a_delta_of_exactly_noise_sigma_is_no_drift() -> None:
    expected = Expected(ssim=0.5, iou=0.5, commit=COMMIT, adapter=GPU.name)
    line = comparison_line(
        _reference({"gpu": expected}, noise_sigma=0.25), _report(0.75), changed=_unchanged
    )
    assert line == "      gpu expected ssim 0.5000000  iou 0.5000000  delta +0.2500000  no drift"


# changed_since, against a throwaway repository.

SHA_CTRY = "a" * 64
SHA_INTRO = "b" * 64
ALL_CTRY = "c" * 64


def _rows(ctry: str = SHA_CTRY, intro: str = SHA_INTRO, all_ctry: str = ALL_CTRY) -> str:
    return (
        f'[ctry]\nfilm = "vault-ctry"\nsha256 = "{ctry}"\nall_sha256 = "{all_ctry}"\n'
        f'[intro]\nfilm = "vault-intro"\nsha256 = "{intro}"\n'
    )


class Repo:
    """A scratch repository holding ``crates/a.rs`` and a ``references.toml``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        hooks = root.parent / "no-hooks"
        hooks.mkdir()
        # No user identity, signing or hooks from this machine's configuration.
        self._config = [
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}",
        ]  # fmt: skip
        self.git("init", "-q")
        self.write("crates/a.rs", "fn a() {}\n")
        self.write(".gitignore", "*.log\n")
        self.write(parity_layout.REFERENCES_FILE.as_posix(), _rows())
        self.first = self.commit()

    def git(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(self.root), *self._config, *args],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def commit(self) -> str:
        self.git("add", "-A")
        self.git("commit", "-qm", "change")
        return self.git("rev-parse", "HEAD")

    def changed(self, commit: str | None = None, film: str = "ctry") -> str | None:
        return changed_since(commit or self.first, read_reference(self.root, film), repo=self.root)


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


def test_nothing_changed_since_the_commit(repo: Repo) -> None:
    repo.write("python/outside.py", "x = 1\n")  # a change outside crates/ does not count
    repo.write("crates/build.log", "ignored\n")  # nor an ignored file under it
    assert repo.changed() is None
    repo.commit()
    assert repo.changed() is None


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda r: r.write("crates/a.rs", "fn a() { 1 }\n"), id="uncommitted"),
        pytest.param(lambda r: r.write("crates/b.rs", "fn b() {}\n"), id="untracked"),
        pytest.param(lambda r: (r.root / "crates" / "a.rs").unlink(), id="deleted"),
        pytest.param(
            lambda r: (r.write("crates/a.rs", "fn a() { 2 }\n"), r.commit()), id="committed"
        ),
    ],
)
def test_a_change_under_crates_is_named(repo: Repo, edit: Callable[[Repo], object]) -> None:
    edit(repo)
    assert repo.changed() == f"crates/ changed since {repo.first[:7]}"


@pytest.mark.parametrize(
    "rows",
    [_rows(ctry="d" * 64), _rows(all_ctry="d" * 64)],
    ids=["sha256", "all_sha256"],
)
def test_a_committed_change_to_the_films_pin_is_named(repo: Repo, rows: str) -> None:
    repo.write(parity_layout.REFERENCES_FILE.as_posix(), rows)
    repo.commit()
    assert repo.changed() == f"reference pin changed since {repo.first[:7]}"


def test_another_films_pin_does_not_count(repo: Repo) -> None:
    repo.write(parity_layout.REFERENCES_FILE.as_posix(), _rows(intro="d" * 64))
    repo.commit()
    assert repo.changed() is None
    assert repo.changed(film="intro") == f"reference pin changed since {repo.first[:7]}"


def test_a_row_the_commit_lacks_is_a_pin_change(repo: Repo) -> None:
    rows = _rows() + '[later]\nfilm = "vault-later"\nsha256 = "' + "e" * 64 + '"\n'
    repo.write(parity_layout.REFERENCES_FILE.as_posix(), rows)
    repo.commit()
    assert repo.changed(film="later") == f"reference pin changed since {repo.first[:7]}"


def test_a_references_file_the_commit_lacks_is_a_pin_change(repo: Repo) -> None:
    (repo.root / parity_layout.REFERENCES_FILE).unlink()
    before = repo.commit()
    repo.write(parity_layout.REFERENCES_FILE.as_posix(), _rows())
    repo.commit()
    assert repo.changed(before) == f"reference pin changed since {before[:7]}"


#: The reason for :data:`COMMIT` when git cannot resolve it.
ABSENT = f"commit 740c608 is not in this clone: git fetch origin {COMMIT}"


def test_a_commit_this_clone_lacks_is_named_with_the_fetch_that_restores_it(repo: Repo) -> None:
    assert (
        repo.changed("deadbee") == "commit deadbee is not in this clone: git fetch origin deadbee"
    )
    full = "0123456789" * 4
    assert repo.changed(full) == f"commit 0123456 is not in this clone: git fetch origin {full}"


def test_a_failing_git_reads_as_a_commit_this_clone_lacks(tmp_path: Path) -> None:
    # A directory that does not exist: an existing one under tmp_path may sit inside a checkout.
    assert changed_since(COMMIT, _reference(), repo=tmp_path / "missing") == ABSENT


def test_a_missing_git_reads_as_a_commit_this_clone_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_git(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise FileNotFoundError("git")

    monkeypatch.setattr("stunt_reel.expected_scores.subprocess.run", no_git)
    assert changed_since(COMMIT, _reference(), repo=tmp_path) == ABSENT


@pytest.mark.parametrize("variable", _GIT_LOCATION_ENV)
def test_git_variables_naming_another_repository_are_ignored(
    repo: Repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    other = tmp_path / "other"  # a repository without the measured commit, its files or index
    subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "init", "-q", str(other)],  # noqa: S607 - git from PATH
        capture_output=True,
        check=True,
    )
    elsewhere = {
        "GIT_DIR": other / ".git",
        "GIT_WORK_TREE": other,
        "GIT_INDEX_FILE": other / ".git" / "index",
        "GIT_COMMON_DIR": other / ".git",
    }
    monkeypatch.setenv(variable, str(elsewhere[variable]))
    assert repo.changed() is None
