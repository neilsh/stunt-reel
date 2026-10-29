"""The DOSBox-X launcher that carries the MCP server's chosen control port.

The MCP server picks its port when it starts and reports it through the
`dosbox_mcp_port` tool, so no profile can hold the port in a config file: the launch
passes it with the same command line a capture launch builds (ADR 0021). Every test
here runs offline: no DOSBox-X, no process, no socket.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ensure_dosbox  # noqa: E402

from stunt_reel import dataroot  # noqa: E402


def test_launch_passes_the_control_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The reported port reaches DOSBox-X as the same -set pair a capture build uses."""
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr("stunt_reel.tac.emulator.shutil.which", lambda _name: "dosbox-x")
    monkeypatch.setattr(
        "subprocess.Popen", lambda args, **kwargs: calls.append((list(args), kwargs))
    )
    monkeypatch.setattr(sys, "argv", ["ensure_dosbox.py", "--mcp-port", "50413"])

    assert ensure_dosbox.main() == 0
    assert calls[0][0] == [
        "dosbox-x",
        "-conf",
        str(dataroot.REPO_ROOT / "tools/dosbox/dosbox-mcp.conf"),
        "-set",
        "dosbox mcp_server=50413",
    ]
    assert calls[0][1]["cwd"] == str(dataroot.REPO_ROOT)
    assert "50413" in capsys.readouterr().out


def test_the_reported_port_is_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a port DOSBox-X would dial nothing and wedge every later launch."""
    launched: list[list[str]] = []
    monkeypatch.setattr("subprocess.Popen", lambda args, **_kwargs: launched.append(list(args)))
    monkeypatch.setattr(sys, "argv", ["ensure_dosbox.py"])

    with pytest.raises(SystemExit) as info:
        ensure_dosbox.main()
    assert info.value.code == 2
    assert launched == []
    assert "--mcp-port" in capsys.readouterr().err


def test_a_missing_emulator_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A checkout without DOSBox-X says so instead of waiting for a guest."""
    monkeypatch.setattr("stunt_reel.tac.emulator.shutil.which", lambda _name: None)
    monkeypatch.setattr(sys, "argv", ["ensure_dosbox.py", "--mcp-port", "50413"])

    assert ensure_dosbox.main() == 1
    assert "not on PATH" in capsys.readouterr().err
