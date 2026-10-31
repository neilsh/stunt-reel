"""The play script stages a film, presses its keys and cleans up, without a real emulator."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import automation

if TYPE_CHECKING:
    import pytest

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
    assert '"KBD_c", "KBD_down", "KBD_enter"' in emulator.scripts[0]
    assert emulator.events == ["wait", "stop"]
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())


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
