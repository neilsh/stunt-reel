"""Offline tests for `mise run agreement` with renders, git and gh stubbed (#908)."""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from functools import reduce
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from render_helpers import flip_byte, rewrite_store, write_store

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_agreement as cli  # noqa: E402

from stunt_reel import class_agreement as ca  # noqa: E402
from stunt_reel.parity_artifacts import RenderAdapter, Report, StoredFrame, write_report  # noqa: E402

if TYPE_CHECKING:
    from collections.abc import Sequence

GPU = RenderAdapter("NVIDIA GeForce RTX 4070 Laptop GPU", "hardware")
LAVAPIPE = RenderAdapter("llvmpipe (LLVM 20.1.2, 256 bits)", "cpu")
TREE = "9" * 40
TICKS = (10, 20, 30)
FILMS = ("ctry", "intro")
DAY = dt.date(2026, 11, 21)
DRIVERS = ("610.88", "25.2.8-0ubuntu0.24.04.5")


def write_arm(
    root: Path,
    adapter: RenderAdapter,
    *,
    ssim: float = 0.9,
    flips: dict[int, list[int]] | None = None,
    ticks: tuple[int, ...] = TICKS,
    films: Sequence[str] = FILMS,
    crates: str = TREE,
) -> Path:
    """A root laid out as ``build/parity``: each film's store, its index plane flipped at *flips*."""
    flips = flips or {}
    for film in films:
        source = root / "source" / film
        write_store(source, ticks)
        rewrite_store(
            source,
            root / "ours" / f"{film}_current",
            lambda tick, frame: StoredFrame(
                indices=reduce(flip_byte, flips.get(tick, []), frame.indices),
                layers=frame.layers,
                palette=frame.palette,
            ),
        )
        path = root / "report" / f"{film}_current" / "report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        report = Report(
            per_frame=(),
            mean_ssim_scored=ssim,
            mean_iou_scored=0.5,
            scored_frames=1,
            frames=1,
            reference_frames=1,
            adapter=adapter,
            crates=crates,
        )
        write_report(path, report)
    return root


@dataclass
class Fake:
    """Records every command and gh call; renders arms on request."""

    repo: Path
    exits: dict[str, int] = field(default_factory=dict)
    outputs: dict[str, str | None] = field(default_factory=dict)
    calls: list[list[str]] = field(default_factory=list)
    gh_calls: list[tuple[str, ...]] = field(default_factory=list)
    gh_pages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    running: bool = False
    commits: list[str] | None = field(default_factory=list)
    lavapipe_flips: dict[int, list[int]] = field(default_factory=dict)
    lavapipe_ticks: tuple[int, ...] = TICKS

    def run(self, argv: Sequence[str], cwd: Path) -> int:
        command = " ".join(argv)
        self.calls.append(list(argv))
        if command.startswith("git worktree add"):
            Path(argv[-2]).mkdir(parents=True)
        parity = cwd / cli.PARITY_DIR
        if command == cli.LAVAPIPE_COMMAND:
            write_arm(
                parity, LAVAPIPE, ssim=0.9, flips=self.lavapipe_flips, ticks=self.lavapipe_ticks
            )
        elif command == "mise run parity":
            for part in ("ours", "report", "source"):
                shutil.rmtree(parity / part, ignore_errors=True)
            write_arm(parity, GPU)
        return self.exits.get(command, 0)

    def output(self, argv: Sequence[str], _cwd: Path) -> str | None:
        command = " ".join(argv)
        if command in self.outputs:
            return self.outputs[command]
        if command == "git rev-parse HEAD:crates":
            return TREE
        if command.startswith("git status"):
            return " M research/parity/expected/agreement.toml"
        if command.startswith("nvidia-smi"):
            return DRIVERS[0]
        if command.startswith("dpkg-query"):
            return DRIVERS[1]
        return None

    def gh(self, *args: str) -> Any:
        self.gh_calls.append(args)
        if args[0] == "-X":
            return {"number": 900, "html_url": "https://example.invalid/pull/1"}
        path = args[0].split("?")[0]
        return self.gh_pages.get(path, [])

    def tools(self) -> cli.Tools:
        return cli.Tools(
            run=self.run,
            output=self.output,
            gh=self.gh,
            running=lambda: self.running,
            commits=lambda _tree, _repo: self.commits,
            today=lambda: DAY,
            films=lambda _repo: FILMS,
        )


def pin_baseline(repo: Path) -> None:
    """Writes a pinned agreement with no residue on either film."""
    films = {film: ca.FilmAgreement(film, len(TICKS), 0, 0.0, 0, TICKS[0], {}) for film in FILMS}
    pinned = ca.Agreement(TREE, DAY, GPU.name, DRIVERS[0], LAVAPIPE.name, DRIVERS[1], films)
    path = repo / ca.AGREEMENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ca.format_agreement(pinned, FILMS), encoding="utf-8")


@pytest.fixture
def fake(tmp_path: Path) -> Fake:
    repo = tmp_path / "repo"
    repo.mkdir()
    return Fake(repo)


def test_measure_prints_flags_and_gaps(
    fake: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_baseline(fake.repo)
    gpu = write_arm(tmp_path / "gpu", GPU, ssim=0.9)
    lav = write_arm(tmp_path / "lav", LAVAPIPE, ssim=0.8, flips={20: [0, 1, 2, 3]})
    code, result = cli.run_measure(fake.repo, gpu, lav, DRIVERS, fake.tools())
    assert code == 0
    assert result.agreement is not None
    assert result.agreement.films["ctry"].differing_ticks == 1
    out = capsys.readouterr().out
    assert "+0.1000000" in out
    assert "flag: Agreement: ctry mean" in out
    assert "flag: Agreement: ctry ssim gap" in out
    assert (fake.repo / cli.STATE_DIR / "measured.toml").is_file()


def test_measure_fails_on_other_tick_sets_and_keeps_nothing(
    fake: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gpu = write_arm(tmp_path / "gpu", GPU)
    lav = write_arm(tmp_path / "lav", LAVAPIPE, ticks=(10, 20))
    code, result = cli.run_measure(fake.repo, gpu, lav, DRIVERS, fake.tools())
    assert (code, result.agreement) == (1, None)
    assert "tick sets differ" in capsys.readouterr().err
    assert not (fake.repo / cli.STATE_DIR / "measured.toml").exists()


def test_measure_refuses_reports_of_another_tree(fake: Fake, tmp_path: Path) -> None:
    gpu = write_arm(tmp_path / "gpu", GPU)
    lav = write_arm(tmp_path / "lav", LAVAPIPE, crates="8" * 40)
    assert cli.run_measure(fake.repo, gpu, lav, DRIVERS, fake.tools())[0] == 1


def test_measure_refuses_a_gpu_root_drawn_on_lavapipe(fake: Fake, tmp_path: Path) -> None:
    gpu = write_arm(tmp_path / "gpu", LAVAPIPE)
    lav = write_arm(tmp_path / "lav", LAVAPIPE)
    assert cli.run_measure(fake.repo, gpu, lav, DRIVERS, fake.tools())[0] == 1


def measured(fake: Fake, tmp_path: Path, **flips: Any) -> None:
    gpu = write_arm(tmp_path / "gpu", GPU, ssim=0.8)
    lav = write_arm(tmp_path / "lav", LAVAPIPE, ssim=0.8, **flips)
    assert cli.run_measure(fake.repo, gpu, lav, DRIVERS, fake.tools())[0] == 0


def test_pin_refuses_flags_without_accept(
    fake: Fake, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pin_baseline(fake.repo)
    before = (fake.repo / ca.AGREEMENT_FILE).read_text()
    measured(fake, tmp_path, flips={20: [0, 1, 2, 3]})
    assert cli.run_pin(fake.repo, None, fake.tools()) == 1
    assert "--accept" in capsys.readouterr().err
    assert (fake.repo / ca.AGREEMENT_FILE).read_text() == before
    assert fake.calls == []


def test_pin_refuses_a_first_baseline_without_accept(fake: Fake, tmp_path: Path) -> None:
    measured(fake, tmp_path)
    assert cli.run_pin(fake.repo, None, fake.tools()) == 1
    assert not (fake.repo / ca.AGREEMENT_FILE).exists()


def test_pin_with_accept_records_reason_and_repins_gpu(fake: Fake, tmp_path: Path) -> None:
    pin_baseline(fake.repo)
    measured(fake, tmp_path, flips={20: [0, 1, 2, 3]})
    assert cli.run_pin(fake.repo, "new driver", fake.tools()) == 0
    pinned = ca.read_agreement(fake.repo / ca.AGREEMENT_FILE)
    assert pinned is not None
    assert pinned.accepted == "new driver"
    assert pinned.films["ctry"].differing_ticks == 1
    commands = [" ".join(call) for call in fake.calls]
    assert commands[0] == "mise run parity-repin -- --class gpu"
    assert "git switch -C chore/agreement-9999999" in commands
    assert any(
        command.startswith("git add -- research/parity/expected/agreement.toml")
        for command in commands
    )
    assert any(call[:3] == ("-X", "POST", "repos/{owner}/{repo}/pulls") for call in fake.gh_calls)


def test_pin_refuses_another_crates_tree(fake: Fake, tmp_path: Path) -> None:
    pin_baseline(fake.repo)
    measured(fake, tmp_path)
    fake.outputs["git rev-parse HEAD:crates"] = "7" * 40
    assert cli.run_pin(fake.repo, "x", fake.tools()) == 1
    assert fake.calls == []


def test_pin_writes_nothing_when_the_repin_fails(fake: Fake, tmp_path: Path) -> None:
    pin_baseline(fake.repo)
    before = (fake.repo / ca.AGREEMENT_FILE).read_text()
    measured(fake, tmp_path, flips={20: [0, 1, 2, 3]})
    fake.exits["mise run parity-repin -- --class gpu"] = 1
    assert cli.run_pin(fake.repo, "x", fake.tools()) == 1
    assert (fake.repo / ca.AGREEMENT_FILE).read_text() == before


def batch(fake: Fake, *, if_due: bool = False, post: bool = False) -> int:
    return cli.run_batch(
        fake.repo,
        if_due=if_due,
        post_result=post,
        lavapipe_command=cli.LAVAPIPE_COMMAND.split(),
        lavapipe_driver_command=cli.LAVAPIPE_DRIVER_COMMAND.split(),
        tools=fake.tools(),
    )


def worktree(fake: Fake) -> Path:
    return fake.repo / cli.WORKTREE


def test_batch_runs_lavapipe_before_gpu_and_pins_with_no_flags(fake: Fake) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    assert batch(fake) == 0
    commands = [" ".join(call) for call in fake.calls]
    assert commands.index(cli.LAVAPIPE_COMMAND) < commands.index("mise run parity")
    assert "mise run parity-repin -- --class gpu" in commands
    assert (worktree(fake) / cli.STATE_DIR / "lavapipe" / "report" / "ctry_current").is_dir()


def test_batch_with_flags_pins_nothing(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.lavapipe_flips = {20: [0, 1, 2, 3]}
    assert batch(fake) == 0
    assert "mise run parity-repin -- --class gpu" not in [" ".join(c) for c in fake.calls]
    assert "pin --accept REASON" in capsys.readouterr().out


def test_batch_makes_the_worktree_when_absent(fake: Fake) -> None:
    assert batch(fake) == 0
    assert fake.calls[1][:4] == ["git", "worktree", "add", "--detach"]


def test_batch_if_due_skips_when_not_due(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.commits = []
    assert batch(fake, if_due=True) == 0
    assert "not due" in capsys.readouterr().out
    assert cli.LAVAPIPE_COMMAND not in [" ".join(c) for c in fake.calls]


def test_batch_if_due_runs_when_due(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.commits = ["c"] * 5
    assert batch(fake, if_due=True) == 0
    assert "agreement batch due: 5 renderer commits" in capsys.readouterr().out


def test_batch_skips_while_stuntreel_runs(fake: Fake, capsys: pytest.CaptureFixture[str]) -> None:
    fake.running = True
    assert batch(fake, if_due=True) == 0
    assert "stuntreel process is running" in capsys.readouterr().out
    assert fake.calls == []


def test_batch_pins_nothing_when_tick_sets_differ(fake: Fake) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.lavapipe_ticks = (10, 20)
    assert batch(fake) == 1
    assert "mise run parity-repin -- --class gpu" not in [" ".join(c) for c in fake.calls]


def test_batch_measures_nothing_when_an_arm_fails(fake: Fake) -> None:
    worktree(fake).mkdir(parents=True)
    fake.exits["mise run parity"] = 1
    assert batch(fake) == 1
    assert not (worktree(fake) / cli.STATE_DIR / "measured.toml").exists()


def test_batch_measures_nothing_without_a_driver_version(fake: Fake) -> None:
    worktree(fake).mkdir(parents=True)
    fake.outputs[" ".join(cli.GPU_DRIVER_COMMAND)] = None
    assert batch(fake) == 1


ISSUES = "repos/{owner}/{repo}/issues"


def flagged() -> tuple[ca.Agreement, list[ca.Flag]]:
    films = {"ctry": ca.FilmAgreement("ctry", 3, 1, 2.0, 1600, 20, {20: 1600})}
    agreement = ca.Agreement(TREE, DAY, GPU.name, DRIVERS[0], LAVAPIPE.name, DRIVERS[1], films)
    return agreement, [ca.Flag("ctry", "ticks: 1 rose by over 1000 pixels", (20,))]


def posts(fake: Fake) -> list[tuple[str, ...]]:
    return [call for call in fake.gh_calls if call[0] == "-X"]


def test_post_comments_once_per_tree(fake: Fake) -> None:
    agreement, _ = flagged()
    fake.gh_pages[ISSUES] = [{"number": 7, "title": cli.STANDING_TITLE}]
    assert cli.post(agreement, {}, [], "pinned", fake.tools()) == 0
    assert [call[2] for call in posts(fake)] == [f"{ISSUES}/7/comments"]
    fake.gh_calls.clear()
    fake.gh_pages[f"{ISSUES}/7/comments"] = [{"body": f"Class agreement on crates `{TREE}`"}]
    assert cli.post(agreement, {}, [], "pinned", fake.tools()) == 0
    assert posts(fake) == []


def test_post_files_an_uncovered_flag_and_opens_the_standing_issue(fake: Fake) -> None:
    agreement, found = flagged()
    assert cli.post(agreement, {}, found, "not pinned", fake.tools()) == 0
    titles = [arg for call in posts(fake) for arg in call if arg.startswith("title=")]
    assert titles == [f"title={cli.STANDING_TITLE}", "title=Agreement: ctry ticks 20-20"]


def test_post_skips_flag_an_open_issue_covers(fake: Fake) -> None:
    agreement, found = flagged()
    fake.gh_pages[ISSUES] = [
        {"number": 7, "title": cli.STANDING_TITLE},
        {"number": 8, "title": "Agreement: ctry ticks 15-25"},
        {"number": 9, "title": "Agreement: intro ticks 20-20"},
        {"number": 10, "title": "Agreement: ctry ticks 1-5", "pull_request": {}},
    ]
    assert cli.post(agreement, {}, found, "not pinned", fake.tools()) == 0
    assert [call[2] for call in posts(fake)] == [f"{ISSUES}/7/comments"]


@pytest.mark.parametrize(
    ("title", "is_covered"),
    [
        ("Agreement: ctry ticks 30-40", True),
        ("Agreement: ctry ticks 41-50", False),
        ("Agreement: ctry ticks 1-9", False),
        ("Agreement: intro ticks 10-40", False),
    ],
)
def test_covered_needs_the_film_and_an_overlapping_range(title: str, is_covered: bool) -> None:
    flag = ca.Flag("ctry", "ticks", (10, 40))
    assert cli.covered(flag, [{"title": title}]) is is_covered


def test_covered_mean_and_gap_need_the_same_title() -> None:
    flag = ca.Flag("ctry", "mean: 1 to 3")
    assert cli.covered(flag, [{"title": "Agreement: ctry mean"}])
    assert not cli.covered(flag, [{"title": "Agreement: ctry ssim gap"}])


def test_a_failed_push_keeps_the_commit_and_opens_no_pull(fake: Fake, tmp_path: Path) -> None:
    pin_baseline(fake.repo)
    measured(fake, tmp_path, flips={20: [0, 1, 2, 3]})
    fake.exits["git push -u origin chore/agreement-9999999"] = 1
    assert cli.run_pin(fake.repo, "x", fake.tools()) == 1
    assert fake.calls[-1][:2] == ["git", "push"]
    assert not any(call[0] == "-X" for call in fake.gh_calls)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "-C", str(repo), "-c", "user.name=T", "-c", "user.email=t@example.com",  # noqa: S607
         "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={repo / 'no-hooks'}", *args],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


def test_a_failed_first_commit_restores_the_files_in_real_git(fake: Fake, tmp_path: Path) -> None:
    repo = fake.repo
    _git(repo, "init", "-q")
    (repo / "crates").mkdir()
    (repo / "crates" / "a.rs").write_text("fn a() {}\n")
    gpu = repo / cli.GPU_FILE
    gpu.parent.mkdir(parents=True)
    gpu.write_text("before\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    tree = _git(repo, "rev-parse", "HEAD:crates")
    gpu_arm = write_arm(tmp_path / "gpu", GPU, crates=tree)
    lav_arm = write_arm(tmp_path / "lav", LAVAPIPE, crates=tree)
    assert cli.run_measure(repo, gpu_arm, lav_arm, DRIVERS, fake.tools())[0] == 0

    def run(argv: Sequence[str], cwd: Path) -> int:
        if argv[0] == "mise":
            gpu.write_text("after\n")
            return 0
        if argv[:2] == ["git", "commit"]:
            return 1
        return cli._run([*argv[:1], "-c", f"core.hooksPath={repo / 'no-hooks'}", *argv[1:]], cwd)

    tools = cli.Tools(run=run, gh=fake.gh, today=lambda: DAY, films=lambda _repo: FILMS)
    assert cli.run_pin(repo, "first baseline", tools) == 1
    assert gpu.read_text() == "before\n"
    assert not (repo / ca.AGREEMENT_FILE).exists()
    assert _git(repo, "status", "--porcelain", "--", "research") == ""


def test_batch_if_due_skips_a_tree_already_measured(
    fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.lavapipe_flips = {20: [0, 1, 2, 3]}
    fake.commits = ["c"] * 5
    assert batch(fake, if_due=True) == 0
    fake.calls.clear()
    assert batch(fake, if_due=True) == 0
    assert "already measured" in capsys.readouterr().out
    assert cli.LAVAPIPE_COMMAND not in [" ".join(c) for c in fake.calls]


def test_batch_if_due_skips_a_tree_whose_pin_awaits_merge(
    fake: Fake, capsys: pytest.CaptureFixture[str]
) -> None:
    worktree(fake).mkdir(parents=True)
    pin_baseline(worktree(fake))
    fake.commits = ["c"] * 5
    fake.outputs["git ls-remote --heads origin chore/agreement-9999999"] = "abc refs/heads/x"
    assert batch(fake, if_due=True) == 0
    assert "awaits its merge" in capsys.readouterr().out


def test_a_failed_measurement_is_posted(fake: Fake) -> None:
    worktree(fake).mkdir(parents=True)
    fake.lavapipe_ticks = (10, 20)
    fake.gh_pages[ISSUES] = [{"number": 7, "title": cli.STANDING_TITLE}]
    assert batch(fake, post=True) == 1
    (comment,) = posts(fake)
    assert comment[2] == f"{ISSUES}/7/comments"
    assert "tick sets differ" in comment[-1]


def test_a_malformed_agreement_file_exits_2(
    fake: Fake, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "REPO_ROOT", fake.repo)
    measured_dir = fake.repo / cli.STATE_DIR
    measured_dir.mkdir(parents=True)
    (measured_dir / "measured.toml").write_text("[ctry]\nticks = 1\n", encoding="utf-8")
    (measured_dir / "gaps.json").write_text("{}", encoding="utf-8")
    assert cli.main(["pin"], fake.tools()) == 2
    assert "not an agreement file" in capsys.readouterr().err
