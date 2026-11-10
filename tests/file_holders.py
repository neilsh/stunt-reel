"""Name the processes holding a file, for a test that failed with ``PermissionError`` on Windows.

The gate on Windows has failed now and then with a ``PermissionError`` on a file no test held,
and a rerun passed (docs/development.md, "A PermissionError on Windows"). The Restart Manager
lists a file's holders without admin rights, but only while they still hold it, so the failure
report asks at once.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

#: Restart Manager's ERROR_MORE_DATA: the holder list did not fit the buffer.
_MORE_DATA = 234


def holders(path: str) -> list[str]:
    """``"<pid> <name>"`` for each process holding *path* open; empty off Windows or on error."""
    # The Windows code sits in a platform branch that returns nothing, so mypy analysing for
    # either platform finds no unreachable statement.
    found: list[str] = []
    if sys.platform == "win32":
        import ctypes  # noqa: PLC0415 - only needed on Windows
        from ctypes import wintypes  # noqa: PLC0415 - only needed on Windows

        class UniqueProcess(ctypes.Structure):
            _fields_ = (  # type: ignore[mutable-override] # a tuple, as ctypes reads it
                ("pid", wintypes.DWORD),
                ("start", wintypes.FILETIME),
            )

        class ProcessInfo(ctypes.Structure):
            _fields_ = (  # type: ignore[mutable-override] # a tuple, as ctypes reads it
                ("process", UniqueProcess),
                ("app", wintypes.WCHAR * 256),
                ("service", wintypes.WCHAR * 64),
                ("kind", ctypes.c_int),
                ("status", wintypes.DWORD),
                ("session", wintypes.DWORD),
                ("restartable", wintypes.BOOL),
            )

        rm = ctypes.WinDLL("rstrtmgr")
        session = wintypes.DWORD()
        key = ctypes.create_unicode_buffer(64)
        if rm.RmStartSession(ctypes.byref(session), 0, key) == 0:
            try:
                files = (wintypes.LPCWSTR * 1)(path)
                if rm.RmRegisterResources(session, 1, files, 0, None, 0, None) == 0:
                    needed, count, reasons = wintypes.UINT(), wintypes.UINT(0), wintypes.DWORD()
                    code = rm.RmGetList(
                        session,
                        ctypes.byref(needed),
                        ctypes.byref(count),
                        None,
                        ctypes.byref(reasons),
                    )
                    if code == _MORE_DATA:
                        info = (ProcessInfo * needed.value)()
                        count = wintypes.UINT(needed.value)
                        code = rm.RmGetList(
                            session,
                            ctypes.byref(needed),
                            ctypes.byref(count),
                            info,
                            ctypes.byref(reasons),
                        )
                        if code == 0:
                            found = [f"{p.process.pid} {p.app}" for p in info[: count.value]]
            finally:
                rm.RmEndSession(session)
    return found


def _paths(error: BaseException) -> list[str]:
    """The paths of each ``PermissionError`` in *error*'s cause and context chain."""
    paths: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PermissionError):
            paths.extend(str(name) for name in (current.filename, current.filename2) if name)
        current = current.__cause__ or current.__context__
    return paths


def describe(error: BaseException, lookup: Callable[[str], list[str]] | None = None) -> str | None:
    """Who holds each file a ``PermissionError`` in *error* names, or ``None`` when none does.

    *lookup* finds a path's holders, ``holders`` by default.
    """
    paths = _paths(error)
    if not paths:
        return None
    lines = []
    for path in paths:
        held = (lookup or holders)(path)
        who = ", ".join(held) if held else "no process now (released, or pending delete)"
        lines.append(f"{path}: held by {who}")
    return "\n".join(lines)
