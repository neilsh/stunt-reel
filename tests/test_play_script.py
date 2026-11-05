"""The play script stages a film, presses its keys and cleans up, without a real emulator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel import dataroot, parity_layout, references
from stunt_reel.tac import automation, playone

if TYPE_CHECKING:
    from tac_mock import StagedRepo

SCRIPT = Path(__file__).resolve().parent.parent / "python" / "scripts" / "play.py"


def _play() -> Any:
    spec = importlib.util.spec_from_file_location("play", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Emulator:
    """Stands in for DosboxAutomation: records the key script and the lifecycle."""

    instances: list[_Emulator] = []  # noqa: RUF012 - reset by each test

    def __init__(self, write_conf: Any) -> None:
        self.conf = write_conf(41234)
        self.conf_text = self.conf.read_text(encoding="utf-8")
        self.scripts: list[str] = []
        self.events: list[str] = []
        _Emulator.instances.append(self)

    def start(self) -> Any:
        emulator = self

        class Client:
            def run_script(self, text: str, *, timeout: float) -> dict[str, Any]:  # noqa: ARG002
                emulator.scripts.append(text)
                return {"done": True}

        return Client()

    def wait(self) -> int:
        self.events.append("wait")
        return 0

    def stop(self, timeout: float) -> None:  # noqa: ARG002
        self.events.append("stop")


def test_play_presses_the_film_keys_waits_and_leaves_no_stage(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 0

    (emulator,) = _Emulator.instances
    assert "cpu_cycles = 45000" in emulator.conf_text.splitlines()
    assert '"KBD_c", "KBD_down", "KBD_enter"' in emulator.scripts[0]
    assert emulator.events == ["wait", "stop"]
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


@pytest.fixture
def rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty references.toml in a stand-in checkout, so the committed rows are not read."""
    checkout = tmp_path / "references-checkout"
    pointers = checkout / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    pointers.write_text("", encoding="utf-8")
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    return pointers


def test_play_refuses_a_build_the_films_row_does_not_name(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: Path,
) -> None:
    """The staged engine is the unpatched build; the row names patch3 (ADR 0029)."""
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)
    rows.write_text('[ctry]\nfilm = "vault-ctry"\n', encoding="utf-8")

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 1
    assert _Emulator.instances == []
    assert "names patch3" in capsys.readouterr().err
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


def test_play_refuses_an_archive_made_by_a_makeone_the_row_does_not_name(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: Path,
) -> None:
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)
    monkeypatch.setattr(references, "archive_makeone_build", lambda *_a: "unpatched")
    rows.write_text(
        '[ctry]\nfilm = "vault-ctry"\nplayone = "unpatched"\nreason = "x"\n', encoding="utf-8"
    )

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 1
    assert _Emulator.instances == []
    assert "unpatched MAKEONE" in capsys.readouterr().err


def test_play_runs_a_film_with_no_row_on_any_build(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, rows: Path
) -> None:
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)
    assert rows.read_text(encoding="utf-8") == ""

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 0
    assert len(_Emulator.instances) == 1


def test_play_runs_a_film_with_no_row_on_an_unknown_playone(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, rows: Path
) -> None:
    """A film with no row is unchecked, so a PLAYONE.EXE that matches no build still plays."""
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)

    def unknown(_exe: Path) -> playone.PlayoneLayout:
        raise playone.UnknownBuild("no known build")

    monkeypatch.setattr(playone, "layout_for", unknown)
    assert rows.read_text(encoding="utf-8") == ""

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 0
    assert len(_Emulator.instances) == 1


def test_play_without_an_archive_fails_before_any_emulator(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _play()
    _Emulator.instances = []
    monkeypatch.setattr(automation, "DosboxAutomation", _Emulator)
    staged_repo.film.with_suffix(".ALL").unlink()

    assert module.run(module.parse_args(["--film", str(staged_repo.film)])) == 1
    assert _Emulator.instances == []
    assert capsys.readouterr().err.startswith("[play] ")
