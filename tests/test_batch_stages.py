"""The batch stage runners: each builds one command, runs it through an injected runner, and records the outcome.

Every test injects a fake runner, so nothing here launches DOSBox-X, MAKEONE or the stuntreel binary,
and nothing reads the corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

from stunt_reel import batch_stages
from stunt_reel.batch_films import BatchFilm


class FakeRunner:
    """Records each command and answers with a fixed exit code and output tail."""

    def __init__(self, code: int = 0, tail: str = "") -> None:
        self.code = code
        self.tail = tail
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, command: list[str], timeout: float) -> tuple[int, str]:
        self.calls.append((list(command), timeout))
        return self.code, self.tail


def _film(tmp_path: Path, *, name: str | None = None, sibling: bool = False) -> BatchFilm:
    return BatchFilm(
        slug="vault-ctry" if name is None else name,
        name=name,
        flm=tmp_path / "VAULT" / "CTRY.FLM",
        sha256="0" * 64,
        has_sibling_all=sibling,
    )


def test_archive_is_skipped_when_a_sibling_all_exists(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_archive(_film(tmp_path, sibling=True), tmp_path, runner, 900.0)
    assert record.status == "skipped"
    assert record.stage == "archive"
    assert runner.calls == []


def test_archive_command_carries_name_only_when_set(tmp_path: Path) -> None:
    plain = FakeRunner()
    batch_stages.run_archive(_film(tmp_path), tmp_path, plain, 900.0)
    command, timeout = plain.calls[0]
    assert Path(command[1]).name == "make_all.py"
    assert command[command.index("--film") + 1] == str(tmp_path / "VAULT" / "CTRY.FLM")
    assert "--name" not in command
    assert timeout == 900.0
    # make_all's own timeout fires 90 s before the runner's kill so it can tear DOSBox-X down.
    assert command[command.index("--timeout") + 1] == "810.0"

    assert command[command.index("--conf") + 1] == str(tmp_path / batch_stages.ARCHIVE_CONF)

    short = FakeRunner()
    batch_stages.run_archive(_film(tmp_path), tmp_path, short, 30.0)
    assert short.calls[0][0][short.calls[0][0].index("--timeout") + 1] == "1"

    named = FakeRunner()
    batch_stages.run_archive(_film(tmp_path, name="vault-ctry-0a1b2c3d"), tmp_path, named, 900.0)
    command, _ = named.calls[0]
    assert command[command.index("--name") + 1] == "vault-ctry-0a1b2c3d"


def test_nonzero_exit_becomes_an_error_record_with_the_output_tail(tmp_path: Path) -> None:
    runner = FakeRunner(code=1, tail="MAKEONE started\nno such shape in RES")
    record = batch_stages.run_archive(_film(tmp_path), tmp_path, runner, 900.0)
    assert record.status == "error"
    assert "exit 1" in record.message
    assert "no such shape in RES" in record.message
    assert "\n" not in record.message


def test_a_runner_exception_becomes_an_error_record(tmp_path: Path) -> None:
    def broken(_command: list[str], _timeout: float) -> tuple[int, str]:
        raise RuntimeError("DOSBox-X not found")

    record = batch_stages.run_capture(_film(tmp_path), tmp_path, broken, 900.0)
    assert record.status == "error"
    assert record.stage == "capture"
    assert "DOSBox-X not found" in record.message


def test_capture_command_uses_the_film_path(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_capture(_film(tmp_path, name="x-y"), tmp_path, runner, 900.0)
    assert record.status == "ok"
    command, _ = runner.calls[0]
    assert Path(command[1]).name == "capture_playone_reference.py"
    assert command[command.index("--film") + 1] == str(tmp_path / "VAULT" / "CTRY.FLM")
    assert command[command.index("--name") + 1] == "x-y"


def test_capture_frames_adds_the_sample_flag_only_when_positive(tmp_path: Path) -> None:
    full = FakeRunner()
    batch_stages.run_capture(_film(tmp_path), tmp_path, full, 900.0)
    assert "--sample-frames" not in full.calls[0][0]

    sampled = FakeRunner()
    batch_stages.run_capture(_film(tmp_path), tmp_path, sampled, 900.0, frames=40)
    command, _ = sampled.calls[0]
    assert command[command.index("--sample-frames") + 1] == "40"


def test_a_known_stall_is_a_skipped_capture_record(tmp_path: Path) -> None:
    record = batch_stages.skip_stalled_capture(_film(tmp_path))
    assert (record.stage, record.status) == ("capture", "skipped")
    assert record.message == "known capture stall"
    assert "amcrisis-ac" in batch_stages.KNOWN_CAPTURE_STALLS
    assert len(batch_stages.KNOWN_CAPTURE_STALLS) == 6


def test_render_without_a_capture_is_an_error_naming_capture(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_render(_film(tmp_path), tmp_path, runner, 600.0)
    assert record.status == "error"
    assert record.stage == "render"
    assert "capture" in record.message
    assert runner.calls == []


def test_score_record_carries_ssim_and_iou(tmp_path: Path) -> None:
    film = _film(tmp_path)
    capture = tmp_path / "build" / "parity" / "captures" / "vault-ctry" / "frames" / "001"
    capture.mkdir(parents=True)

    def score_writes_report(command: list[str], _timeout: float) -> tuple[int, str]:
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        document = {"per_frame": [], "mean_ssim_scored": 0.7, "mean_iou_scored": 0.9}
        (output / "report.json").write_text(json.dumps(document), encoding="utf-8")
        return 0, ""

    record = batch_stages.run_score(film, tmp_path, score_writes_report, 600.0)
    assert record.status == "ok"
    assert record.stage == "score"
    assert record.ssim == 0.7
    assert record.iou == 0.9


def test_archive_conf_differs_from_the_capture_conf_only_in_the_cpu_lines() -> None:
    tools = Path(__file__).resolve().parent.parent / "tools" / "dosbox"
    capture = (tools / "dosbox-parity.conf").read_text(encoding="utf-8").splitlines()
    archive = (tools / "dosbox-archive.conf").read_text(encoding="utf-8").splitlines()

    def body(lines: list[str]) -> list[str]:
        # Comments and the two cpu settings may differ; everything else must agree.
        return [
            line
            for line in lines
            if not line.startswith("#") and not line.startswith(("core =", "cycles ="))
        ]

    assert body(archive) == body(capture)
    assert "core = dynamic" in archive
    assert "cycles = max" in archive
    assert "core = normal" in capture
    assert "cycles = 8000" in capture
