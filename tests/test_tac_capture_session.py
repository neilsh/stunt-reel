"""Offline tests for the capture session: a whole run driven by the mock emulator.

Covers the move from the old script-owned loop (dialog settle, BDA confirmation,
trap, sampling, teardown) to run_session plus the capture sampler: artifact bytes,
meta ordering, the clock-hold stop, lazy/stale pages, palette fallback, granular
errors, staging, the shared-write gate and the emulator lifecycle. DOSBox-X is
never launched and port 58991 is never bound.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import dataroot
from stunt_reel.dataroot import SharedWriteError
from stunt_reel.tac import staging
from stunt_reel.tac.emulator import (
    EMULATOR_STOP_SECONDS,
    DosboxX,
    EmulatorUnavailable,
    Launching,
    MockEmulator,
    PortTaken,
    WaitingForGuest,
)
from stunt_reel.tac.framebuffer import capture
from stunt_reel.tac.palette import MODE_13H_PALETTE
from stunt_reel.tac.playone import DGROUP_RUNTIME_SEG
from stunt_reel.tac.session import (
    DialogSettled,
    DialogUnsettled,
    Page,
    Session,
    ShortDump,
    StalePage,
    run_session,
)
from stunt_reel.tac.staging import ENGINE_FILES
from stunt_reel.tac.transport import FRAME_BYTES, ListenTransport, MockTransport, Transport
from tac_mock import (
    FILM_COLORS,
    CaptureGuest,
    StagedRepo,
    capture_emulator,
    fake_guest,
    free_port,
)

#: Dumps the capture guest's boot sequence and settled dialog take.
SETTLE_DUMPS: int = 9
FILM_META: dict[str, Any] = {"film": "CTRY.FLM", "flm_bytes": 19, "flm_sha256": "0" * 64}


def _run_capture(
    repo: StagedRepo,
    emulator: MockEmulator,
    *,
    max_frames: int = 3,
    dgroup_segment: int = DGROUP_RUNTIME_SEG,
    extra_meta: dict[str, Any] | None = FILM_META,
) -> dict[str, Any]:
    return run_session(
        repo.film,
        repo.out,
        sample=lambda session: capture(session, repo.out, max_frames, extra_meta=extra_meta),
        conf=repo.conf,
        dgroup_segment=dgroup_segment,
        emulator=emulator,
    )


# ==============================================================================
# Capture artifacts
# ==============================================================================


@pytest.mark.parametrize("dgroup_segment", [DGROUP_RUNTIME_SEG, 0x2000])
def test_capture_tags_frames_with_film_and_global_ticks(
    staged_repo: StagedRepo, dgroup_segment: int
) -> None:
    """Every captured frame carries the film clock and global tick read at the trap."""
    guest = CaptureGuest(dgroup_segment)
    emulator = MockEmulator(guest.mock)

    meta = _run_capture(staged_repo, emulator, dgroup_segment=dgroup_segment)

    frames = meta["frames"]
    assert [f["ordinal"] for f in frames] == [1, 2, 3]
    # Hit 1 was the load screen; frames come from hits 2..4.
    assert [f["film_tick"] for f in frames] == [106, 109, 112]
    assert [f["global_tick"] for f in frames] == [101, 104, 107]
    assert [f["frame_file"] for f in frames] == [
        "tick_0001.idx",
        "tick_0002.idx",
        "tick_0003.idx",
    ]
    assert meta["palette_source"] == "dacpal"
    assert meta["dgroup_segment"] == f"{dgroup_segment:04X}"

    on_disk = json.loads((staged_repo.out / "meta.json").read_text(encoding="utf-8"))
    assert on_disk == meta


def test_capture_artifacts_keep_their_contract(staged_repo: StagedRepo) -> None:
    """Frame bytes, palette JSON and meta key order are the capture contract."""
    meta = _run_capture(staged_repo, capture_emulator())

    assert list(meta) == [
        "film",
        "flm_bytes",
        "flm_sha256",
        "frames",
        "palette_source",
        "dgroup_segment",
        "frame_bytes",
        "width",
        "height",
    ]
    assert list(meta["frames"][0]) == [
        "ordinal",
        "film_tick",
        "global_tick",
        "vga_start",
        "frame_file",
        "palette_file",
        "distinct_indices",
    ]

    expected_page = bytes((i * 7 + 2) % FILM_COLORS for i in range(FRAME_BYTES))
    assert (staged_repo.out / "tick_0001.idx").read_bytes() == expected_page
    palette = json.loads((staged_repo.out / "palettes_0001.json").read_text(encoding="utf-8"))
    assert palette == [[255, 0, 0]] * 256
    meta_text = (staged_repo.out / "meta.json").read_text(encoding="utf-8")
    assert json.dumps(json.loads(meta_text), indent=2) == meta_text
    assert meta_text == json.dumps(meta, indent=2)


def test_meta_is_written_last(staged_repo: StagedRepo) -> None:
    """A short dump during sampling leaves the frames but never a meta.json."""
    guest = CaptureGuest()
    original = guest.dump
    calls = {"n": 0}

    def failing_dump() -> bytes:
        calls["n"] += 1
        if calls["n"] == SETTLE_DUMPS + 3:
            return b"\x00" * 10
        return original()

    guest.mock.dump_source = failing_dump
    emulator = MockEmulator(guest.mock)

    with pytest.raises(ShortDump):
        _run_capture(staged_repo, emulator)

    assert (staged_repo.out / "tick_0001.idx").is_file()
    assert not (staged_repo.out / "meta.json").exists()
    assert emulator.stopped


def test_clock_hold_stops_capture(staged_repo: StagedRepo) -> None:
    """Three consecutive frames at one film clock end the capture."""
    guest = CaptureGuest()

    def step() -> None:
        guest.hits += 1

    guest.mock.retrace_source = step
    meta = _run_capture(staged_repo, MockEmulator(guest.mock), max_frames=10)

    assert len(meta["frames"]) == 3
    assert [f["film_tick"] for f in meta["frames"]] == [0, 0, 0]


# ==============================================================================
# Session behaviour
# ==============================================================================


def test_run_session_settles_and_injects_dialog_keys(staged_repo: StagedRepo) -> None:
    """The session waits for the dialog and queues prefix, Down and Enter keys."""
    guest = CaptureGuest()

    def sample(_session: Session) -> None:
        assert guest.dumps == SETTLE_DUMPS
        assert guest.mock.read_u16(0x0040, 0x001C) == 0x0024
        assert guest.mock.read_memory((0x0040, 0x001E), 6) == bytes(
            [0x63, 0x2E, 0x00, 0x50, 0x0D, 0x1C]
        )

    run_session(
        staged_repo.film,
        staged_repo.out,
        sample=sample,
        conf=staged_repo.conf,
        emulator=MockEmulator(guest.mock),
    )


def test_page_properties_are_lazy(staged_repo: StagedRepo) -> None:
    """A page that is never asked for a raster never dumps one."""
    guest = CaptureGuest()
    observed: dict[str, int] = {}

    def sample(session: Session) -> None:
        page = session.next_frame()
        before = guest.dumps
        assert page.film_clock == (103, 98)
        observed["after_clock"] = guest.dumps - before
        _ = page.raster
        observed["after_raster"] = guest.dumps - before

    run_session(
        staged_repo.film,
        staged_repo.out,
        sample=sample,
        conf=staged_repo.conf,
        emulator=MockEmulator(guest.mock),
    )
    assert observed == {"after_clock": 0, "after_raster": 1}


def test_page_is_stale_after_next_frame_and_session_end(staged_repo: StagedRepo) -> None:
    """A page is valid only until the next frame or the session end."""
    pages: list[Page] = []

    def sample(session: Session) -> None:
        first = session.next_frame()
        assert first.raster
        second = session.next_frame()
        pages.extend([first, second])
        with pytest.raises(StalePage):
            _ = first.raster
        with pytest.raises(StalePage):
            _ = first.film_clock
        with pytest.raises(StalePage):
            _ = first.read_memory(DGROUP_RUNTIME_SEG, 0, 2)

    run_session(
        staged_repo.film,
        staged_repo.out,
        sample=sample,
        conf=staged_repo.conf,
        emulator=MockEmulator(CaptureGuest().mock),
    )
    with pytest.raises(StalePage):
        _ = pages[0].palette
    with pytest.raises(StalePage):
        _ = pages[1].raster


def test_page_palette_falls_back_to_the_sdk_table() -> None:
    """A missing DAC palette falls back to the Mode 13h table with provenance."""
    page = Page(MockTransport(), DGROUP_RUNTIME_SEG)
    palette, source = page.palette
    assert source == "fallback"
    assert palette == [tuple(rgb) for rgb in MODE_13H_PALETTE]


def test_dialog_never_settling_reports_granular_error(staged_repo: StagedRepo) -> None:
    """A page that never stops changing fails after exactly 600 dumps."""
    mock = MockTransport()
    calls = {"n": 0}

    def changing() -> bytes:
        calls["n"] += 1
        return bytes((i + calls["n"]) % 6 for i in range(FRAME_BYTES))

    mock.dump_source = changing
    emulator = MockEmulator(mock)

    with pytest.raises(DialogUnsettled, match="never settled after 600 dumps"):
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=lambda _session: None,
            conf=staged_repo.conf,
            emulator=emulator,
        )
    assert calls["n"] == 600
    assert emulator.stopped


def test_short_dump_during_settle_raises(staged_repo: StagedRepo) -> None:
    """A dump that is not one Mode 13h page is a ShortDump."""
    mock = MockTransport()
    mock.dump_source = lambda: b"\x00" * 100

    with pytest.raises(ShortDump, match="expected 64000"):
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=lambda _session: None,
            conf=staged_repo.conf,
            emulator=MockEmulator(mock),
        )


def test_probe_samples_only_requested_ticks(staged_repo: StagedRepo) -> None:
    """A probe-style sampler dumps only the pages whose film clock it asked for."""
    guest = CaptureGuest()
    sampled: list[int] = []

    def probe(session: Session) -> None:
        staged_repo.out.mkdir(parents=True, exist_ok=True)
        pending = [106, 112]
        while pending:
            page = session.next_frame()
            tick, _global = page.film_clock
            if tick < pending[0]:
                continue
            pending.pop(0)
            sampled.append(tick)
            (staged_repo.out / f"sample_{tick}.idx").write_bytes(page.raster)

    run_session(
        staged_repo.film,
        staged_repo.out,
        sample=probe,
        conf=staged_repo.conf,
        emulator=MockEmulator(guest.mock),
    )
    assert sampled == [106, 112]
    assert guest.dumps == SETTLE_DUMPS + 2


def test_raising_callback_still_stops_the_emulator(staged_repo: StagedRepo) -> None:
    """A callback exception propagates unchanged and teardown still runs."""
    emulator = MockEmulator(CaptureGuest().mock)

    def sample(_session: Session) -> None:
        raise RuntimeError("sampler failed")

    with pytest.raises(RuntimeError, match="sampler failed") as info:
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=sample,
            conf=staged_repo.conf,
            emulator=emulator,
        )
    assert emulator.stopped
    assert emulator.stop_timeouts == [EMULATOR_STOP_SECONDS]
    assert getattr(info.value, "emulator_status", None) is None


def test_emulator_exit_status_is_attached_to_the_propagating_error(
    staged_repo: StagedRepo,
) -> None:
    """A crashed emulator leaves its exit status on the error the caller sees."""
    status = 0xC0000409

    class CrashedEmulator:
        def __init__(self, transport: Transport) -> None:
            self.transport = transport

        @property
        def exit_status(self) -> int | None:
            return status

        def start(self) -> Transport:
            return self.transport

        def stop(self, _timeout: float) -> None:
            return None

    def sample(_session: Session) -> None:
        raise RuntimeError("sampler failed")

    with pytest.raises(RuntimeError, match="sampler failed") as info:
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=sample,
            conf=staged_repo.conf,
            emulator=CrashedEmulator(CaptureGuest().mock),
        )
    assert info.value.emulator_status == status  # type: ignore[attr-defined]


def test_a_callback_error_outranks_a_teardown_error(staged_repo: StagedRepo) -> None:
    """The first exception propagates even when teardown also fails."""

    class FailingCloseTransport(MockTransport):
        def close(self) -> None:
            super().close()
            raise RuntimeError("teardown failed")

    class QuietEmulator:
        def __init__(self, transport: Transport) -> None:
            self.transport = transport

        @property
        def exit_status(self) -> int | None:
            return None

        def start(self) -> Transport:
            return self.transport

        def stop(self, _timeout: float) -> None:
            return None

    transport = FailingCloseTransport()
    CaptureGuest(transport=transport)

    def sample(_session: Session) -> None:
        raise RuntimeError("sampler failed")

    with pytest.raises(RuntimeError, match="sampler failed"):
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=sample,
            conf=staged_repo.conf,
            emulator=QuietEmulator(transport),
        )


def test_teardown_closes_the_transport_before_stopping_the_emulator(
    staged_repo: StagedRepo,
) -> None:
    """Teardown order is transport close, port release, then process stop."""
    events: list[str] = []

    class RecordingTransport(MockTransport):
        def close(self) -> None:
            events.append("transport")
            super().close()

    class RecordingEmulator:
        def __init__(self, transport: Transport) -> None:
            self.transport = transport

        @property
        def exit_status(self) -> int | None:
            return None

        def start(self) -> Transport:
            events.append("start")
            return self.transport

        def stop(self, _timeout: float) -> None:
            events.append("emulator")

    transport = RecordingTransport()
    guest = CaptureGuest(transport=transport)

    run_session(
        staged_repo.film,
        staged_repo.out,
        sample=lambda _session: None,
        conf=staged_repo.conf,
        emulator=RecordingEmulator(transport),
    )
    assert events == ["start", "transport", "emulator"]
    assert guest.dumps == SETTLE_DUMPS


# ==============================================================================
# Emulator lifecycle and the port
# ==============================================================================


def test_port_taken_before_launch(staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch) -> None:
    """A held control port fails the session before any process is launched."""
    port = free_port()
    blocker = ListenTransport(host="127.0.0.1", port=port)
    blocker.listen()
    launched: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "stunt_reel.tac.emulator.subprocess.Popen",
        lambda *args, **kwargs: launched.append((args, tuple(kwargs.items()))),
    )
    try:
        with pytest.raises(PortTaken) as info:
            DosboxX(staged_repo.conf, port=port).start()
    finally:
        blocker.close()
    assert info.value.port == port
    assert launched == []


def test_launch_failure_releases_the_port(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing emulator executable releases the bound control port."""
    port = free_port()
    monkeypatch.setattr("stunt_reel.tac.emulator.shutil.which", lambda _name: None)

    with pytest.raises(EmulatorUnavailable, match="not on PATH"):
        DosboxX(staged_repo.conf, port=port).start()

    probe = ListenTransport(host="127.0.0.1", port=port)
    probe.listen()
    probe.close()


def test_two_sessions_cannot_hold_one_port(staged_repo: StagedRepo) -> None:
    """The port is the machine-wide lock: a second session is refused."""
    port = free_port()
    first = DosboxX(staged_repo.conf, port=port, no_launch=True)
    thread = fake_guest(port)
    transport = first.start()
    try:
        second = DosboxX(staged_repo.conf, port=port, no_launch=True)
        with pytest.raises(PortTaken):
            second.start()
    finally:
        transport.close()
        first.stop(0.1)
        thread.join(timeout=2.0)


def test_raising_callback_releases_the_port(staged_repo: StagedRepo) -> None:
    """Teardown releases the control port even when the sampler raises."""
    port = free_port()

    class PortTransport(MockTransport):
        def __init__(self) -> None:
            super().__init__()
            self.listener = ListenTransport(host="127.0.0.1", port=port)
            self.listener.listen()

        def close(self) -> None:
            self.listener.close()
            super().close()

    transport = PortTransport()
    CaptureGuest(transport=transport)

    class PortEmulator:
        def __init__(self, ops: Transport) -> None:
            self.ops = ops

        @property
        def exit_status(self) -> int | None:
            return None

        def start(self) -> Transport:
            return self.ops

        def stop(self, _timeout: float) -> None:
            return None

    def sample(_session: Session) -> None:
        raise RuntimeError("sampler failed")

    with pytest.raises(RuntimeError, match="sampler failed"):
        run_session(
            staged_repo.film,
            staged_repo.out,
            sample=sample,
            conf=staged_repo.conf,
            emulator=PortEmulator(transport),
        )

    probe = ListenTransport(host="127.0.0.1", port=port)
    probe.listen()
    probe.close()


# ==============================================================================
# Staging and the shared-write gate
# ==============================================================================


def test_staging_copies_engine_files_and_rewrites_the_conf(staged_repo: StagedRepo) -> None:
    """Staging copies the engine files and the film pair, then mounts the fresh stage."""
    intro = staged_repo.film.with_name("INTRO.FLM")
    shutil.copy2(staged_repo.film, intro)
    shutil.copy2(staged_repo.film.with_suffix(".ALL"), intro.with_suffix(".ALL"))

    stage, staged_conf = staging.stage_film(intro, staged_repo.conf)

    for name in ENGINE_FILES:
        assert (stage / name).is_file()
    assert (stage / "VAULT" / "INTRO.FLM").is_file()
    assert (stage / "VAULT" / "INTRO.ALL").is_file()
    text = staged_conf.read_text(encoding="utf-8")
    assert 'mount c "build/parity/stage/intro"' in text
    assert r"VAULT\INTRO.FLM" in text
    assert "corpus/stisldem" not in text


def test_staging_fails_loudly_when_the_conf_literal_is_missing(
    staged_repo: StagedRepo, tmp_path: Path
) -> None:
    """A conf that cannot be rewritten must not mount the wrong tree."""
    missing_film = tmp_path / "no-film.conf"
    missing_film.write_text('mount c "corpus/stisldem"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not contain"):
        staging.stage_film(staged_repo.film, missing_film)

    missing_mount = tmp_path / "no-mount.conf"
    missing_mount.write_text("VAULT\\CTRY.FLM\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not contain"):
        staging.stage_film(staged_repo.film, missing_mount)


def test_staging_requires_the_all_sibling(staged_repo: StagedRepo) -> None:
    """The film's .ALL must sit beside its .FLM."""
    staged_repo.film.with_suffix(".ALL").unlink()
    with pytest.raises(FileNotFoundError, match=r"\.ALL must sit together"):
        staging.stage_film(staged_repo.film, staged_repo.conf)


def test_shared_write_gate_refuses_before_launch(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run_session refuses a shared output root once, before staging or launch."""
    monkeypatch.delenv(dataroot.WRITE_ENV, raising=False)
    shared = dataroot.data_root() / "reference" / "ctry"
    emulator = capture_emulator()

    with pytest.raises(SharedWriteError, match=dataroot.WRITE_ENV):
        run_session(
            staged_repo.film,
            shared,
            sample=lambda _session: None,
            conf=staged_repo.conf,
            emulator=emulator,
        )
    assert not emulator.started


def test_shared_write_gate_allows_an_opted_in_run(
    staged_repo: StagedRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STUNT_DATA_WRITE=1 opens the shared root for a capture session."""
    monkeypatch.setenv(dataroot.WRITE_ENV, "1")
    shared = dataroot.data_root() / "reference" / "ctry"
    emulator = capture_emulator()

    result = run_session(
        staged_repo.film,
        shared,
        sample=lambda _session: "sampled",
        conf=staged_repo.conf,
        emulator=emulator,
    )
    assert result == "sampled"
    assert emulator.started


# ==============================================================================
# Scripts: flags, stdout lines and exit codes
# ==============================================================================

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load_script(name: str) -> Any:
    """Import one python/scripts module by path, without putting scripts on sys.path."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _capture_argv(staged_repo: StagedRepo, out: Path) -> list[str]:
    return [
        "capture_playone_reference.py",
        "--film",
        str(staged_repo.film),
        "--out",
        str(out),
        "--conf",
        str(staged_repo.conf),
    ]


def test_capture_script_keeps_its_flags_and_progress_lines(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """capture-ref's flags and the three progress lines are unchanged."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(sys, "argv", ["capture_playone_reference.py"])
    args = module.parse_args()

    assert args.film == Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert args.out is None
    assert args.dgroup_segment == DGROUP_RUNTIME_SEG
    assert args.max_frames == 2000
    assert args.conf == Path("tools/dosbox/dosbox-parity.conf")
    assert args.no_launch is False

    exe = Path("dosbox-x.exe")
    conf = Path("build/parity/stage/stage-ctry.conf")
    cwd = Path("D:/git/stunt-reel")
    module.report(Launching(exe, conf, cwd))
    module.report(WaitingForGuest(58991))
    module.report(DialogSettled(6))
    assert capsys.readouterr().out.splitlines() == [
        f"[capture] launching {exe} -conf {conf} (cwd {cwd})",
        "[capture] waiting for DOSBox-X on 127.0.0.1:58991",
        "[capture] dialog settled: 6 distinct indices",
    ]


def test_capture_script_failure_lines_and_exit_codes(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """capture-ref's failure lines and exit codes are unchanged."""
    module = _load_script("capture_playone_reference")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", _capture_argv(staged_repo, out))
    args = module.parse_args()

    def stub_raises(error: BaseException) -> None:
        def stub(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise error

        monkeypatch.setattr(module, "run_session", stub)

    shared = SharedWriteError("the capture session writes the shared data root")
    stub_raises(shared)
    assert module.run(args) == 2
    assert capsys.readouterr().err == f"[capture] {shared}\n"

    taken = PortTaken(
        58991, OSError(10048, "port 58991 is taken: another capture or the MCP server holds it")
    )
    stub_raises(taken)
    assert module.run(args) == 1
    assert capsys.readouterr().err == (
        f"[capture] cannot listen on 127.0.0.1:{taken.port} ({taken}); "
        "close the running DOSBox-X instance (or use --no-launch)\n"
    )

    missing = EmulatorUnavailable("dosbox-x is not on PATH")
    stub_raises(missing)
    assert module.run(args) == 1
    assert capsys.readouterr().err == f"[capture] {missing}; run via mise run capture-ref\n"

    crashed = RuntimeError("boom")
    crashed.emulator_status = 3221226505  # type: ignore[attr-defined]
    stub_raises(crashed)
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[capture] boom; emulator exit status 3221226505\n"

    def stub_ok(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"frames": [{"ordinal": 1}]}

    monkeypatch.setattr(module, "run_session", stub_ok)
    assert module.run(args) == 0
    assert capsys.readouterr().out == f"[capture] captured 1 frames into {out}\n"

    monkeypatch.setattr(module, "run_session", lambda *_a, **_k: {"frames": []})
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[capture] no frames captured\n"


def test_probe_script_keeps_its_flags_and_shot_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The light probe's flags and its [shot] line are unchanged."""
    module = _load_script("probe_playone_light")
    monkeypatch.setattr(sys, "argv", ["probe_playone_light.py"])
    args = module.parse_args()

    assert args.film == Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert args.ticks == "10,150,273,448,700,900,1100"
    assert args.out == Path("build/scratch/round5")
    assert args.stage == Path("tools/dosbox/dosbox-parity.conf")
    assert args.dump_all_segments is False

    mock = MockTransport()
    work = 0x1DF8
    mock.write_memory((work, module.LIGHT_OFFSET), struct.pack("<3h", 100, -200, 300))
    mock.write_memory((work, module.SUN_BILLBOARD_OFFSET), struct.pack("<3h", 1, 2, 3))
    mock.write_memory(
        (DGROUP_RUNTIME_SEG, module.SUN_POSITION_OFFSET), struct.pack("<6h", 4, 5, 6, 7, 8, 9)
    )
    mock.write_memory(
        (work, module.SHADE_ARRAY_OFFSET),
        struct.pack("<8h", 10, 11, 12, 13, 14, 15, 16, 17),
    )
    page = Page(mock, DGROUP_RUNTIME_SEG)
    module.sample(page, 42, work, tmp_path, dump_all=False)

    assert capsys.readouterr().out.splitlines() == [
        "[shot] tick    42 workseg 1DF8 L [100, -200, 300] |L| 374.2 "
        "sun_billboard [1, 2, 3] sun_position [4, 5, 6, 7, 8, 9] "
        "shade [10, 11, 12, 13, 14, 15, 16, 17]"
    ]
    assert (tmp_path / "work_t42.bin").stat().st_size == module.SEGMENT_BYTES
    assert (tmp_path / "ds_t42.bin").stat().st_size == module.SEGMENT_BYTES


def test_probe_script_failure_lines_and_exit_codes(
    staged_repo: StagedRepo,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The light probe's failure lines and exit codes are unchanged."""
    module = _load_script("probe_playone_light")
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe_playone_light.py",
            "--film",
            str(staged_repo.film),
            "--out",
            str(tmp_path / "out"),
            "--stage",
            str(staged_repo.conf),
        ],
    )
    args = module.parse_args()

    def stub_raises(error: BaseException) -> None:
        def stub(*_args: Any, **_kwargs: Any) -> None:
            raise error

        monkeypatch.setattr(module, "run_session", stub)

    shared = SharedWriteError("the capture session writes the shared data root")
    stub_raises(shared)
    assert module.run(args) == 2
    assert capsys.readouterr().err == f"[probe] {shared}\n"

    missing = EmulatorUnavailable("dosbox-x is not on PATH")
    stub_raises(missing)
    assert module.run(args) == 1
    assert capsys.readouterr().err == f"[probe] {missing}; run via mise exec\n"

    stub_raises(RuntimeError("boom"))
    assert module.run(args) == 1
    assert capsys.readouterr().err == "[probe] boom\n"

    monkeypatch.setattr(module, "run_session", lambda *_a, **_k: None)
    assert module.run(args) == 0
    assert capsys.readouterr().out == ""
