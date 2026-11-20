"""mise run claim-words: rule 5's over-broad words in a branch's added lines."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import claim_words
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "python" / "scripts" / "claim_words.py"
# The rename fixture builds its paths from this part, so this file names no document path of its
# own for test_code_cited_docs_exist to look up.
RESEARCH = "research"
TICK = "\x60"
TIERS = ("[Unknown]", "[Hypothesis]", "[Established]")

AGENTS = (
    "# Test Agents\n"
    "\n"
    "### Committing\n"
    "\n"
    f"5. Before a push that changes {TICK}research/{TICK}, {TICK}notes.md{TICK}, a fresh "
    "reviewer reads the diff and reports any claim broader than its evidence "
    f"({TICK}only{TICK}, {TICK}all{TICK}).\n"
    "\n"
    "### Other\n"
)


def _git(repo: Path, *args: str) -> str:
    """Run git args in repo with a fixed identity; return its stdout."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )
    return done.stdout


def _base(tmp_path: Path) -> Path:
    """A repository on main whose AGENTS.md states a synthetic rule 5."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "AGENTS.md").write_text(AGENTS, encoding="utf-8")
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-m", "test: base")
    return repo


def _claim(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the task's script in repo."""
    return subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.mark.docs
def test_agents_md_rule_5_lists_the_words_and_paths() -> None:
    words, paths = claim_words.rule_5(REPO_ROOT / "AGENTS.md")
    assert words == ("only", "all", "noise", "within", "equivalent")
    assert paths == (
        "research/",
        "NOTICE.md",
        "docs/howto/",
        "docs/*.md",
        "site/guides/",
        "site/reading.md",
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("research/formats/res.md", True),
        ("NOTICE.md", True),
        ("docs/howto/render-a-film.md", True),
        ("docs/development.md", True),
        ("docs/adr/0001-sod-tap-anchor-table.md", False),
        ("docs/agents/domain.md", False),
        ("site/guides/index.md", True),
        ("site/reading.md", True),
        ("README.md", False),
        ("python/scripts/claim_words.py", False),
        ("docs/development.txt", False),
        ("site/reading.txt", False),
    ],
)
def test_rule_5_paths(path: str, expected: bool) -> None:
    _words, patterns = claim_words.rule_5(REPO_ROOT / "AGENTS.md")
    assert claim_words.is_rule_5_path(path, patterns) is expected


def test_non_hits_are_whole_words() -> None:
    words = ("all", "only")
    assert claim_words.words_in("The overall allowance is small.", words) == ()
    assert claim_words.words_in("Only one line.", words) == ("only",)
    assert claim_words.words_in("They all agree.", words) == ("all",)


def test_nearest_tier_reads_the_line_then_the_paragraph() -> None:
    assert claim_words.nearest_tier(["Our only path. [Established]"], 0, TIERS) == "[Established]"
    paragraph = ["Claim. [Hypothesis]", "Our only path."]
    assert claim_words.nearest_tier(paragraph, 1, TIERS) == "[Hypothesis]"
    assert claim_words.nearest_tier(["[Hypothesis]", "", "Our only path."], 2, TIERS) is None
    nearest = ["[Unknown]", "Text. [Established]", "Our only path."]
    assert claim_words.nearest_tier(nearest, 2, TIERS) == "[Established]"


def test_lists_a_hit_with_its_line_and_tier_and_skips_a_non_hit(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    _git(repo, "switch", "-c", "feature")
    (repo / "notes.md").write_text(
        "The overall allowance is fine.\nOur only path is forward. [Established]\n",
        encoding="utf-8",
    )
    _git(repo, "add", "notes.md")
    done = _claim(repo)
    assert done.returncode == 0
    assert "notes.md:2: only" in done.stdout
    assert "Our only path is forward. [Established]" in done.stdout
    assert "[Established]" in done.stdout
    assert "overall" not in done.stdout


def test_ignores_a_file_outside_rule_5(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    _git(repo, "switch", "-c", "feature")
    (repo / "src").mkdir()
    (repo / "src" / "notes.md").write_text("Our only path.\n", encoding="utf-8")
    done = _claim(repo)
    assert done.returncode == 0
    assert "only" not in done.stdout


def test_reads_an_untracked_file(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    note = repo / "research" / "formats" / "res.md"
    note.parent.mkdir(parents=True)
    note.write_text("Only a claim.\n", encoding="utf-8")
    done = _claim(repo)
    assert done.returncode == 0
    assert "research/formats/res.md:1: only" in done.stdout


def test_a_renamed_file_keeps_its_unchanged_lines_out(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    old = repo / RESEARCH / "old.md"
    old.parent.mkdir()
    old.write_text("An old all line.\n", encoding="utf-8")
    _git(repo, "add", f"{RESEARCH}/old.md")
    _git(repo, "commit", "-m", "test: note")
    _git(repo, "switch", "-c", "feature")
    _git(repo, "mv", f"{RESEARCH}/old.md", f"{RESEARCH}/new.md")
    done = _claim(repo)
    assert done.returncode == 0
    assert "all" not in done.stdout
    assert "new.md" not in done.stdout


def test_a_modified_file_skips_deleted_lines_and_numbers_inserted_ones(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    note = repo / "research" / "formats" / "res.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "First line.\nA deleted all line.\nThird line.\nFourth line.\n", encoding="utf-8"
    )
    _git(repo, "add", "research/formats/res.md")
    _git(repo, "commit", "-m", "test: note")
    _git(repo, "switch", "-c", "feature")
    note.write_text(
        "First line.\nThird line.\nInserted only line.\nFourth line.\n", encoding="utf-8"
    )
    done = _claim(repo)
    assert done.returncode == 0
    assert "research/formats/res.md:3: only" in done.stdout
    assert "all" not in done.stdout


def test_a_named_base_is_counted_from_its_merge_base(tmp_path: Path) -> None:
    repo = _base(tmp_path)
    _git(repo, "switch", "-c", "feature")
    (repo / "notes.md").write_text("Only a claim.\n", encoding="utf-8")
    _git(repo, "add", "notes.md")
    done = _claim(repo, "main")
    assert done.returncode == 0
    assert "notes.md:1: only" in done.stdout
