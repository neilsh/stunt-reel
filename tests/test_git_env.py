"""``isolated_env`` keeps a git command on the repository it names."""

from __future__ import annotations

import shutil

import pytest

from stunt_reel.git_env import COMMAND_SCOPE, git_location_vars, isolated_env


@pytest.fixture
def caller_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The variables a hook in another checkout leaves set, plus one git does not list."""
    monkeypatch.setenv("GIT_DIR", "/caller/.git")
    monkeypatch.setenv("GIT_WORK_TREE", "/caller")
    monkeypatch.setenv("GIT_COMMON_DIR", "/caller/.git")
    monkeypatch.setenv("GIT_INDEX_FILE", "/caller/.git/next-index.lock")
    monkeypatch.setenv("GIT_ASKPASS", "askpass")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'safe.directory'='/caller'")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "1")


@pytest.mark.usefixtures("caller_env")
def test_the_caller_repository_and_index_are_dropped() -> None:
    env = isolated_env(keep_index=False)
    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"} & env.keys()
    assert env["GIT_ASKPASS"] == "askpass"
    assert env["GIT_CONFIG_PARAMETERS"] == "'safe.directory'='/caller'"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_NO_REPLACE_OBJECTS"] == "1"


@pytest.mark.usefixtures("caller_env")
def test_keep_index_keeps_only_the_index() -> None:
    env = isolated_env(keep_index=True)
    assert not {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"} & env.keys()
    assert env["GIT_INDEX_FILE"] == "/caller/.git/next-index.lock"


def test_the_list_is_the_one_git_reports() -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    assert {"GIT_CONFIG", "GIT_OBJECT_DIRECTORY", "GIT_DIR"} <= git_location_vars()
    assert not COMMAND_SCOPE & git_location_vars()


def test_without_git_the_core_four_are_still_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    git_location_vars.cache_clear()
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    try:
        assert {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} <= (
            git_location_vars()
        )
    finally:
        git_location_vars.cache_clear()
