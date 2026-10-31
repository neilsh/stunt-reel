"""The dosbox-automation REST client and process wrapper, against a fake HTTP server."""

from __future__ import annotations

import json
import subprocess
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from stunt_reel.tac import automation
from stunt_reel.tac.emulator import EmulatorUnavailable, GuestTimeout

if TYPE_CHECKING:
    from collections.abc import Iterator

TOKEN = "t" * 64
REPO = Path(__file__).resolve().parent.parent


class Fake:
    """A fake dosbox-automation server: records requests, scripts the status replies."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str], bytes]] = []
        self.statuses: list[dict[str, Any]] = [{"state": "completed", "output": {}}]
        self.server: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        assert self.server is not None
        return int(self.server.server_address[1])


@pytest.fixture
def fake() -> Iterator[Fake]:
    state = Fake()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            state.requests.append((self.command, self.path, dict(self.headers), body))
            if self.path.endswith("/script/status"):
                reply = state.statuses.pop(0) if len(state.statuses) > 1 else state.statuses[0]
            else:
                reply = {"ok": True}
            data = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = _serve  # noqa: N815

        def log_message(self, *args: object) -> None:
            pass

    state.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=state.server.serve_forever, daemon=True)
    thread.start()
    yield state
    state.server.shutdown()
    state.server.server_close()


def _client(fake: Fake) -> automation.AutomationClient:
    return automation.AutomationClient(fake.port, TOKEN)


def test_every_request_carries_the_bearer_token(fake: Fake) -> None:
    _client(fake).info()

    _method, path, headers, _body = fake.requests[0]
    assert path == "/api/v1/dosbox/info"
    assert headers["Authorization"] == f"Bearer {TOKEN}"


def test_run_script_loads_text_plain_starts_and_returns_the_output(fake: Fake) -> None:
    fake.statuses = [
        {"state": "running"},
        {"state": "completed", "output": {"trace": "x1:2:0", "done": True}},
    ]

    out = _client(fake).run_script("print(1)", timeout=60, poll=0, sleep=lambda _s: None)

    assert out == {"trace": "x1:2:0", "done": True}
    load, start, *_ = fake.requests
    assert (load[0], load[1], load[3]) == ("POST", "/api/v1/script/load", b"print(1)")
    assert load[2]["Content-Type"] == "text/plain"
    assert (start[0], start[1]) == ("POST", "/api/v1/script/start")
    assert [r[1] for r in fake.requests].count("/api/v1/script/status") == 2


def test_a_script_error_carries_the_emulator_text(fake: Fake) -> None:
    fake.statuses = [{"state": "error", "error": "instruction limit exceeded"}]

    with pytest.raises(automation.ScriptError, match="instruction limit exceeded"):
        _client(fake).run_script("x", timeout=60, poll=0, sleep=lambda _s: None)


def test_a_run_over_budget_is_a_guest_timeout(fake: Fake) -> None:
    fake.statuses = [{"state": "running"}]
    now = iter(range(0, 1000, 100))

    with pytest.raises(GuestTimeout, match="30"):
        _client(fake).run_script(
            "x", timeout=30, poll=0, sleep=lambda _s: None, clock=lambda: float(next(now))
        )


def test_shutdown_posts_the_control_endpoint(fake: Fake) -> None:
    _client(fake).shutdown()

    assert fake.requests[-1][:2] == ("POST", "/api/v1/control/shutdown")


class FakeProcess:
    def __init__(self, exit_code: int | None) -> None:
        self.exit_code = exit_code
        self.killed = False

    def poll(self) -> int | None:
        return self.exit_code

    def terminate(self) -> None:
        self.exit_code = 0

    def kill(self) -> None:
        self.killed = True
        self.exit_code = -9

    def wait(self, timeout: float | None = None) -> int:  # noqa: ARG002
        if self.exit_code is None:
            self.exit_code = 0
        return self.exit_code


def _wrapper(
    tmp_path: Path,
    processes: list[FakeProcess],
    ports: list[int],
    seen: list[dict[str, Any]],
) -> automation.DosboxAutomation:
    def spawn(argv: list[str], env: dict[str, str]) -> FakeProcess:
        seen.append({"argv": argv, "token": env["DOSBOX_API_TOKEN"]})
        return processes.pop(0)

    def write_conf(port: int) -> Path:
        conf = tmp_path / f"{port}.conf"
        conf.write_text(f"webserver_port = {port}\n", encoding="utf-8")
        return conf

    return automation.DosboxAutomation(
        write_conf,
        exe="dosbox.exe",
        spawn=spawn,
        pick_port=lambda: ports.pop(0),
        sleep=lambda _s: None,
        launch_timeout=5,
    )


def test_start_passes_a_fresh_token_in_the_environment_only(tmp_path: Path, fake: Fake) -> None:
    seen: list[dict[str, Any]] = []
    wrapper = _wrapper(tmp_path, [FakeProcess(None)], [fake.port], seen)

    client = wrapper.start()

    assert len(seen[0]["token"]) == 64
    assert seen[0]["token"] not in " ".join(seen[0]["argv"])
    assert seen[0]["argv"][:2] == ["dosbox.exe", "-conf"]
    client.info()
    assert fake.requests[-1][2]["Authorization"] == f"Bearer {seen[0]['token']}"


def test_a_lost_port_race_retries_on_a_new_port(tmp_path: Path, fake: Fake) -> None:
    seen: list[dict[str, Any]] = []
    wrapper = _wrapper(
        tmp_path, [FakeProcess(1), FakeProcess(None)], [fake.port + 1, fake.port], seen
    )

    wrapper.start()

    assert len(seen) == 2
    assert (tmp_path / f"{fake.port}.conf").is_file()


def test_a_server_that_never_answers_is_a_guest_timeout(tmp_path: Path) -> None:
    dead_port = 9  # discard: nothing listens
    process = FakeProcess(None)
    now = iter(range(0, 1000, 2))
    wrapper = automation.DosboxAutomation(
        lambda _port: tmp_path / "x.conf",
        exe="dosbox.exe",
        spawn=lambda _argv, _env: process,
        pick_port=lambda: dead_port,
        sleep=lambda _s: None,
        clock=lambda: float(next(now)),
        launch_timeout=5,
    )

    with pytest.raises(GuestTimeout):
        wrapper.start()
    assert process.killed


def test_stop_shuts_down_then_waits(tmp_path: Path, fake: Fake) -> None:
    process = FakeProcess(None)
    wrapper = _wrapper(tmp_path, [process], [fake.port], [])
    wrapper.start()

    wrapper.stop(1.0)

    assert fake.requests[-1][:2] == ("POST", "/api/v1/control/shutdown")
    assert not process.killed
    assert wrapper.exit_status == 0


def test_stop_kills_a_process_that_ignores_shutdown(tmp_path: Path, fake: Fake) -> None:
    class Stubborn(FakeProcess):
        def wait(self, timeout: float | None = None) -> int:
            if not self.killed:
                raise subprocess.TimeoutExpired("dosbox", timeout or 0)
            return -9

    process = Stubborn(None)
    wrapper = _wrapper(tmp_path, [process], [fake.port], [])
    wrapper.start()

    wrapper.stop(0.1)

    assert process.killed


def test_the_executable_comes_from_the_environment_then_the_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(automation.EXE_ENV, str(tmp_path / "custom.exe"))
    assert automation.dosbox_executable() == str(tmp_path / "custom.exe")

    monkeypatch.delenv(automation.EXE_ENV)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(EmulatorUnavailable, match="dosbox-automation"):
        automation.dosbox_executable()


def test_mock_automation_returns_canned_output_and_records_scripts() -> None:
    mock = automation.MockAutomation(lambda lua: {"trace": "x1:2:0", "n": len(lua)})

    out = mock.run_script("abc", timeout=1)

    assert out == {"trace": "x1:2:0", "n": 3}
    assert mock.scripts == ["abc"]


def test_free_port_returns_a_bindable_port() -> None:
    port = automation.free_port()

    assert 1024 <= port <= 65535


def test_mise_pins_dosbox_automation_with_a_checksum() -> None:
    mise = tomllib.loads((REPO / "mise.toml").read_text(encoding="utf-8"))

    pin = mise["tools"]["github:dosbox-automation/dosbox-automation"]
    assert pin["version"] == "0.85.1"
    assert pin["checksum"].startswith("sha256:")
