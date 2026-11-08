"""`mise run move-docs`: `git mv` what a moves file lists, then rewrite every link and path to it.

The rewriting cases call `rewrite_text` on strings; the phases build a throwaway repository
in `tmp_path`, without the user's autocrlf, and run `main` against it with `--root`.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.work_items import parse_folder

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
GIT = shutil.which("git")
#: Variables that point git at another repository; a suite started from a hook has them set.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")

needs_git = pytest.mark.skipif(GIT is None, reason="git is not on PATH")


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("move_docs", SCRIPTS / "move_docs.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


move_docs = _load()


def _md(stem: str) -> str:
    """*stem* plus `.md`: a fake doc path written whole would read as a citation of a real one."""
    return f"{stem}.md"


A = _md("docs/drafts/a-2026-11-01")
B = _md("docs/drafts/b-2026-11-01")
SPEC = _md("work/2026-11/a/spec")
PLAN = _md("work/2026-11/a/plan")
README = _md("work/2026-11/a/README")
ADR = _md("docs/adr/0001-x")
#: A dated record that names the moved files: the work item that moves them.
RECORD = _md("work/2026-11/9_move/plan")
MAPPING = {
    A: SPEC,
    B: PLAN,
    "research/parity/hangar": "work/2026-11/a/images",
    "research/parity/hangar/x.png": "work/2026-11/a/images/x.png",
}
MOVES = f"""\
[[move]]
from = "{A}"
to = "{SPEC}"

[[move]]
from = "{B}"
to = "{PLAN}"

[[move]]
from = "research/parity/hangar/"
to = "work/2026-11/a/images"

[[folder]]
path = "work/2026-11/a"
title = 'A "quoted" plan'
started = 2026-11-01
outcome = "Landed in #12"
state_source = "Status line"
"""
MOVES_PATH = "work/2026-11/9_move/moves.toml"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00"
#: A small repository: two plans that link each other, an image directory, and files that
#: name them in every way the rewrite handles or must leave alone.
TREE: dict[str, str | bytes] = {
    "AGENTS.md": f"See [`{A}`]({A}).\n",
    ADR: (
        "Accepted ([spec](../drafts/a-2026-11-01.md#decisions)).\n\n"
        "[p]: ../drafts/b-2026-11-01.md\n"
    ),
    A: (
        "# A\n\n[plan](b-2026-11-01.md#task-1), [ADR](../adr/0001-x.md), "
        "[hangar](../../research/parity/hangar/).\n"
    ),
    B: "# B\n\n[spec](a-2026-11-01.md)\n",
    "research/parity/hangar/x.png": PNG,
    "research/parity/hangar/sub/y.png": PNG + b"y",
    "research/README.md": "[hangar/](parity/hangar/) ![x](parity/hangar/x.png)\n",
    "python/tool.py": f'"""Plan: {A}."""\n',
    "corpus/notes.md": f"{A}\n",
    "latin1.txt": A.encode() + b" \xe9\n",
    "zero-byte.txt": A.encode() + b"\x00\n",
    MOVES_PATH: MOVES,
    RECORD: f"Move `{A}`; see [a](../../../docs/drafts/a-2026-11-01.md).\n",
}
#: The files that did not move, as the move phase leaves them.
AFTER_MOVE: dict[str, str | bytes] = {
    "AGENTS.md": f"See [`{SPEC}`]({SPEC}).\n",
    ADR: (
        "Accepted ([spec](../../work/2026-11/a/spec.md#decisions)).\n\n"
        "[p]: ../../work/2026-11/a/plan.md\n"
    ),
    "research/README.md": (
        "[hangar/](../work/2026-11/a/images/) ![x](../work/2026-11/a/images/x.png)\n"
    ),
    "python/tool.py": f'"""Plan: {SPEC}."""\n',
    RECORD: f"Move `{A}`; see [a](../a/spec.md).\n",
}
MOVED = {
    A: SPEC,
    B: PLAN,
    "research/parity/hangar/x.png": "work/2026-11/a/images/x.png",
    "research/parity/hangar/sub/y.png": "work/2026-11/a/images/sub/y.png",
}


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_LOCATION_ENV:
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> str:
    assert GIT is not None
    done = subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


def _repo(root: Path, tree: dict[str, str | bytes]) -> Path:
    """Commit *tree* into a new repository at *root*, with no autocrlf."""
    _git(root, "init", "-q")
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.com")
    for name, content in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
    _git(root, "add", "--", *tree)
    _git(root, "commit", "-q", "-m", "tree")
    return root


def _apply(root: Path, phase: str, *extra: str, moves: str = MOVES_PATH) -> int:
    code: int = move_docs.main(
        ["apply", str(root / moves), "--phase", phase, "--root", str(root), *extra]
    )
    return code


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _rewrite(
    text: str, source: str, new_source: str | None = None, *, markdown: bool = True
) -> str:
    result: str = move_docs.rewrite_text(
        text, source, new_source or source, MAPPING, markdown=markdown
    )
    return result


# Rewriting one file.


def test_inline_link_from_unmoved_file_follows_the_move() -> None:
    text = "See [the plan](../drafts/a-2026-11-01.md).\n"
    assert _rewrite(text, ADR) == "See [the plan](../../work/2026-11/a/spec.md).\n"


def test_reference_style_definition_follows_the_move() -> None:
    text = (
        "See [the plan][p] and [the other][q].\n\n"
        "[p]: ../drafts/a-2026-11-01.md\n"
        '  [q]: <../drafts/b-2026-11-01.md> "Plan B"\n'
    )
    assert _rewrite(text, ADR) == (
        "See [the plan][p] and [the other][q].\n\n"
        "[p]: ../../work/2026-11/a/spec.md\n"
        '  [q]: <../../work/2026-11/a/plan.md> "Plan B"\n'
    )


def test_fragment_is_kept() -> None:
    text = "[s](../drafts/a-2026-11-01.md#decisions) [t](../drafts/b-2026-11-01.md?x#y)"
    assert _rewrite(text, ADR) == (
        "[s](../../work/2026-11/a/spec.md#decisions) [t](../../work/2026-11/a/plan.md?x#y)"
    )


def test_link_to_a_moved_directory_follows_it() -> None:
    text = (
        "[hangar/](parity/hangar/), [hangar](parity/hangar), "
        "![x](parity/hangar/x.png), [later](parity/hangar/later.png)\n"
    )
    assert _rewrite(text, "research/README.md") == (
        "[hangar/](../work/2026-11/a/images/), [hangar](../work/2026-11/a/images), "
        "![x](../work/2026-11/a/images/x.png), [later](../work/2026-11/a/images/later.png)\n"
    )


def test_a_rooted_link_changes_only_when_its_target_moves() -> None:
    text = "[top](/), [log](/research/parity/hangar/x.png#a), [same](/README.md)"
    assert _rewrite(text, A, MAPPING[A]) == (
        "[top](/), [log](/work/2026-11/a/images/x.png#a), [same](/README.md)"
    )


def test_links_of_a_moved_file_are_re_expressed_from_its_new_place() -> None:
    text = "[plan](b-2026-11-01.md#task-1), [ADR](../adr/0001-x.md), [self](#a), [top](/README.md)"
    assert _rewrite(text, A, MAPPING[A]) == (
        "[plan](plan.md#task-1), [ADR](../../../docs/adr/0001-x.md), [self](#a), [top](/README.md)"
    )


def test_root_relative_path_in_code_comment_is_replaced() -> None:
    text = f"# See {A} and research/parity/hangar/x.png, or research/parity/hangar/.\n"
    assert _rewrite(text, "python/tool.py", markdown=False) == (
        f"# See {SPEC} and work/2026-11/a/images/x.png, or work/2026-11/a/images/.\n"
    )


@pytest.mark.parametrize(
    "text",
    [
        f"{A}.bak",
        f"{A}x",
        f"{A}-old",
        f"other/{A}",
        f"../{A}",
        f"https://example.com/{A}",
        "research/parity/hangar-old/x.png",
        "docs/drafts/",
        "research/parity",
    ],
)
def test_root_relative_paths_match_on_path_boundaries_only(text: str) -> None:
    assert _rewrite(text, "python/tool.py", markdown=False) == text


def test_a_path_in_prose_follows_the_move_inside_code_spans_too() -> None:
    text = f'Read `{A}#goals`, ({A}), or "{A}":12.\n'
    new = MAPPING[A]
    assert _rewrite(text, _md("docs/x")) == f'Read `{new}#goals`, ({new}), or "{new}":12.\n'


def test_a_link_from_the_root_and_its_text_are_each_rewritten_once() -> None:
    text = f"[`{A}`]({A}) [x]({A}#y)\n"
    new = MAPPING[A]
    assert _rewrite(text, "AGENTS.md") == f"[`{new}`]({new}) [x]({new}#y)\n"


def test_links_inside_code_spans_and_fences_are_left_alone() -> None:
    text = (
        "`[p](../drafts/a-2026-11-01.md)`\n"
        "```md\n"
        "[p](../drafts/a-2026-11-01.md)\n"
        "[q]: ../drafts/b-2026-11-01.md\n"
        "```\n"
    )
    assert _rewrite(text, ADR) == text


def test_urls_and_links_to_what_did_not_move_are_left_alone() -> None:
    text = (
        "[u](https://example.com/docs/drafts/a-2026-11-01.md) [m](mailto:a@b.c) "
        "[f](#a-2026-11-01) [o](../drafts/other.md) [up](../../../outside.md)\n"
    )
    assert _rewrite(text, ADR) == text


def test_a_dated_record_takes_link_fixes_only() -> None:
    text = f"Move `{A}` ({A}); see [a](../../../docs/drafts/a-2026-11-01.md).\n"
    assert _rewrite(text, RECORD) == (f"Move `{A}` ({A}); see [a](../a/spec.md).\n")
    assert _rewrite(f'"{A}"', "work/2026-11/9_move/plan.py", markdown=False) == f'"{A}"'


# Reading a moves file.


def test_load_moves_expands_a_directory_and_path_map_covers_it(tmp_path: Path) -> None:
    moves_file = tmp_path / "moves.toml"
    moves_file.write_text(MOVES, encoding="utf-8")
    tracked = [A, B, "research/parity/hangar/x.png", "research/parity/hangar/sub/y.png"]
    moves = move_docs.load_moves(moves_file, tracked)
    assert moves == [
        (A, MOVED[A]),
        (B, MOVED[B]),
        ("research/parity/hangar/", "work/2026-11/a/images/"),
        ("research/parity/hangar/sub/y.png", "work/2026-11/a/images/sub/y.png"),
        ("research/parity/hangar/x.png", "work/2026-11/a/images/x.png"),
    ]
    assert move_docs.path_map(moves) == {
        **MOVED,
        "research/parity/hangar": "work/2026-11/a/images",
        "research/parity/hangar/sub": "work/2026-11/a/images/sub",
    }


def test_load_moves_finds_a_moved_directory_under_its_new_path(tmp_path: Path) -> None:
    moves_file = tmp_path / "moves.toml"
    moves_file.write_text(MOVES, encoding="utf-8")
    moves = move_docs.load_moves(moves_file, list(MOVED.values()))
    assert sorted(pair for pair in moves if not pair[0].endswith("/")) == sorted(MOVED.items())


@pytest.mark.parametrize(
    ("toml", "reason"),
    [
        ("", "no [[move]]"),
        ("[[moves]]\nfrom = 'a.md'\nto = 'b.md'\n", "unknown"),
        ("[[move]]\nfrom = 'a.md'\n", "from and to"),
        ("[[move]]\nfrom = '../a.md'\nto = 'b.md'\n", "repo-relative"),
        ("[[move]]\nfrom = 'gone.md'\nto = 'b.md'\n", "neither"),
        ("[[move]]\nfrom = 'a.md'\nto = 'b.md'\n[[move]]\nfrom = 'c.md'\nto = 'b.md'\n", "twice"),
        ("[[move]\n", "TOML"),
    ],
)
def test_load_moves_refuses_a_bad_moves_file(tmp_path: Path, toml: str, reason: str) -> None:
    moves_file = tmp_path / "moves.toml"
    moves_file.write_text(toml, encoding="utf-8")
    with pytest.raises(move_docs.MovesError, match=re.escape(reason)):
        move_docs.load_moves(moves_file, ["a.md", "c.md"])


# The phases, in a throwaway repository.


@needs_git
def test_move_phase_leaves_moved_files_bytes_identical(tmp_path: Path) -> None:
    root = _repo(tmp_path, TREE)
    assert _apply(root, "move") == 0
    for old, new in MOVED.items():
        assert not (root / old).exists()
        expected = TREE[old]
        assert (root / new).read_bytes() == (
            expected.encode() if isinstance(expected, str) else expected
        )
    _git(root, "add", "--", *AFTER_MOVE, README)
    renames = _git(root, "diff", "--cached", "-M100%", "--name-status", "HEAD").splitlines()
    assert sorted(line for line in renames if line.startswith("R")) == sorted(
        f"R100\t{old}\t{new}" for old, new in MOVED.items()
    )


@needs_git
def test_move_phase_rewrites_every_tracked_text_file_that_did_not_move(tmp_path: Path) -> None:
    root = _repo(tmp_path, TREE)
    assert _apply(root, "move") == 0
    for name, content in TREE.items():
        if name in MOVED:
            continue
        expected = AFTER_MOVE.get(name, content)
        assert (root / name).read_bytes() == (
            expected.encode() if isinstance(expected, str) else expected
        ), name


@needs_git
@pytest.mark.parametrize(
    ("line", "status"),
    [("", "landed"), ('status = "abandoned"\n', "abandoned")],
    ids=["no-status", "abandoned"],
)
def test_move_phase_writes_each_folder_readme(tmp_path: Path, line: str, status: str) -> None:
    moves = MOVES.replace("started = 2026-11-01\n", f"started = 2026-11-01\n{line}")
    root = _repo(tmp_path, {**TREE, MOVES_PATH: moves})
    assert _apply(root, "move") == 0
    folder = parse_folder(root / "work/2026-11/a")
    assert (folder.title, folder.started) == ('A "quoted" plan', date(2026, 11, 1))
    assert (folder.status, folder.issue, folder.outcome) == (status, None, "Landed in #12")


@needs_git
def test_link_between_two_moved_files_resolves_in_inside_phase(tmp_path: Path) -> None:
    root = _repo(tmp_path, TREE)
    assert _apply(root, "move") == 0
    after_move = _snapshot(root)
    assert _apply(root, "inside") == 0
    assert (root / MOVED[A]).read_text(encoding="utf-8") == (
        "# A\n\n[plan](plan.md#task-1), [ADR](../../../docs/adr/0001-x.md), [hangar](images/).\n"
    )
    assert (root / MOVED[B]).read_text(encoding="utf-8") == "# B\n\n[spec](spec.md)\n"
    changed = {name for name, data in _snapshot(root).items() if after_move.get(name) != data}
    assert changed == {MOVED[A], MOVED[B]}


@needs_git
def test_line_endings_are_preserved(tmp_path: Path) -> None:
    tree = {
        **TREE,
        _md("docs/crlf"): "One\r\n[p](drafts/a-2026-11-01.md)\r\nTwo\r\n",
        "python/crlf.py": f"# {A}\r\n# {A}\n",
    }
    root = _repo(tmp_path, tree)
    assert _apply(root, "move") == 0
    assert (root / _md("docs/crlf")).read_bytes() == (
        b"One\r\n[p](../work/2026-11/a/spec.md)\r\nTwo\r\n"
    )
    assert (root / "python/crlf.py").read_bytes() == (f"# {SPEC}\r\n# {SPEC}\n".encode())


@needs_git
def test_dry_run_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path, TREE)
    before, status = _snapshot(root), _git(root, "status", "--porcelain")
    assert _apply(root, "move", "--dry-run") == 0
    assert _snapshot(root) == before
    assert _git(root, "status", "--porcelain") == status
    out = capsys.readouterr().out
    for old, new in MOVED.items():
        assert f"| `{old}` | `{new}` |" in out
    assert "| `work/2026-11/a` | landed | Status line |" in out
    written, _, left_alone = out.partition("Left alone")
    for name in [*AFTER_MOVE, README]:
        assert f"  {name}\n" in written
    for name in ("corpus/notes.md", MOVES_PATH):
        assert f"  {name}\n" not in out
    # Not text, so not rewritten, but listed: each names a moved path.
    assert left_alone.splitlines()[1:] == ["  latin1.txt", "  zero-byte.txt"]


@needs_git
def test_the_moves_file_is_never_rewritten(tmp_path: Path) -> None:
    tree = {name: content for name, content in TREE.items() if name != MOVES_PATH}
    root = _repo(tmp_path, {**tree, "moves.toml": MOVES})
    assert _apply(root, "move", moves="moves.toml") == 0
    assert (root / "moves.toml").read_text(encoding="utf-8") == MOVES
    assert _apply(root, "inside", moves="moves.toml") == 0
    assert "[spec](spec.md)" in (root / MOVED[B]).read_text(encoding="utf-8")


@needs_git
@pytest.mark.parametrize(
    ("extra", "reason"),
    [
        ({SPEC: "taken\n"}, "already exists"),
        ({README: "taken\n"}, "already exists"),
    ],
)
def test_move_phase_refuses_a_target_that_exists_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: dict[str, str], reason: str
) -> None:
    root = _repo(tmp_path, {**TREE, **extra})
    before = _snapshot(root)
    assert _apply(root, "move") == 1
    assert _snapshot(root) == before
    err = capsys.readouterr().err
    assert reason in err
    assert "Traceback" not in err


@needs_git
def test_a_folder_that_breaks_the_layout_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    moves = MOVES.replace("started = 2026-11-01\n", "started = 2026-11-01\nissue = 12\n")
    root = _repo(tmp_path, {**TREE, MOVES_PATH: moves})
    before = _snapshot(root)
    assert _apply(root, "move") == 1
    assert _snapshot(root) == before
    assert "no issue number" in capsys.readouterr().err


@needs_git
def test_a_folder_marked_landed_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    moves = MOVES.replace("started = 2026-11-01\n", 'started = 2026-11-01\nstatus = "landed"\n')
    root = _repo(tmp_path, {**TREE, MOVES_PATH: moves})
    before, status = _snapshot(root), _git(root, "status", "--porcelain")
    assert _apply(root, "move") == 1
    assert _snapshot(root) == before
    assert _git(root, "status", "--porcelain") == status
    err = capsys.readouterr().err
    assert "[[folder]] work/2026-11/a: " in err
    assert "omit status for a landed record" in err


@needs_git
def test_inside_phase_before_the_move_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _repo(tmp_path, TREE)
    before = _snapshot(root)
    assert _apply(root, "inside") == 1
    assert _snapshot(root) == before
    assert "--phase move" in capsys.readouterr().err


@needs_git
def test_inside_phase_refuses_a_second_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A second run would resolve the rewritten links from the old place again and break them."""
    root = _repo(tmp_path, TREE)
    assert _apply(root, "move") == 0
    assert _apply(root, "inside") == 0
    before = _snapshot(root)
    capsys.readouterr()
    assert _apply(root, "inside") == 1
    assert _snapshot(root) == before
    err = capsys.readouterr().err
    assert f"{SPEC}: link plan.md#task-1 already resolves from its new place" in err
    assert "Traceback" not in err


@needs_git
def test_move_phase_refuses_a_directory_move_onto_an_existing_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The inside phase finds a moved directory's files under `to`, so `to` must hold only them."""
    root = _repo(tmp_path, {**TREE, "work/2026-11/a/images/old.png": PNG})
    before = _snapshot(root)
    assert _apply(root, "move") == 1
    assert _snapshot(root) == before
    assert "work/2026-11/a/images already exists" in capsys.readouterr().err


@needs_git
def test_move_phase_refuses_a_folder_inside_a_moved_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Its README would sit under the directory's `to`, read back as a moved file."""
    moves = MOVES.replace('to = "work/2026-11/a/images"', 'to = "work/2026-11/hangar"')
    moves = moves.replace('path = "work/2026-11/a"', 'path = "work/2026-11/hangar"')
    root = _repo(tmp_path, {**TREE, MOVES_PATH: moves})
    before = _snapshot(root)
    assert _apply(root, "move") == 1
    assert _snapshot(root) == before
    assert "inside the moved directory work/2026-11/hangar" in capsys.readouterr().err
