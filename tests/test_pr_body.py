"""The one `Fixes`/`Closes`/`Part of #N` pattern `pr_lint` and `merge_bar` share (#983)."""

from __future__ import annotations

from stunt_reel.pr_body import issue_links


def test_each_closing_keyword_links_its_issue() -> None:
    for keyword in ("Fixes", "Closes", "Part of"):
        assert [match.group(1) for match in issue_links(f"{keyword} #863")] == ["863"]


def test_a_body_may_name_several_issues() -> None:
    body = "Part of #12\n\nFixes #863"
    assert [match.group(0) for match in issue_links(body)] == ["Part of #12", "Fixes #863"]


def test_a_link_names_one_issue_not_its_prefix() -> None:
    assert [match.group(1) for match in issue_links("Fixes #8630")] == ["8630"]


def test_a_body_with_no_closing_keyword_links_nothing() -> None:
    assert issue_links("Adds the task. Resolves #5.") == []
