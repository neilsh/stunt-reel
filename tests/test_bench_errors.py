"""The error readout: categories, sheets, grades, readouts, comparisons and calibration."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stunt_reel.bench.errors import FilmWindow, add_example, load_categories
from stunt_reel.bench.planes import BenchError

REPO = Path(__file__).resolve().parents[1]
CATEGORIES = REPO / "research" / "parity" / "error-categories.toml"

TWO_CATEGORIES = """\
# a comment
[[category]]
id = "a"
definition = "first"
examples = []

[[category]]
id = "b"
definition = "second"
examples = ["x"]

[faults]
"actors_removed" = ["a"]

[films.ctry]
start = 0
end = 990

[readout]
min_change = 2
"""


def _write(tmp_path: Path, text: str) -> Path:
    examples = tmp_path / "error-examples"
    examples.mkdir(exist_ok=True)
    (examples / "x.png").write_bytes(b"")
    (examples / "y.png").write_bytes(b"")
    path = tmp_path / "categories.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_committed_categories_load() -> None:
    taxonomy = load_categories(CATEGORIES)
    assert len(taxonomy.categories) == 15
    assert taxonomy.ids[0] == "aircraft-parts-missing"
    assert taxonomy.ids[-1] == "explosion-missing"
    assert taxonomy.films["intro"] == FilmWindow(1000, None)
    assert taxonomy.films["ctry"] == FilmWindow(0, 990)
    assert taxonomy.min_change == 2
    assert len(taxonomy.digest) == 64


def test_film_window_end_is_exclusive() -> None:
    window = FilmWindow(10, 20)
    assert window.holds(10)
    assert not window.holds(20)
    assert FilmWindow(10, None).holds(10**9)


def test_digest_ignores_examples(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    before = load_categories(path).digest
    add_example(path, "a", "y")
    assert load_categories(path).digest == before
    path.write_text(
        path.read_text(encoding="utf-8").replace('"first"', '"first, changed"'),
        encoding="utf-8",
        newline="\n",
    )
    assert load_categories(path).digest != before


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ('id = "b"', 'id = "a"', '"a"'),
        ('"actors_removed" = ["a"]', '"wobble:3" = ["a"]', "wobble:3"),
        ('"actors_removed" = ["a"]', '"actors_removed" = ["no-such-category"]', "no-such-category"),
        ('examples = ["x"]', 'examples = ["ctry-0001"]', "ctry-0001"),
    ],
)
def test_rejects_bad_files(tmp_path: Path, old: str, new: str, named: str) -> None:
    path = _write(tmp_path, TWO_CATEGORIES.replace(old, new))
    with pytest.raises(BenchError, match=named.strip('"')):
        load_categories(path)


def test_add_example_edits_one_block(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    add_example(path, "b", "y")
    text = path.read_text(encoding="utf-8")
    assert text == TWO_CATEGORIES.replace('examples = ["x"]', 'examples = ["x", "y"]')
    add_example(path, "b", "y")
    assert path.read_text(encoding="utf-8") == text
    with pytest.raises(BenchError, match="zzz"):
        add_example(path, "zzz", "y")


def test_committed_file_copy_takes_an_example(tmp_path: Path) -> None:
    path = tmp_path / "error-categories.toml"
    shutil.copy(CATEGORIES, path)
    shutil.copytree(CATEGORIES.parent / "error-examples", tmp_path / "error-examples")
    add_example(path, "aircraft-too-small", "ctry-0004")
    assert load_categories(path).categories[2].examples == ("ctry-0004",)
