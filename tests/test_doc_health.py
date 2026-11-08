"""`mise run doc-health`: oversized, unsummarised and session-style docs, and stale work items."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
TODAY = date(2026, 11, 21)
SUMMARY = "---\nsummary: A note.\n---\n\n# Note\n"
#: Fixture paths are built from these parts so this file names no document path of its own for
#: ``test_code_cited_docs_exist`` to look up.
RESEARCH = "research"
DOCS = "docs"
WORK_FOLDER = "work/2026-11/307_docs-streamline"
GIT_LOG = ["log", "-1", "--format=%cs", "--", WORK_FOLDER]


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("doc_health", SCRIPTS / "doc_health.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


doc_health = _load()


def _write(root: Path, relative: str, text: str = SUMMARY) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _sized(size: int) -> str:
    return SUMMARY + "x" * (size - len(SUMMARY))


def _work_folder(root: Path, issue: int = 307, outcome: str = '""') -> None:
    readme = f"---\ntitle: T\nstarted: 2026-11-07\nissue: {issue}\noutcome: {outcome}\n---\n"
    _write(root, f"work/2026-11/{issue}_docs-streamline/README.md", readme)


def _gh(state: str, reason: str = "") -> str:
    return json.dumps([{"number": 307, "state": state, "stateReason": reason}])


class FakeRunner:
    """Answers `gh` with *gh* and `git` with *git*, raising an answer that is an exception."""

    def __init__(self, gh: str | Exception, git: str | Exception = "") -> None:
        self.answers = {"gh": gh, "git": git}
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        answer = self.answers[args[0]]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _unused(args: list[str]) -> str:
    raise AssertionError(f"no command should run: {args}")


def _found(findings: list[Any], kind: str) -> list[tuple[str, str]]:
    return [(f.path, f.detail) for f in findings if f.kind == kind]


def test_flags_an_oversized_note_and_ranks_it_first(tmp_path: Path) -> None:
    _write(tmp_path, f"{RESEARCH}/formats/mid.md", _sized(21000))
    _write(tmp_path, f"{RESEARCH}/parity/big.md", _sized(30000))
    _write(tmp_path, f"{DOCS}/agents/guide.md", _sized(25000))
    _write(tmp_path, f"{DOCS}/howto/run.md", _sized(22000))
    _write(tmp_path, f"{DOCS}/SPEC.md", _sized(20480))
    _write(tmp_path, f"{DOCS}/process/plan.md", _sized(40000))
    _write(tmp_path, "README.md", _sized(40000))
    _write(tmp_path, f"{RESEARCH}/unsummarised.md", "# Note\n")
    findings = doc_health.collect(tmp_path, _unused, TODAY)
    assert [(f.kind, f.path, f.weight) for f in findings[:4]] == [
        ("size", f"{RESEARCH}/parity/big.md", 30000),
        ("size", f"{DOCS}/agents/guide.md", 25000),
        ("size", f"{DOCS}/howto/run.md", 22000),
        ("size", f"{RESEARCH}/formats/mid.md", 21000),
    ]
    assert findings[0].detail == "30000 bytes, over the 20480-byte budget"
    assert [f.kind for f in findings[4:]] == ["summary"]
    assert all(f.weight == 1 for f in findings[4:])


def test_size_is_bytes_on_disk(tmp_path: Path) -> None:
    _write(tmp_path, f"{DOCS}/crlf.md", "x\r\n" * 7000)
    assert _found(doc_health.collect(tmp_path, _unused, TODAY), "size") == [
        (f"{DOCS}/crlf.md", "21000 bytes, over the 20480-byte budget")
    ]


def test_agents_md_is_evergreen(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md", "# Agents\n\n## Handoff to the next session\n" + "x" * 21000)
    findings = doc_health.collect(tmp_path, _unused, TODAY)
    assert [(f.kind, f.path) for f in findings] == [("size", "AGENTS.md"), ("heading", "AGENTS.md")]
    assert findings[1].detail == "line 3: ## Handoff to the next session"


def test_exempts_generated_tables_and_adrs(tmp_path: Path) -> None:
    dated = SUMMARY + "## 2026-11-06 sweep\n" + "x" * 30000
    for relative in (
        f"{RESEARCH}/MAP.md",
        f"{RESEARCH}/formats/sod-opcode-coverage.md",
        f"{DOCS}/adr/0001-a-decision.md",
    ):
        _write(tmp_path, relative, dated)
    assert doc_health.collect(tmp_path, _unused, TODAY) == []


def test_flags_a_research_note_without_summary(tmp_path: Path) -> None:
    _write(tmp_path, f"{RESEARCH}/parity/bare.md", "# Bare\n")
    _write(tmp_path, f"{RESEARCH}/formats/empty.md", '---\nsummary: ""\n---\n')
    _write(tmp_path, f"{RESEARCH}/formats/unclosed.md", "---\nsummary: never closed\n")
    _write(tmp_path, f"{RESEARCH}/summarised.md")
    _write(tmp_path, f"{RESEARCH}/README.md", "# Research\n")
    _write(tmp_path, f"{RESEARCH}/parity/README.md", "# Parity\n")
    _write(tmp_path, f"{RESEARCH}/MAP.md", "# Research map\n")
    _write(tmp_path, f"{DOCS}/development.md", "# Development\n")
    (tmp_path / f"{RESEARCH}/formats/latin1.md").write_bytes(b"---\nsummary: caf\xe9\n---\n")
    assert _found(doc_health.collect(tmp_path, _unused, TODAY), "summary") == [
        (f"{RESEARCH}/formats/empty.md", "no summary: in its frontmatter"),
        (f"{RESEARCH}/formats/latin1.md", "no summary: in its frontmatter"),
        (f"{RESEARCH}/formats/unclosed.md", "no summary: in its frontmatter"),
        (f"{RESEARCH}/parity/bare.md", "no summary: in its frontmatter"),
    ]


@pytest.mark.parametrize(
    ("heading", "flagged"),
    [
        ("## 4.1 Second Round: Seven Questions", True),
        ("## 2026-11-06 sweep", True),
        ("### Update: lavapipe", True),
        ("## Updates to the capture", True),
        ("## 4. Follow-up Measurements", True),
        ("## Handoff to the next session", True),
        ("## Session notes", True),
        ("## The 3rd round of probes", True),
        ("### Dependency updates", False),
        ("## Ruled out", False),
        ("### UpdateCamera at 0x1234", False),
        ("## 1992 retail release", False),
    ],
)
def test_session_style_headings(tmp_path: Path, heading: str, flagged: bool) -> None:
    _write(tmp_path, f"{DOCS}/howto/note.md", f"# Note\n\nText.\n\n{heading}\n\nMore.\n")
    expected = [(f"{DOCS}/howto/note.md", f"line 5: {heading}")] if flagged else []
    assert _found(doc_health.collect(tmp_path, _unused, TODAY), "heading") == expected


def test_lines_in_fenced_blocks_are_not_headings(tmp_path: Path) -> None:
    text = (
        "---\nsummary: Fences.\n---\n\n# Fences\n\n"
        "```sh\n# 2026-11-06 sweep\n## Update: lavapipe\n```\n\n"
        "```markdown\n## Ruled out\n### Handoff\n```\n\n"
        "## Session `2026-11-07`\n"
    )
    _write(tmp_path, f"{RESEARCH}/parity/fences.md", text)
    assert _found(doc_health.collect(tmp_path, _unused, TODAY), "heading") == [
        (f"{RESEARCH}/parity/fences.md", "line 17: ## Session `2026-11-07`")
    ]


@pytest.mark.parametrize(("last_commit", "flagged"), [("2026-11-07", True), ("2026-11-08", False)])
def test_flags_an_open_issue_untouched_for_14_days(
    tmp_path: Path, last_commit: str, flagged: bool
) -> None:
    _work_folder(tmp_path)
    run = FakeRunner(_gh("OPEN"), f"{last_commit}\n")
    expected = (
        [
            (
                WORK_FOLDER,
                f"issue #307 is open and no commit has touched the folder since {last_commit}",
            )
        ]
        if flagged
        else []
    )
    findings = doc_health.collect(tmp_path, run, TODAY)
    assert _found(findings, "stale-issue") == expected
    assert run.calls[1] == ["git", "-C", str(tmp_path), *GIT_LOG]
    assert _found(findings, "missing-outcome") == []


def test_an_open_issue_whose_folder_was_never_committed_is_not_stale(tmp_path: Path) -> None:
    _work_folder(tmp_path)
    assert doc_health.collect(tmp_path, FakeRunner(_gh("OPEN"), ""), TODAY) == []


@pytest.mark.parametrize(
    ("reason", "outcome", "flagged"),
    [
        ("COMPLETED", '""', True),
        ("NOT_PLANNED", '"  "', True),
        ("COMPLETED", "Landed in #310.", False),
    ],
)
def test_flags_a_closed_issue_with_empty_outcome(
    tmp_path: Path, reason: str, outcome: str, flagged: bool
) -> None:
    _work_folder(tmp_path, outcome=outcome)
    run = FakeRunner(_gh("CLOSED", reason), AssertionError("a closed issue needs no git log"))
    status = "abandoned" if reason == "NOT_PLANNED" else "landed"
    expected = [(WORK_FOLDER, f"issue #307 is closed ({status}) and outcome is empty")]
    assert _found(doc_health.collect(tmp_path, run, TODAY), "missing-outcome") == (
        expected if flagged else []
    )


def test_without_gh_skips_issue_checks_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _work_folder(tmp_path)
    _write(tmp_path, f"{RESEARCH}/bare.md", "# Bare\n\n## 2026-11-06 sweep\n")
    _write(tmp_path, f"{DOCS}/big.md", _sized(21000))
    run = FakeRunner(FileNotFoundError(2, "No such file or directory", "gh"))
    assert doc_health.main(["--root", str(tmp_path)], run, TODAY) == 0
    out, err = capsys.readouterr()
    assert err == (
        "doc-health: gh gave no usable issue list, so the stale-issue and missing-outcome "
        "checks were skipped\n"
    )
    assert [line.split()[0] for line in out.splitlines()] == ["size", "summary", "heading"]
    assert [args[0] for args in run.calls] == ["gh"]


def test_a_failing_git_log_skips_the_stale_check_with_a_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _work_folder(tmp_path)
    _work_folder(tmp_path, issue=308)
    gh = json.dumps([{"number": n, "state": "OPEN", "stateReason": ""} for n in (307, 308)])
    run = FakeRunner(gh, subprocess.CalledProcessError(128, ["git"]))
    assert doc_health.collect(tmp_path, run, TODAY) == []
    assert capsys.readouterr().err == (
        "doc-health: git log failed, so the stale-issue check was skipped\n"
    )
    assert [args[0] for args in run.calls] == ["gh", "git"]


def test_a_broken_work_folder_is_a_finding(tmp_path: Path) -> None:
    (tmp_path / "work/2026-11/no-readme").mkdir(parents=True)
    _write(tmp_path / "work", "README.md", "# Work\n")
    assert _found(doc_health.collect(tmp_path, _unused, TODAY), "folder") == [
        ("work/2026-11/no-readme", "2026-11/no-readme: has no README.md")
    ]
    assert doc_health.main(["--root", str(tmp_path)], _unused, TODAY) == 0


def test_json_output_lists_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, f"{RESEARCH}/parity/big.md", _sized(30000))
    _write(tmp_path, f"{RESEARCH}/bare.md", "# Bare\n")
    assert doc_health.main(["--json", "--root", str(tmp_path)], _unused, TODAY) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert json.loads(out) == [
        {
            "path": f"{RESEARCH}/parity/big.md",
            "kind": "size",
            "detail": "30000 bytes, over the 20480-byte budget",
            "weight": 30000,
        },
        {
            "path": f"{RESEARCH}/bare.md",
            "kind": "summary",
            "detail": "no summary: in its frontmatter",
            "weight": 1,
        },
    ]


def test_table_output_ranks_findings_worst_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path, f"{RESEARCH}/bare.md", "# Bare\n")
    _write(tmp_path, f"{DOCS}/big.md", _sized(21000))
    assert doc_health.main(["--root", str(tmp_path)], _unused, TODAY) == 0
    assert capsys.readouterr().out == (
        f"size     {DOCS}/big.md       21000 bytes, over the 20480-byte budget\n"
        f"summary  {RESEARCH}/bare.md  no summary: in its frontmatter\n"
    )


def test_a_clean_tree_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, f"{RESEARCH}/note.md")
    assert doc_health.main(["--root", str(tmp_path)], _unused, TODAY) == 0
    assert capsys.readouterr().out == "doc-health: nothing to report\n"
    assert doc_health.main(["--json", "--root", str(tmp_path)], _unused, TODAY) == 0
    assert json.loads(capsys.readouterr().out) == []
