"""The branch's pins and dates pass `pr_lint`'s checks, so CI holds every pull request to them.

`pin_failures` and `date_failures` read a working tree, which a coordinator never checks out;
this documentation test runs them on the checkout CI built, against the gate's base (#1049).
On a push to main the branch equals its base, so nothing changed and nothing fails.
"""

from __future__ import annotations

import gate
import pr_lint
import pytest

from stunt_reel.dataroot import REPO_ROOT

pytestmark = pytest.mark.docs


def test_this_branchs_expected_pins_and_dates_pass_pr_lint() -> None:
    try:
        found = [*pr_lint.pin_failures(REPO_ROOT), *pr_lint.date_failures(REPO_ROOT)]
    except gate.ChangedPathsError as error:
        pytest.skip(f"git cannot give the branch's changes: {error}")
    assert found == [], "\n".join(found)
