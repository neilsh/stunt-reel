"""One helper strips every git repository variable, for every script that runs git."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from stunt_reel import git_env

GIT = shutil.which("git")
KNOWN = {"GIT_DIR", "GIT_INDEX_FILE", "GIT_CONFIG", "GIT_OBJECT_DIRECTORY", "GIT_COMMON_DIR"}


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    git_env.local_env_vars.cache_clear()


def test_the_variables_are_the_ones_git_lists() -> None:
    if GIT is None:
        pytest.skip("git is not on PATH")
    assert KNOWN | {"GIT_WORK_TREE"} <= git_env.local_env_vars()


def test_clean_environ_drops_git_variables_and_keeps_the_rest() -> None:
    cleaned = git_env.clean_environ(
        {"GIT_DIR": "/x", "GIT_INDEX_FILE": "/i", "GIT_CONFIG_COUNT": "1", "GIT_ASKPASS": "a"}
    )
    assert cleaned == {"GIT_ASKPASS": "a"}


def test_clean_environ_defaults_to_the_process_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_INDEX_FILE", "/i")
    monkeypatch.setenv("GIT_ASKPASS", "a")
    cleaned = git_env.clean_environ()
    assert "GIT_INDEX_FILE" not in cleaned
    assert cleaned["GIT_ASKPASS"] == "a"


def test_keep_leaves_the_named_variable() -> None:
    environ = {"GIT_DIR": "/x", "GIT_INDEX_FILE": "/i"}
    assert git_env.clean_environ(environ, keep=["GIT_INDEX_FILE"]) == {"GIT_INDEX_FILE": "/i"}


def test_a_missing_git_still_strips_the_known_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert git_env.local_env_vars() >= KNOWN


def test_a_failing_git_still_strips_the_known_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 1, stdout="", stderr="boom")

    monkeypatch.setattr(shutil, "which", lambda _name: "git")
    monkeypatch.setattr(subprocess, "run", fail)
    assert git_env.local_env_vars() >= KNOWN


def test_an_unlaunchable_git_still_strips_the_known_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("no exec")

    monkeypatch.setattr(shutil, "which", lambda _name: "git")
    monkeypatch.setattr(subprocess, "run", fail)
    assert git_env.local_env_vars() >= KNOWN


def test_git_is_asked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    def run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess([], 0, stdout="GIT_DIR\nGIT_ODD\n", stderr="")

    monkeypatch.setattr(shutil, "which", lambda _name: "git")
    monkeypatch.setattr(subprocess, "run", run)
    assert "GIT_ODD" in git_env.local_env_vars()
    git_env.local_env_vars()
    assert len(calls) == 1
