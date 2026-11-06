"""The gate's lane map stays in step with its one step list (ADR 0016).

The gate is one plan of leaf tasks (ADR 0014) that runs as concurrent lanes (ADR 0016). These
checks hold the two together: a step added to `STEPS` without a lane must fail here, before the
gate refuses to start at run time, and a lane must never reorder or drop a step of its plan.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_commit_msg  # noqa: E402
import gate  # noqa: E402


def test_lane_map_covers_every_step_exactly_once() -> None:
    steps = [step for half in gate.STEPS.values() for step in half]
    assert len(steps) == len(set(steps)), "a step is listed twice in STEPS"
    assert sorted(gate.STEP_LANES) == sorted(steps), (
        "STEP_LANES must name every step, and only steps"
    )


def test_the_rust_and_python_halves_make_the_whole_plan() -> None:
    assert gate._plan("all") == [*gate.STEPS["rust"], *gate.STEPS["py"]]
    assert gate._plan("rust") == gate.STEPS["rust"]
    assert gate._plan("py") == gate.STEPS["py"]


def test_the_docs_half_shares_no_step_with_the_whole_plan() -> None:
    assert gate._plan("docs") == gate.STEPS["docs"]
    assert not set(gate._plan("docs")) & set(gate._plan("all"))


def test_lanes_keep_plan_order_and_drop_no_step() -> None:
    for half in ("all", "rust", "py", "docs"):
        plan = gate._plan(half)
        lanes = gate._lane_plan(plan)
        scheduled = [task for _, tasks in lanes for task in tasks]
        assert sorted(scheduled) == sorted(plan)
        for _, tasks in lanes:
            positions = [plan.index(task) for task in tasks]
            assert positions == sorted(positions), "a lane reordered its steps"


def test_the_gate_has_no_staged_half() -> None:
    """The commit hooks run through prek now (ADR 0026), not a plan of the gate's own."""
    with pytest.raises(SystemExit):
        gate.main(["staged"])


def _verdict(failed: list[str], half: str) -> str:
    return gate._verdict(failed, gate._plan(half), half, 43.0)


def test_a_passing_run_names_no_next_command() -> None:
    line = _verdict([], "all")
    assert line.startswith("[gate] PASS 9/9 steps")
    assert "re-run" not in line
    assert "fix:" not in line


def test_a_rust_failure_names_the_rust_rerun() -> None:
    line = _verdict(["test-rust"], "all")
    assert line.endswith("; re-run: mise run check-rust")
    assert "fix:" not in line


def test_a_python_failure_names_the_python_rerun() -> None:
    line = _verdict(["typecheck"], "all")
    assert line.endswith("; re-run: mise run check-py")


def test_a_mixed_failure_names_both_reruns() -> None:
    line = _verdict(["doc", "test-py"], "all")
    assert "re-run: mise run check-rust, mise run check-py" in line


def test_a_scoped_task_never_suggests_itself() -> None:
    assert "re-run" not in _verdict(["test-rust"], "rust")
    assert "re-run" not in _verdict(["test-py"], "py")


def test_a_step_in_neither_half_names_no_rerun() -> None:
    assert "re-run" not in _verdict(["not-a-step"], "all")


def test_scoped_tasks_are_the_mise_tasks_that_run_each_half() -> None:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    for half, scoped in gate.SCOPED_TASKS.items():
        assert tasks[scoped]["run"] == f"python python/scripts/gate.py {half}"


def test_fixable_steps_are_gate_steps_and_get_the_fix_hint() -> None:
    assert set(gate.STEP_LANES) >= gate.FIXABLE_STEPS
    for step in gate.FIXABLE_STEPS:
        assert "fix: mise run fix" in _verdict([step], "all")
    for step in set(gate.STEP_LANES) - gate.FIXABLE_STEPS:
        assert "fix:" not in _verdict([step], "all")


def test_fix_task_applies_what_the_fixable_steps_check() -> None:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    assert tasks[gate.FIX_TASK]["description"]
    commands = " | ".join(
        c if isinstance(c, str) else c.get("task", "") for c in tasks[gate.FIX_TASK]["run"]
    )
    assert "ruff check --fix" in commands
    assert "fmt-py" in commands
    assert "fmt-rust" in commands


def test_failure_tail_header_carries_fix_hint_only_for_fixable_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The output-tail header is printed by main alone, so exercise it there."""
    failed = {*gate.FIXABLE_STEPS, "test-rust"}

    def fake_step(_mise: str, task: str) -> tuple[int, str, float]:
        return (1 if task in failed else 0, f"{task} output\n", 0.0)

    monkeypatch.setattr(gate, "_mise", lambda: "mise")
    monkeypatch.setattr(gate, "_step", fake_step)
    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "gate.log")

    assert gate.main(["all", "--tail", "1"]) == 1
    output = capsys.readouterr().out
    for task in gate._plan("all"):
        if task not in failed:
            assert f"---- {task} output tail" not in output
            continue
        note = f" (fix: mise run {gate.FIX_TASK})" if task in gate.FIXABLE_STEPS else ""
        assert f"---- {task} output tail{note} ----" in output


def test_cargo_steps_share_a_lane_exactly_when_they_share_a_target_dir() -> None:
    """Cargo locks a target directory for a whole build: one lane per directory (ADR 0016)."""
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    target_dirs = {
        step: tasks[step].get("env", {}).get("CARGO_TARGET_DIR", "{{config_root}}/target")
        for step in gate.STEP_LANES
        if str(tasks[step].get("run", "")).startswith("cargo ")
        and "fmt" not in str(tasks[step]["run"])
    }
    assert {"lint-rust", "test-rust", "doc", "check-rust-matrix"} <= set(target_dirs)
    for step, target in target_dirs.items():
        for other, other_target in target_dirs.items():
            same_lane = gate.STEP_LANES[step] == gate.STEP_LANES[other]
            assert same_lane == (target == other_target), (step, other)


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("tests/fixtures/synthetic_pfont.bin", "other"),
        ("tests/fixtures/README.md", "other"),
        ("crates/stunt-core/src/lib.rs", "rust"),
        ("crates/stunt-core/README.md", "rust"),
        ("Cargo.lock", "rust"),
        ("deny.toml", "rust"),
        ("python/scripts/gate.py", "python"),
        ("uv.lock", "python"),
        ("pyproject.toml", "python"),
        ("research/formats/x.ksy", "docs"),
        ("AGENTS.md", "docs"),
        ("ä/ä.md", "docs"),
        ("mise.toml", "other"),
        (".github/workflows/ci.yml", "other"),
        ("tools/x/Cargo.toml", "other"),
    ],
)
def test_classify(path: str, category: str) -> None:
    assert gate.classify(path) == category


def test_docs_only_runs_the_docs_half() -> None:
    assert gate.scope_for(["a.md"], full_flag=False, ci=False).halves == ("docs",)


def test_rust_change_runs_rust_and_docs() -> None:
    assert gate.scope_for(["crates/a.rs"], full_flag=False, ci=False).halves == ("rust", "docs")


def test_python_change_needs_no_docs_half() -> None:
    assert gate.scope_for(["a.py", "b.md"], full_flag=False, ci=False).halves == ("py",)


@pytest.mark.parametrize(
    ("paths", "full_flag", "ci", "error", "reason"),
    [
        (["a.md"], True, False, "", "--full"),
        (["a.md"], False, True, "", "CI is set"),
        (["a.md", "mise.toml"], False, False, "", "unclassified path: mise.toml"),
        ([], False, False, "", "no changes against main"),
        (None, False, False, "no main", "changed paths unknown: no main"),
    ],
)
def test_full_gate_triggers(
    paths: list[str] | None, full_flag: bool, ci: bool, error: str, reason: str
) -> None:
    scope = gate.scope_for(paths, full_flag=full_flag, ci=ci, error=error)
    assert (scope.full, scope.halves, scope.reason) == (True, ("rust", "py"), reason)


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"CI": "true"}, True),
        ({"CI": "1"}, True),
        ({"CI": "false"}, False),
        ({"CI": "FALSE"}, False),
        ({"CI": "0"}, False),
        ({"CI": ""}, False),
    ],
)
def test_ci_requested(env: dict[str, str], expected: bool) -> None:
    assert gate.ci_requested(env) is expected


@pytest.mark.parametrize(
    ("halves", "line"),
    [
        (("rust", "py"), "mise run check passes."),
        (("docs",), "mise run check-docs passes; check-rust not run; check-py not run."),
        (("rust", "docs"), "mise run check-rust passes; check-docs passes; check-py not run."),
        (("py",), "mise run check-py passes; check-rust not run."),
        (("rust",), "mise run check-rust passes; check-py not run; check-docs not run."),
    ],
)
def test_gate_line(halves: tuple[str, ...], line: str) -> None:
    assert gate.gate_line(halves) == line
    assert check_commit_msg._is_gate_line(line)


def test_a_docs_failure_names_the_docs_rerun() -> None:
    assert "re-run: mise run check-docs" in _verdict(["test-py-docs"], "all")


def test_no_changes_names_the_base() -> None:
    assert (
        gate.scope_for([], full_flag=False, ci=False, base="HEAD").reason
        == "no changes against HEAD"
    )


def test_docs_step_requires_the_kaitai_compiler() -> None:
    assert gate.STEP_ENV["test-py-docs"]["STUNT_REQUIRE_KSC"] == "1"
    assert (
        gate.STEP_ENV["test-py-docs"]["PYTEST_ADDOPTS"]
        == gate.STEP_ENV["test-py"]["PYTEST_ADDOPTS"]
    )


@pytest.mark.parametrize(
    "module", ["test_doc_invariants.py", "test_formats_catalog.py", "test_schema_contract.py"]
)
def test_docs_marker_is_on_the_documentation_modules(module: str) -> None:
    assert "pytest.mark.docs" in (ROOT / "tests" / module).read_text(encoding="utf-8")


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(repo: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None, "git is not on PATH"
    subprocess.run(  # noqa: S603
        [git, *args], cwd=repo, env={**os.environ, **_GIT_ENV}, capture_output=True, check=True
    )


def _write(repo: Path, name: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name, encoding="utf-8")


def _feature_repo(tmp_path: Path, trunk: str = "main") -> Path:
    """A repository with one commit on *trunk* and a ``feat`` branch checked out."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", trunk)
    _write(repo, "base.md")
    _git(repo, "add", "base.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "switch", "-q", "-c", "feat")
    return repo


def test_changed_paths_lists_committed_staged_unstaged_and_untracked(tmp_path: Path) -> None:
    repo = _feature_repo(tmp_path)
    for name in ("committed.md", "staged.py", "untracked.ksy"):
        _write(repo, name)
    _git(repo, "add", "committed.md")
    _git(repo, "commit", "-qm", "work")
    _git(repo, "add", "staged.py")
    (repo / "base.md").write_text("edited", encoding="utf-8")

    assert sorted(gate.changed_paths(repo)) == [
        "base.md",
        "committed.md",
        "staged.py",
        "untracked.ksy",
    ]


def test_changed_paths_lists_only_an_untracked_file(tmp_path: Path) -> None:
    repo = _feature_repo(tmp_path)
    _write(repo, "new.md")

    assert gate.changed_paths(repo) == ["new.md"]


def test_changed_paths_lists_both_sides_of_a_rename(tmp_path: Path) -> None:
    repo = _feature_repo(tmp_path)
    _git(repo, "mv", "base.md", "base.py")
    _git(repo, "commit", "-qm", "rename")

    assert sorted(gate.changed_paths(repo)) == ["base.md", "base.py"]


def test_changed_paths_keeps_a_non_ascii_name(tmp_path: Path) -> None:
    repo = _feature_repo(tmp_path)
    _write(repo, "notes/ä.md")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "umlaut")

    assert gate.changed_paths(repo) == ["notes/ä.md"]


def test_changed_paths_without_main_raises(tmp_path: Path) -> None:
    repo = _feature_repo(tmp_path, trunk="trunk")

    with pytest.raises(gate.ChangedPathsError):
        gate.changed_paths(repo)


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    paths: list[str] | Exception,
    *args: str,
) -> tuple[list[str], str]:
    """Run ``gate.main`` with every step passing; return the steps it ran and what it printed."""
    ran: list[str] = []

    def step(_mise: str, task: str) -> tuple[int, str, float]:
        ran.append(task)
        return 0, "", 0.0

    def changed(_repo: Path, base: str = "main") -> list[str]:
        assert base == "main"
        if isinstance(paths, Exception):
            raise paths
        return paths

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "check.log")
    monkeypatch.setattr(gate, "_mise", lambda: "mise")
    monkeypatch.setattr(gate, "_step", step)
    monkeypatch.setattr(gate, "changed_paths", changed)
    assert gate.main(["all", *args]) == 0
    return ran, (tmp_path / "check.log").read_text(encoding="utf-8")


def test_a_documentation_change_runs_only_the_docs_half(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran, log = _run_main(monkeypatch, tmp_path, ["a.md", "b.md", "c.md", "d.ksy"])

    out = capsys.readouterr().out
    assert ran == ["test-py-docs"]
    assert "[gate] scope: docs; not run: check-rust, check-py" in out
    assert "[gate]   docs: a.md, b.md, c.md (+1 more)" in out
    assert "# scope: docs; not run: check-rust, check-py" in log
    assert out.rstrip().endswith(
        "[gate] gate line: mise run check-docs passes; check-rust not run; check-py not run."
    )


def test_unknown_changed_paths_run_the_full_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran, _ = _run_main(monkeypatch, tmp_path, gate.ChangedPathsError("no main"))

    out = capsys.readouterr().out
    assert sorted(ran) == sorted(gate._plan("all"))
    assert "[gate] scope: full (changed paths unknown: no main)" in out
    assert out.rstrip().endswith("[gate] gate line: mise run check passes.")


def test_full_flag_runs_the_full_gate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran, _ = _run_main(monkeypatch, tmp_path, ["a.md"], "--full")

    assert set(ran) == set(gate._plan("all"))
    assert "[gate] scope: full (--full)" in capsys.readouterr().out
