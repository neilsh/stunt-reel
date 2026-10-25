"""Shared pytest configuration: registers the TAC mock fixtures as a plugin."""

from __future__ import annotations

import pytest

pytest_plugins = ["tac_mock"]


def pytest_configure(config: pytest.Config) -> None:
    """Keep pytest's temporary root inside the checkout when the OS temp dir is unusable.

    A low-integrity Python -- a sandboxed process, or any binary carrying this
    checkout's integrity label -- cannot write the user's temp directory, so
    tempfile falls back to the working directory and every tmp_path lands in the
    checkout, where the nested-worktree walker mistakes its fake .git file for a
    worktree.  A per-checkout basetemp keeps temporary files out of that walk and
    out of the OS temp dir at once.
    """
    if config.option.basetemp is None:
        config.option.basetemp = str(config.rootpath / ".pytest_cache" / "basetemp")
