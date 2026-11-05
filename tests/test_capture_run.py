"""The capture run lifecycle, driven the way a person drives it: through the scripts' ``run``.

Every test starts a whole run (identity, build choice, staging, plan, swap, exit code) with a
:class:`~stunt_reel.tac.automation.MockAutomation` behind the ``launch`` seam and a temporary data
root (``staged_repo``), so no emulator starts and the corpus is never read.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from archive_helpers import build_all
from pytest_helpers import build_avi
from stunt_reel import capture_run, capture_store, dataroot, parity_layout, references
from stunt_reel.all_archive import ArchiveMeta, publish_archive
from stunt_reel.tac import automation, makeone, plan, playone
from stunt_reel.tac.emulator import EmulatorUnavailable
from tac_mock import FakeFilm, StagedRepo, load_script, makeone_launcher

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

FRAMES = "capture_playone_reference"
VIDEO = "capture_video"
VIDEO_LOG = {
    "cs": "x100",
    "log": "x101:7:0,102:7:1,103:8:2",
    "pal0": "x" + "00" * 768,
    "pal": "x",
    "end": "xhold",
    "done": True,
}


@pytest.fixture(autouse=True)
def rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty references.toml in a stand-in checkout, so the committed rows are not read."""
    checkout = tmp_path / "references-checkout"
    pointers = checkout / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    pointers.write_text("", encoding="utf-8")
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    return pointers


def _row(pointers: Path, *, playone_build: str = "patch3", makeone_build: str = "patch3") -> None:
    reason = 'reason = "x"\n' if "unpatched" in (playone_build, makeone_build) else ""
    pointers.write_text(
        f'[ctry]\nfilm = "vault-ctry"\nmakeone = "{makeone_build}"\n'
        f'playone = "{playone_build}"\n{reason}',
        encoding="utf-8",
    )


class Emulator:
    """A fake emulator behind the ``launch`` seam: what each launch staged, and what it answers."""

    def __init__(self, script: str, handler: Callable[[str], dict[str, Any]] | None = None) -> None:
        self.script = script
        self.handler = handler or (FakeFilm().handler if script == FRAMES else self._video)
        self.engines: list[bytes] = []
        self.confs: list[str] = []
        self.fail_first: list[BaseException] = []
        self.launches = 0

    def builds(self) -> list[bytes]:
        """The engines staged, in order, once each (a capture launches once per pass)."""
        return list(dict.fromkeys(self.engines))

    def _video(self, _lua: str) -> dict[str, Any]:
        recording = Path(re.search(r"capture_dir = (.+)", self.confs[-1]).group(1))  # type: ignore[union-attr]
        recording.mkdir(exist_ok=True)
        frames = [bytes([n]) * 3 for n in range(3)]
        (recording / "capture-0001.avi").write_bytes(build_avi(frames, [b"s" * 5] * 3))
        return dict(VIDEO_LOG)

    @contextmanager
    def launch(self, write_conf: Callable[[int], Path]) -> Iterator[automation.MockAutomation]:
        """The ``Launch`` a script's ``run`` takes: writes the stage's conf like a real launch."""
        self.launches += 1
        conf = write_conf(41234)
        self.confs.append(conf.read_text(encoding="utf-8"))
        self.engines.append((conf.parent / "mount" / "PLAYONE.EXE").read_bytes())
        if self.fail_first:
            raise self.fail_first.pop(0)
        yield automation.MockAutomation(self.handler)


def _run(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    emulator: Emulator,
    *extra: str,
    out: Path | None = None,
) -> int:
    module = load_script(script)
    argv = [f"{script}.py", "--film", str(staged_repo.film)]
    if out is not None:
        argv += ["--out", str(out)]
    monkeypatch.setattr(sys, "argv", [*argv, *extra])
    return int(module.run(module.parse_args(), launch=emulator.launch))


def _store(kind: str, slug: str = "vault-ctry") -> Path:
    paths = {"frames": parity_layout.frames_path, "video": parity_layout.video_path}
    return dataroot.data_root() / paths[kind](slug)


def _stage_is_empty() -> bool:
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    return not stage_root.exists() or not any(stage_root.iterdir())


def _kind(script: str) -> str:
    return "frames" if script == FRAMES else "video"


BOTH = pytest.mark.parametrize("script", [FRAMES, VIDEO])


# ==============================================================================
# One run, both capture kinds
# ==============================================================================


@BOTH
def test_a_default_run_stages_patch3_and_replaces_the_films_capture(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    emulator = Emulator(script)
    store = _store(_kind(script))

    assert _run(script, staged_repo, monkeypatch, emulator) == 0
    assert _run(script, staged_repo, monkeypatch, emulator) == 0

    assert emulator.builds() == [b"patch3 PLAYONE.EXE"]
    assert capture_store.current(store) == store
    assert [p.name for p in store.parent.iterdir() if p.suffix != ".lock"] == [store.name]
    assert _stage_is_empty()


@BOTH
def test_a_run_records_when_and_by_whom_and_the_engine_it_ran(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(script, staged_repo, monkeypatch, Emulator(script)) == 0

    meta = json.loads((_store(_kind(script)) / "meta.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d\d-\d\d", meta["captured_on"])
    assert meta["checkout"] == "stunt-reel"
    # The synthetic executable matches no build's hash; the fixture reads it as the unpatched one.
    assert (meta["playone_build"], meta["playone_sha256"]) == (
        playone.UNPATCHED.name,
        playone.UNPATCHED.sha256,
    )


@BOTH
@pytest.mark.parametrize(
    ("error", "code", "line"),
    [
        (EmulatorUnavailable("not installed"), 1, "not installed; run via mise run"),
        (automation.ScriptError("instruction limit exceeded"), 1, "instruction limit exceeded"),
        (plan.PlanDivergence("drifted"), 1, "drifted"),
        (TimeoutError("took too long"), 1, "took too long"),
        (RuntimeError("boom"), 1, "boom"),
        (OSError("disk"), 1, "disk"),
    ],
)
def test_the_stage_is_removed_on_every_failure_path(
    script: str,
    error: BaseException,
    code: int,
    line: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    emulator = Emulator(script)
    emulator.fail_first = [error]
    # --game-root, so the single failure is not retried on the unpatched build.
    tree = dataroot.data_root() / "builds" / "patch3"

    assert _run(script, staged_repo, monkeypatch, emulator, "--game-root", str(tree)) == code

    assert line in capsys.readouterr().err
    assert emulator.launches == 1
    assert _stage_is_empty()
    assert not _store(_kind(script)).exists()


@BOTH
def test_a_failed_run_keeps_the_old_capture_and_leaves_nothing_beside_it(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(script, staged_repo, monkeypatch, Emulator(script)) == 0
    store = _store(_kind(script))
    before = (store / "meta.json").stat().st_mtime_ns
    failing = Emulator(script)
    failing.fail_first = [RuntimeError("boom")]
    tree = dataroot.data_root() / "builds" / "patch3"

    assert _run(script, staged_repo, monkeypatch, failing, "--game-root", str(tree)) == 1

    assert (store / "meta.json").stat().st_mtime_ns == before
    assert [p.name for p in store.parent.iterdir() if p.suffix != ".lock"] == [store.name]


def test_replacing_a_capture_leaves_no_stale_digest(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process that digested the old capture must not validate the old pin after the swap."""
    store = _store("frames")
    assert _run(FRAMES, staged_repo, monkeypatch, Emulator(FRAMES)) == 0
    old = references.capture_digest(store)

    assert (
        _run(
            FRAMES, staged_repo, monkeypatch, Emulator(FRAMES, FakeFilm(moving_frames=300).handler)
        )
        == 0
    )

    assert references.capture_digest(store) != old
    assert references.capture_digest(store) == references.capture_digest(store)


@BOTH
def test_a_non_empty_out_is_never_written_over_and_the_store_is_untouched(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    (out / "meta.json").write_text("{}", encoding="utf-8")
    emulator = Emulator(script)

    assert _run(script, staged_repo, monkeypatch, emulator, out=out) == 2

    assert emulator.launches == 0
    assert (out / "meta.json").read_text(encoding="utf-8") == "{}"
    assert _stage_is_empty()


@BOTH
def test_out_writes_there_and_replaces_nothing(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = tmp_path / "out"

    assert _run(script, staged_repo, monkeypatch, Emulator(script), out=out) == 0

    assert (out / "meta.json").is_file()
    assert not _store(_kind(script)).exists()


@BOTH
def test_an_out_inside_the_store_is_refused(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    inside = dataroot.data_root() / parity_layout.capture_root() / "somewhere"
    emulator = Emulator(script)

    assert _run(script, staged_repo, monkeypatch, emulator, out=inside) == 2
    assert emulator.launches == 0


def test_the_leftovers_of_a_run_that_died_are_cleared(tmp_path: Path) -> None:
    """Rasters without a meta.json are no capture: the same directory can be retried (ADR 0022)."""
    out = tmp_path / "out"
    (out / "frames").mkdir(parents=True)
    (out / "frames" / "tick_0001.idx").write_bytes(b"\x00")
    (out / "tick_0002.idx").write_bytes(b"\x00")
    (out / "palettes_0001.json").write_text("{}", encoding="utf-8")
    (out / "frames" / "notes.txt").write_text("mine", encoding="utf-8")
    assert capture_run.is_taken(out)  # a file that is not ours keeps the directory taken
    assert (out / "frames" / "notes.txt").read_text(encoding="utf-8") == "mine"
    assert not list((out / "frames").glob("tick_*"))
    (out / "frames" / "notes.txt").unlink()
    assert not capture_run.is_taken(out)
    assert list(out.iterdir()) == []
    (out / "tick_0001.idx").write_bytes(b"\x00")
    (out / "meta.json").write_text("{}", encoding="utf-8")
    assert capture_run.is_taken(out)
    assert (out / "tick_0001.idx").exists()


@BOTH
def test_name_overrides_the_slug_and_a_bad_one_is_refused(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _run(script, staged_repo, monkeypatch, Emulator(script), "--name", "Bad Name") == 2
    assert not _store(_kind(script), "Bad Name").exists()


@BOTH
def test_a_film_with_no_archive_names_make_all_and_starts_nothing(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_repo.film.with_suffix(".ALL").unlink()
    emulator = Emulator(script)

    assert _run(script, staged_repo, monkeypatch, emulator) == 2

    assert "mise run make-all -- --film" in capsys.readouterr().err
    assert emulator.launches == 0


@BOTH
def test_a_missing_film_is_refused(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    staged_repo.film.unlink()

    assert _run(script, staged_repo, monkeypatch, Emulator(script)) == 2
    assert "not found" in capsys.readouterr().err


def _stored_archive(staged_repo: StagedRepo, data: bytes, slug: str = "vault-ctry") -> None:
    """Remove the film's sibling archive and store *data* as the generated one for its hash."""
    staged_repo.film.with_suffix(".ALL").unlink()
    flm = staged_repo.film.read_bytes()
    meta = ArchiveMeta(
        film=staged_repo.film.name,
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(data),
        all_sha256=hashlib.sha256(data).hexdigest(),
    )
    publish_archive(dataroot.data_root(), data, meta, slug=slug, film=staged_repo.film.name)


def test_a_capture_plays_the_stored_archive_and_records_its_hash(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored = build_all([b"stored"])
    _stored_archive(staged_repo, stored)
    played: list[bytes] = []
    emulator = Emulator(FRAMES)
    real = emulator.launch

    @contextmanager
    def launch(write_conf: Callable[[int], Path]) -> Iterator[automation.MockAutomation]:
        played.append((write_conf(1).parent / "mount" / "VAULT" / "CTRY.ALL").read_bytes())
        with real(write_conf) as runner:
            yield runner

    emulator.launch = launch  # type: ignore[method-assign]

    assert _run(FRAMES, staged_repo, monkeypatch, emulator) == 0

    assert set(played) == {stored}
    meta = json.loads((_store("frames") / "meta.json").read_text(encoding="utf-8"))
    assert meta["all_sha256"] == hashlib.sha256(stored).hexdigest()


def test_name_also_selects_where_the_stored_archive_is_looked_up(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stored_archive(staged_repo, build_all([b"named"]), slug="my-ctry")

    assert _run(FRAMES, staged_repo, monkeypatch, Emulator(FRAMES), "--name", "my-ctry") == 0
    assert (_store("frames", "my-ctry") / "meta.json").is_file()
    assert _run(FRAMES, staged_repo, monkeypatch, Emulator(FRAMES)) == 2


# ==============================================================================
# Build choice (ADR 0029)
# ==============================================================================


@BOTH
def test_the_films_row_chooses_the_build(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, rows: Path
) -> None:
    _row(rows, playone_build="unpatched")
    emulator = Emulator(script)
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "patch3")

    assert _run(script, staged_repo, monkeypatch, emulator) == 0
    assert emulator.builds() == [b"unpatched PLAYONE.EXE"]


@BOTH
def test_a_game_root_that_the_row_does_not_name_is_refused_before_the_emulator(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: Path,
) -> None:
    """The row names patch3 and the engine reads as the unpatched build (the fixture's layout)."""
    _row(rows, playone_build="patch3")
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "patch3")
    emulator = Emulator(script)

    assert _run(script, staged_repo, monkeypatch, emulator) == 2

    assert "names patch3" in capsys.readouterr().err
    assert emulator.launches == 0
    assert _stage_is_empty()


@BOTH
def test_an_archive_whose_build_cannot_be_determined_is_refused(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: Path,
) -> None:
    _row(rows, playone_build="unpatched")
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: references.UNKNOWN_BUILD)
    emulator = Emulator(script)

    assert _run(script, staged_repo, monkeypatch, emulator) == 2

    assert "cannot be determined" in capsys.readouterr().err
    assert emulator.launches == 0


@BOTH
def test_a_missing_build_tree_names_the_task_that_makes_it(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (dataroot.data_root() / "builds" / "patch3" / "PLAYONE.EXE").unlink()

    assert _run(script, staged_repo, monkeypatch, Emulator(script)) == 2
    assert "mise run game-builds" in capsys.readouterr().err


@BOTH
def test_game_root_overrides_the_chosen_build(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    emulator = Emulator(script)
    tree = dataroot.data_root() / "builds" / "unpatched"

    assert _run(script, staged_repo, monkeypatch, emulator, "--game-root", str(tree)) == 0
    assert emulator.builds() == [b"unpatched PLAYONE.EXE"]


@BOTH
def test_a_stall_on_patch3_retries_on_unpatched_and_suggests_the_row(
    script: str,
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    emulator = Emulator(script)
    emulator.fail_first = [automation.ScriptError("instruction limit exceeded")]

    assert _run(script, staged_repo, monkeypatch, emulator) == 0

    assert emulator.builds() == [b"patch3 PLAYONE.EXE", b"unpatched PLAYONE.EXE"]
    captured = capsys.readouterr()
    assert "patch3 stalled (instruction limit exceeded); retrying on the unpatched build" in (
        captured.err
    )
    assert '[vault-ctry]\nfilm = "vault-ctry"\nplayone = "unpatched"\nreason = "' in captured.out
    assert "makeone" not in captured.out.split("[vault-ctry]")[1]
    assert capture_store.current(_store(_kind(script))) is not None
    assert _stage_is_empty()


@BOTH
def test_a_stall_on_both_builds_fails_and_stores_nothing(
    script: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    emulator = Emulator(script)
    emulator.fail_first = [RuntimeError("stalled"), RuntimeError("stalled again")]

    assert _run(script, staged_repo, monkeypatch, emulator) == 1

    assert emulator.launches == 2
    assert not _store(_kind(script)).exists()
    assert _stage_is_empty()


@pytest.mark.parametrize(
    "why",
    ["row", "game-root", "out", "drift", "no-emulator"],
)
def test_the_fallback_is_only_for_a_stall_of_a_default_run_of_a_film_with_no_row(
    why: str, staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, rows: Path, tmp_path: Path
) -> None:
    emulator = Emulator(FRAMES)
    emulator.fail_first = [RuntimeError("stalled")]
    extra: list[str] = []
    out: Path | None = None
    if why == "row":
        _row(rows, playone_build="patch3")
        monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "patch3")
        monkeypatch.setattr(playone, "layout_for", lambda _exe: playone.PATCH3)
    elif why == "game-root":
        extra = ["--game-root", str(dataroot.data_root() / "builds" / "patch3")]
    elif why == "out":
        out = tmp_path / "out"
    elif why == "drift":
        emulator.fail_first = [plan.PlanDivergence("drifted")]
    else:
        emulator.fail_first = [EmulatorUnavailable("not installed")]

    assert _run(FRAMES, staged_repo, monkeypatch, emulator, *extra, out=out) == 1
    assert emulator.launches == 1


# ==============================================================================
# The video capture's own output
# ==============================================================================


def test_a_video_run_files_the_stripped_avi_and_a_meta_naming_the_film(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(VIDEO, staged_repo, monkeypatch, Emulator(VIDEO)) == 0

    store = _store("video")
    assert b"01wb" not in (store / "capture.avi").read_bytes()
    meta = json.loads((store / "meta.json").read_text(encoding="utf-8"))
    assert meta["film"]["name"] == "CTRY.FLM"
    assert meta["film"]["all_sha256"] == hashlib.sha256(b"ALL").hexdigest()
    out = capsys.readouterr().out
    assert "[capture-video] recorded 3 frames (hold), film starts at frame 103" in out
    assert f"[capture-video] replaced the capture in {store}" in out


def test_a_video_run_with_a_recording_that_cannot_be_used_fails_cleanly(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    emulator = Emulator(VIDEO, lambda _lua: dict(VIDEO_LOG))  # no .avi is ever written

    tree = dataroot.data_root() / "builds" / "patch3"
    assert _run(VIDEO, staged_repo, monkeypatch, emulator, "--game-root", str(tree)) == 1

    assert "no .avi" in capsys.readouterr().err
    assert not _store("video").exists()
    assert _stage_is_empty()


# ==============================================================================
# Frame capture: the script keeps its progress lines and refusals
# ==============================================================================


def test_a_frame_run_reports_its_progress_and_what_it_stored(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(FRAMES, staged_repo, monkeypatch, Emulator(FRAMES)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("[capture] pass 1") for line in lines)
    assert re.fullmatch(r"\[capture\] captured \d+ frames into .*\.partial-\w+", lines[-2])
    assert lines[-1] == f"[capture] replaced the capture in {_store('frames')}"


def test_a_frame_run_that_captures_no_frames_fails_and_replaces_nothing(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The film's clock never runs, so no window finds a frame.
    emulator = Emulator(FRAMES, FakeFilm(tick_step=0).handler)
    tree = dataroot.data_root() / "builds" / "patch3"

    assert _run(FRAMES, staged_repo, monkeypatch, emulator, "--game-root", str(tree)) == 1

    assert capsys.readouterr().err.startswith("[capture] ")
    assert not _store("frames").exists()


# ==============================================================================
# make-all
# ==============================================================================

ARCHIVE = build_all([b"one", b"two"])


@pytest.fixture
def _fast_makeone(monkeypatch: pytest.MonkeyPatch) -> None:
    """MAKEONE's real poll interval is 2 s per wait; the mock guest answers at once."""
    monkeypatch.setattr(makeone, "make_all", functools.partial(makeone.make_all, poll=0.0))


@pytest.mark.usefixtures("_fast_makeone")
def test_make_all_runs_the_chosen_builds_makeone_and_records_that_tree_in_the_manifest(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    launch, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    module = load_script("make_all")
    monkeypatch.setattr(sys, "argv", ["make_all.py", "--film", str(staged_repo.film)])
    seen: list[tuple[Any, ...]] = []
    monkeypatch.setattr(module, "extract_with_binary", lambda *call: seen.append(call))

    assert module.run(module.parse_args(), launch) == 0

    stored = capture_store.current(dataroot.data_root() / parity_layout.archive_path("vault-ctry"))
    assert stored is not None
    assert (stored / "CTRY.ALL").read_bytes() == ARCHIVE
    assert [call[2] for call in seen] == ["builds/patch3"]
    assert capture_store.current(stored) == stored


@pytest.mark.usefixtures("_fast_makeone")
def test_make_all_retries_a_makeone_that_wrote_no_archive_on_the_unpatched_build(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_script("make_all")
    monkeypatch.setattr(module, "extract_with_binary", lambda *_call: None)
    monkeypatch.setattr(sys, "argv", ["make_all.py", "--film", str(staged_repo.film)])
    trees: list[str] = []
    good, _state = makeone_launcher(text_after=1, archive=ARCHIVE)
    bad, _bad_state = makeone_launcher(text_after=1, archive=None)

    def launch(staged: Any) -> Any:
        trees.append((staged.mount / "MAKEONE.EXE").read_bytes().decode())
        return (bad if len(trees) == 1 else good)(staged)

    assert module.run(module.parse_args(), launch) == 0

    assert trees == ["patch3 MAKEONE.EXE", "unpatched MAKEONE.EXE"]
    captured = capsys.readouterr()
    assert 'makeone = "unpatched"' in captured.out
    assert "playone" not in captured.out.split("[vault-ctry]")[1]
