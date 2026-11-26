"""The branch's pins and dates pass `pr_lint`'s checks, so CI holds every pull request to them.

`pin_failures` and `date_failures` read a working tree, which a coordinator never checks out;
this documentation test runs them on the checkout CI built, against the gate's base (#1049).
On a pull request that checkout is GitHub's merge commit, so pins are held to the head's
`crates` tree (`HEAD^2:crates`), which a later `crates/` change on main leaves alone; dates are
held to the runner's day, UTC in CI. On a push to main the branch equals its base, so nothing
changed and nothing fails.
"""

from __future__ import annotations

import os
import subprocess

import gate
import pr_lint
import pytest

from stunt_reel.dataroot import REPO_ROOT

pytestmark = pytest.mark.docs


def _pull_request_head_crates() -> str | None:
    """The pull request head's ``crates`` tree when CI built a merge commit, else ``None``."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    done = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "HEAD^2:crates"],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tree = done.stdout.strip()
    return tree if done.returncode == 0 and tree else None


def test_this_branchs_expected_pins_and_dates_pass_pr_lint() -> None:
    try:
        found = [
            *pr_lint.pin_failures(REPO_ROOT, tree=_pull_request_head_crates()),
            *pr_lint.date_failures(REPO_ROOT),
        ]
    except gate.ChangedPathsError as error:
        pytest.skip(f"git cannot give the branch's changes: {error}")
    assert found == [], "\n".join(found)
