"""``parity_repin``: rewriting the expected tables from current reports, or refusing to."""

from __future__ import annotations

import subprocess
import sys
lazy from pathlib import Path

import pytest

from stunt_reel import dataroot, parity_layout
from stunt_reel.expected_scores import changed_since, clean_crates_tree, comparison_line
from stunt_reel.parity_artifacts import RenderAdapter, Report, read_report, write_report
from stunt_reel.references import read_reference

SCRIPTS_DIR = dataroot.REPO_ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_repin  # noqa: E402

GPU = RenderAdapter("NVIDIA GeForce RTX 4070", "hardware")
LAVAPIPE = RenderAdapter("llvmpipe (LLVM 19.1.7, 256 bits)", "cpu")
SHA_CTRY = "a" * 64
SHA_INTRO = "b" * 64
ALL_CTRY = "c" * 64
OLD_TREE = "1" * 40

#: Two rows: ctry with an archive pin, a comment and an old gpu table carrying `commit`; intro
#: with neither an archive pin nor a table.
DOCUMENT = f"""# Header comment, kept.

[ctry]
film = "vault-ctry"
sha256 = "{SHA_CTRY}"
# The archive the film plays, kept.
all_sha256 = "{ALL_CTRY}"

[ctry.expected.gpu]
ssim = 0.5000000
iou = 0.6000000
crates = "{OLD_TREE}"
sha256 = "{SHA_CTRY}"
all_sha256 = "{ALL_CTRY}"
commit = "abcdef1"
adapter = "{GPU.name}"

[intro]
film = "vault-intro"
sha256 = "{SHA_INTRO}"
"""


class Repo:
    """A scratch repository holding ``crates/a.rs`` and :data:`DOCUMENT`."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        hooks = root.parent / "no-hooks"
        hooks.mkdir()
        self._config = [
            "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={hooks}",
        ]  # fmt: skip
        self.git("init", "-q")
        self.write("crates/a.rs", "fn a() {}\n")
        self.write(".gitignore", "build/\n")
        self.write(parity_layout.REFERENCES_FILE.as_posix(), DOCUMENT)
        self.git("add", "-A")
        self.git("commit", "-qm", "start")
        self.tree = self.git("rev-parse", "HEAD:crates")

    def git(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", "-C", str(self.root), *self._config, *args],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    @property
    def references(self) -> Path:
        return self.root / parity_layout.REFERENCES_FILE

    def report(
        self,
        film: str,
        ssim: float,
        iou: float,
        *,
        crates: str | None = "tree",
        adapter: RenderAdapter = GPU,
    ) -> Report:
        """Writes *film*'s current report; *crates* ``"tree"`` stands for :attr:`tree`."""
        report = Report(
            per_frame=(),
            mean_ssim_scored=ssim,
            mean_iou_scored=iou,
            scored_frames=1,
            frames=1,
            reference_frames=1,
            adapter=adapter,
            crates=self.tree if crates == "tree" else crates,
        )
        path = self.root / parity_layout.report_dir(film) / "report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_report(path, report)
        return report


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo(tmp_path / "repo")


def test_a_repin_writes_every_table_that_reads_back(repo: Repo) -> None:
    repo.report("ctry", 0.812345678, 0.98765432)
    repo.report("intro", 0.7, 0.9)

    tables = parity_repin.repin(repo.root, "gpu")

    assert [t.film for t in tables] == ["ctry", "intro"]
    ctry = read_reference(repo.root, "ctry").expected["gpu"]
    assert (ctry.ssim, ctry.iou, ctry.crates) == (0.8123457, 0.9876543, repo.tree)
    assert (ctry.sha256, ctry.all_sha256, ctry.adapter) == (SHA_CTRY, ALL_CTRY, GPU.name)
    assert ctry.commit is None, "a commit line names an older measurement"
    intro = read_reference(repo.root, "intro").expected["gpu"]
    assert (intro.ssim, intro.crates, intro.sha256, intro.all_sha256) == (
        0.7,
        repo.tree,
        SHA_INTRO,
        None,
    )


def test_a_repin_keeps_comments_and_row_order(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    repo.report("intro", 0.7, 0.9)

    parity_repin.repin(repo.root, "gpu")

    text = repo.references.read_text(encoding="utf-8")
    assert text.startswith("# Header comment, kept.\n")
    assert "# The archive the film plays, kept.\n" in text
    order = [text.index(h) for h in ("[ctry]", "[ctry.expected.gpu]", "[intro]")]
    assert order == sorted(order)
    assert text.index("[intro.expected.gpu]") > text.index("[intro]")


def test_after_a_repin_the_same_reports_show_no_drift(repo: Repo) -> None:
    reports = {
        "ctry": repo.report("ctry", 0.812345678, 0.9),
        "intro": repo.report("intro", 0.7, 0.9),
    }

    parity_repin.repin(repo.root, "gpu")

    for film, report in reports.items():
        line = comparison_line(
            read_reference(repo.root, film),
            report,
            changed=lambda e, r: changed_since(e, r, repo=repo.root),
        )
        assert line.endswith("no drift"), line


def test_a_repin_of_lavapipe_adds_tables_beside_gpu(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9, adapter=LAVAPIPE)
    repo.report("intro", 0.7, 0.9, adapter=LAVAPIPE)

    parity_repin.repin(repo.root, "lavapipe")

    ctry = read_reference(repo.root, "ctry")
    assert ctry.expected["gpu"].ssim == 0.5, "the other class keeps its table"
    assert ctry.expected["lavapipe"].adapter == LAVAPIPE.name


def _refused(repo: Repo, renderer: str = "gpu") -> str:
    before = repo.references.read_bytes()
    with pytest.raises(parity_repin.RepinRefusedError) as caught:
        parity_repin.repin(repo.root, renderer)
    assert repo.references.read_bytes() == before, "a refusal writes nothing"
    return "\n".join(caught.value.reasons)


def test_a_dirty_crates_tree_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    repo.report("intro", 0.7, 0.9)
    repo.write("crates/a.rs", "fn a() { let _ = 1; }\n")
    assert "uncommitted" in _refused(repo)


def test_a_film_without_a_report_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    assert "intro: no report" in _refused(repo)


@pytest.mark.parametrize(
    ("crates", "says"), [(None, "records no crates/ tree"), ("2" * 40, "measured crates/ 2222222")]
)
def test_a_report_of_another_or_no_tree_is_refused(
    repo: Repo, crates: str | None, says: str
) -> None:
    repo.report("ctry", 0.8, 0.9, crates=crates)
    repo.report("intro", 0.7, 0.9)
    assert f"ctry: the report {says}" in _refused(repo)


def test_a_report_of_another_class_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9, adapter=LAVAPIPE)
    repo.report("intro", 0.7, 0.9)
    assert "ctry: the report was drawn on lavapipe" in _refused(repo)


def test_clean_crates_tree_is_head_crates_only_when_clean(repo: Repo) -> None:
    assert clean_crates_tree(repo.root) == repo.tree
    repo.write("crates/new.rs", "\n")
    assert clean_crates_tree(repo.root) is None


def test_a_report_round_trips_its_crates_tree(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_report(path, Report(per_frame=(), crates="f" * 40))
    assert read_report(path).crates == "f" * 40
    path.write_text('{"per_frame": []}', encoding="utf-8")
    assert read_report(path).crates is None


@pytest.mark.parametrize(
    ("no_build", "no_render", "rescored", "recorded"),
    [
        (False, False, False, "tree"),
        (True, False, False, None),
        (False, True, False, None),
        (False, False, True, None),
    ],
)
def test_a_parity_run_records_its_tree_only_for_a_fresh_build_and_render(
    no_build: bool, no_render: bool, rescored: bool, recorded: str | None
) -> None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    found = parity_run.recorded_crates(
        no_build=no_build, no_render=no_render, rescored=rescored, tree=lambda: "tree"
    )
    assert found == recorded
