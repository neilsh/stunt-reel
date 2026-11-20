"""``parity_repin``: regenerating the expected files from current reports, or refusing to."""

from __future__ import annotations

import dataclasses
import subprocess
import sys
lazy from pathlib import Path

import pytest

from stunt_reel import dataroot, expected_file, parity_layout
from stunt_reel.expected_scores import (
    RENDER_TREE_FILE,
    SCORER_DIR,
    changed_since,
    clean_crates_tree,
    comparison_line,
    read_render_tree,
    renderer_changes,
    scorer_only_change,
    write_render_tree,
)
from stunt_reel.parity_artifacts import (
    LOSS_CLASSES,
    RenderAdapter,
    Report,
    read_report,
    write_report,
)
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
#: The pins each row of :data:`DOCUMENT` records: ctry's capture and archive, intro's capture
#: alone.
ROW_PINS = {"ctry": (SHA_CTRY, ALL_CTRY), "intro": (SHA_INTRO, None)}

#: Two rows: ctry with an archive pin and a comment; intro without an archive pin.
DOCUMENT = f"""# Header comment, kept.

[ctry]
film = "vault-ctry"
sha256 = "{SHA_CTRY}"
# The archive the film plays, kept.
all_sha256 = "{ALL_CTRY}"

[intro]
film = "vault-intro"
sha256 = "{SHA_INTRO}"
"""

#: The committed gpu file: a hand-added comment, an old ctry table carrying `commit`, and a table
#: for a film no row names; a repin drops all three.
GPU_FILE = f"""# A hand-added comment, dropped.

[ctry]
ssim = 0.5000000
iou = 0.6000000
crates = "{OLD_TREE}"
sha256 = "{SHA_CTRY}"
all_sha256 = "{ALL_CTRY}"
commit = "abcdef1"
adapter = "{GPU.name}"

[ctry.loss]
props = 0.0100000
sky = 0.0200000

[gone]
ssim = 0.1000000
iou = 0.1000000
crates = "{OLD_TREE}"
sha256 = "{SHA_INTRO}"
adapter = "{GPU.name}"
"""


def losses(total: float = 0.1) -> dict[str, float]:
    """A report's class losses: *total* split evenly over :data:`LOSS_CLASSES`."""
    return {name: total / len(LOSS_CLASSES) for name in LOSS_CLASSES}


class Repo:
    """A scratch repository holding ``crates/a.rs``, :data:`DOCUMENT` and :data:`GPU_FILE`."""

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
        self.write(expected_file.path(parity_layout.REFERENCES_FILE, "gpu").as_posix(), GPU_FILE)
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

    def scorer_only(self, old: str, new: str) -> bool:
        """:func:`scorer_only_change` on this scratch repository."""
        return scorer_only_change(old, new, self.root)

    @property
    def references(self) -> Path:
        return self.root / parity_layout.REFERENCES_FILE

    def class_file(self, renderer: str) -> Path:
        """The generated expected file of *renderer*."""
        return expected_file.path(self.references, renderer)

    def report(
        self,
        film: str,
        ssim: float,
        iou: float,
        *,
        crates: str | None = "tree",
        adapter: RenderAdapter = GPU,
        pins: tuple[str | None, str | None] | None = None,
        loss: dict[str, float] | None = None,
    ) -> Report:
        """Writes *film*'s current report; *crates* ``"tree"`` stands for :attr:`tree`.

        *pins* are the ``sha256`` and ``all_sha256`` it records; ``None`` records the film's
        own row, as a run against that row's capture does; *loss* is the report's
        ``mean_loss_by_class_scored``, :func:`losses` when not given.
        """
        sha256, all_sha256 = ROW_PINS[film] if pins is None else pins
        report = Report(
            per_frame=(),
            mean_ssim_scored=ssim,
            mean_iou_scored=iou,
            mean_loss_by_class_scored=losses() if loss is None else loss,
            scored_frames=1,
            frames=1,
            reference_frames=1,
            adapter=adapter,
            crates=self.tree if crates == "tree" else crates,
            sha256=sha256,
            all_sha256=all_sha256,
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


def test_a_repin_writes_the_class_losses_in_class_order(repo: Repo) -> None:
    ctry = {**losses(), "props": 0.04, "terrain": 0.0117}
    repo.report("ctry", 0.8, 0.9, loss=ctry)
    repo.report("intro", 0.7, 0.9)

    parity_repin.repin(repo.root, "gpu")

    for film, expected in (("ctry", ctry), ("intro", losses())):
        pinned = read_reference(repo.root, film).expected["gpu"].loss
        assert pinned is not None
        assert tuple(pinned) == LOSS_CLASSES
        assert pinned == pytest.approx(expected, abs=1e-7)


def _expected_of(repo: Repo, films: tuple[str, ...] = ("ctry", "intro")) -> str:
    """What a repin of the scratch repo's gpu reports must write."""
    tables = []
    for film in films:
        values, loss = expected_file.format_values(read_reference(repo.root, film).expected["gpu"])
        tables.append((film, values, loss))
    return expected_file.render(tables)


def test_a_repin_regenerates_the_class_file_whole(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    repo.report("intro", 0.7, 0.9)
    references = repo.references.read_bytes()

    parity_repin.repin(repo.root, "gpu")

    text = repo.class_file("gpu").read_text(encoding="utf-8")
    assert text.startswith(expected_file.HEADER)
    assert "hand-added" not in text
    assert "[gone]" not in text
    assert "abcdef1" not in text, "a commit line names an older measurement"
    assert text == _expected_of(repo)
    assert text.index("[ctry]") < text.index("[intro]")
    assert repo.references.read_bytes() == references, "references.toml is left alone"


def test_a_repin_of_lavapipe_leaves_the_gpu_file_alone(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9, adapter=LAVAPIPE)
    repo.report("intro", 0.7, 0.9, adapter=LAVAPIPE)
    gpu = repo.class_file("gpu").read_bytes()

    parity_repin.repin(repo.root, "lavapipe")

    assert repo.class_file("gpu").read_bytes() == gpu, "the other class keeps its file"
    ctry = read_reference(repo.root, "ctry")
    assert ctry.expected["gpu"].ssim == 0.5
    assert ctry.expected["lavapipe"].adapter == LAVAPIPE.name


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


def _refused(repo: Repo, renderer: str = "gpu") -> str:
    before = repo.class_file(renderer).read_bytes() if repo.class_file(renderer).exists() else None
    with pytest.raises(parity_repin.RepinRefusedError) as caught:
        parity_repin.repin(repo.root, renderer)
    after = repo.class_file(renderer).read_bytes() if repo.class_file(renderer).exists() else None
    assert after == before, "a refusal writes nothing"
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


@pytest.mark.parametrize(
    ("pins", "says"),
    [
        ((None, None), "records no reference pin"),
        ((SHA_INTRO, ALL_CTRY), "was scored against capture"),
        ((SHA_CTRY, "d" * 64), "was scored against capture"),
        ((SHA_CTRY, None), "records no archive pin"),
    ],
)
def test_a_report_scored_against_other_pins_is_refused(
    repo: Repo, pins: tuple[str | None, str | None], says: str
) -> None:
    repo.report("ctry", 0.8, 0.9, pins=pins)
    repo.report("intro", 0.7, 0.9)
    assert f"ctry: the report {says}" in _refused(repo)


def test_a_report_recording_an_archive_the_row_does_not_pin_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    repo.report("intro", 0.7, 0.9, pins=(SHA_INTRO, ALL_CTRY))
    assert "intro: the report was scored against capture" in _refused(repo)


def test_a_report_of_another_class_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9, adapter=LAVAPIPE)
    repo.report("intro", 0.7, 0.9)
    assert "ctry: the report was drawn on lavapipe" in _refused(repo)


def test_a_report_without_class_losses_is_refused(repo: Repo) -> None:
    repo.report("ctry", 0.8, 0.9)
    repo.report("intro", 0.7, 0.9)
    path = repo.root / parity_layout.report_dir("intro") / "report.json"
    write_report(path, dataclasses.replace(read_report(path), mean_loss_by_class_scored=None))
    assert "intro: the report records no class losses" in _refused(repo)


def test_a_report_whose_class_names_differ_from_the_pinned_ones_is_refused(repo: Repo) -> None:
    other = {name: v for name, v in losses().items() if name != "props"} | {"ground": 0.01}
    repo.report("ctry", 0.8, 0.9, loss=other)
    repo.report("intro", 0.7, 0.9)
    says = _refused(repo)
    assert "ctry: the report's loss classes differ" in says
    assert "report only: ground" in says
    assert "pin only: props" in says


def test_clean_crates_tree_is_head_crates_only_when_clean(repo: Repo) -> None:
    assert clean_crates_tree(repo.root) == repo.tree
    repo.write("crates/new.rs", "\n")
    assert clean_crates_tree(repo.root) is None


def test_a_report_round_trips_its_crates_tree_and_pins(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_report(path, Report(per_frame=(), crates="f" * 40, sha256="a" * 64, all_sha256="b" * 64))
    report = read_report(path)
    assert (report.crates, report.sha256, report.all_sha256) == ("f" * 40, "a" * 64, "b" * 64)
    path.write_text('{"per_frame": []}', encoding="utf-8")
    legacy = read_report(path)
    assert (legacy.crates, legacy.sha256, legacy.all_sha256) == (None, None, None)


@pytest.mark.parametrize(
    ("no_build", "rescored", "recorded"),
    [(False, False, "tree"), (True, False, None), (False, True, None)],
)
def test_a_parity_run_offers_its_tree_only_when_it_built_the_binary_now(
    no_build: bool, rescored: bool, recorded: str | None
) -> None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    found = parity_run.recorded_crates(no_build=no_build, rescored=rescored, tree=lambda: "tree")
    assert found == recorded


def _render_built_from(path: Path, tree: str | None) -> Path:
    """A render directory recording *tree* as the build that made it."""
    path.mkdir(parents=True)
    write_render_tree(path, tree)
    return path


def _scored_tree(
    tmp_path: Path, built: str | None, *, no_render: bool = True, scorer_only: bool = True
) -> str | None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    render = _render_built_from(tmp_path / "render", built)
    return parity_run.scored_render_tree(
        "head", render, no_render=no_render, scorer_only=lambda _old, _new: scorer_only
    )


def test_a_fresh_render_records_the_candidate_tree(tmp_path: Path) -> None:
    assert _scored_tree(tmp_path, None, no_render=False) == "head"


def test_a_no_render_run_after_a_scorer_only_change_records_the_tree(tmp_path: Path) -> None:
    assert _scored_tree(tmp_path, "1" * 40) == "head"


def test_a_no_render_run_after_a_renderer_change_records_nothing(tmp_path: Path) -> None:
    assert _scored_tree(tmp_path, "1" * 40, scorer_only=False) is None


def test_a_render_without_a_recorded_build_records_nothing(tmp_path: Path) -> None:
    """A render from a dirty ``crates/``, a ``--no-build``, ``--reuse`` or ``--retime`` run, or an
    older run has no record, so a ``--no-render`` run cannot vouch for it."""
    assert _scored_tree(tmp_path, None) is None


def test_no_render_on_a_dirty_crates_records_nothing(tmp_path: Path) -> None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    render = _render_built_from(tmp_path / "render", "1" * 40)
    assert parity_run.scored_render_tree(None, render, no_render=True) is None


def test_an_unreadable_record_is_no_record(tmp_path: Path) -> None:
    render = _render_built_from(tmp_path / "render", "1" * 40)
    assert read_render_tree(render) == "1" * 40
    (render / RENDER_TREE_FILE).write_text("not a tree\n", encoding="ascii")
    assert read_render_tree(render) is None
    (render / RENDER_TREE_FILE).write_bytes(b"\xff\xfe")
    assert read_render_tree(render) is None
    write_render_tree(render, None)
    assert read_render_tree(render) is None
    write_render_tree(render, None)  # nothing left to remove


def test_a_scorer_only_commit_lets_a_no_render_report_be_repinned(repo: Repo) -> None:
    """End to end: a render built on the old tree, rescored after a scorer-only commit."""
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    renders = {
        film: _render_built_from(repo.root / "build" / "renders" / film, repo.tree)
        for film in ("ctry", "intro")
    }
    repo.report("ctry", 0.812345678, 0.98765432)
    repo.report("intro", 0.7, 0.9)
    repo.write(f"crates/{SCORER_DIR}score.rs", "fn score() {}\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "scorer")
    new_tree = clean_crates_tree(repo.root)
    assert new_tree not in (None, repo.tree)

    # The report still records the old tree: the repin refuses it.
    with pytest.raises(parity_repin.RepinRefusedError):
        parity_repin.repin(repo.root, "gpu")

    for film, render in renders.items():
        crates = parity_run.scored_render_tree(
            new_tree, render, no_render=True, scorer_only=repo.scorer_only
        )
        assert crates == new_tree
        repo.report(film, 0.8, 0.9, crates=crates)
    assert [t.film for t in parity_repin.repin(repo.root, "gpu")] == ["ctry", "intro"]


def test_a_renderer_commit_still_needs_a_re_render(repo: Repo) -> None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    render = _render_built_from(repo.root / "build" / "render", repo.tree)
    repo.write(f"crates/{SCORER_DIR}score.rs", "fn score() {}\n")
    repo.write("crates/a.rs", "fn a() { 1; }\n")
    repo.git("add", "-A")
    repo.git("commit", "-qm", "renderer")
    head = clean_crates_tree(repo.root)
    assert head is not None
    found = parity_run.scored_render_tree(
        head, render, no_render=True, scorer_only=repo.scorer_only
    )
    assert found is None
    reason = parity_run.unrecorded_reason(
        head, render, changes=lambda old, new: renderer_changes(old, new, repo.root)
    )
    assert reason == "crates/a.rs changed outside the scorer since the render"


def test_the_unrecorded_reason_names_a_missing_or_unreadable_record(tmp_path: Path) -> None:
    import parity_run  # noqa: PLC0415 - a script, on the path set above

    unrecorded = _render_built_from(tmp_path / "old", None)
    assert parity_run.unrecorded_reason("head", unrecorded) == "the render records no build tree"
    render = _render_built_from(tmp_path / "render", "1" * 40)
    reason = parity_run.unrecorded_reason("head", render, changes=lambda _old, _new: None)
    assert reason == "git cannot compare the render's tree 1111111 with crates/"
    reason = parity_run.unrecorded_reason("head", render, changes=lambda _old, _new: ["a", "b"])
    assert reason == "crates/a and 1 more changed outside the scorer since the render"
