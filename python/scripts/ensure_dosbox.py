"""Launch DOSBox-X dialling the control port the MCP server chose.

The MCP server binds its own control port when it starts and reports it through the
`dosbox_mcp_port` tool, so no profile can hold that port in a config file: this
script passes the reported port to DOSBox-X with the same command line a capture
launch builds (ADR 0021). Start the MCP server, ask it for the port, then run this.

Each launch dials the port it is given, so nothing is reused: run this once per
debugger session, and close the window before starting another.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from stunt_reel import dataroot
from stunt_reel.tac.emulator import EmulatorUnavailable, dosbox_executable, launch_argv

#: The interactive profile: mounts the corpus and leaves the shell for the debugger.
DEFAULT_CONF: Path = Path("tools/dosbox/dosbox-mcp.conf")

#: DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP, so DOSBox-X outlives this task.
_WINDOWS_DETACHED: int = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--mcp-port",
        type=int,
        required=True,
        help="the port the MCP server reported through dosbox_mcp_port",
    )
    return parser.parse_args()


def launch(port: int) -> str:
    """Start DOSBox-X detached, dialling port, and return the executable started."""
    exe = dosbox_executable()
    argv = launch_argv(exe, dataroot.REPO_ROOT / DEFAULT_CONF, port)
    cwd = str(dataroot.REPO_ROOT)
    if os.name == "nt":
        subprocess.Popen(  # noqa: S603
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_WINDOWS_DETACHED,
        )
    else:
        subprocess.Popen(  # noqa: S603
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return exe


def main() -> int:
    """Launch DOSBox-X for the debugger, or report why it could not."""
    args = parse_args()
    try:
        exe = launch(args.mcp_port)
    except EmulatorUnavailable as exc:
        print(f"[dosbox] {exc}; run mise install first", file=sys.stderr)
        return 1
    print(f"[dosbox] launched {exe} on control port {args.mcp_port}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
