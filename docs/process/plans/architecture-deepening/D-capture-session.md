# Unit D: the capture session

Status: design agreed 2026-10-24; implemented and merged 2026-10-25 (`feat(tac): give the capture harness one session and an operations transport`); live capture and probe verified 2026-10-25. Source: architecture review card 6 (one capture session for the emulator) plus the transport-at-operation-altitude rider.

## 1. Problem

Two scripts own the whole capture session - staging, launch, the fixed control port, accept and handshake, dialog settle, trap arming, sampling and teardown - with `framebuffer.capture()` holding the frame loop and artifact writer in between. The transport seam speaks debugger text, so callers know syntax and the mock cannot drive a session. The probe imports a private framebuffer helper and the capture script's staging function, and the trajectory streamer is a third consumer of the same text client.

## 2. Constraints

- ADR-0010: the shipped `python/stunt_reel` package stays standard-library only; scripts are tooling.
- Offline CI never runs DOSBox-X or the corpus; the mock must drive a whole session with synthetic fixtures.
- Capture is local, and sessions no longer serialise on a fixed port (superseded by [ADR 0021](../../../adr/0021-capture-chooses-its-control-port.md), which also removes this plan's `CONTROL_PORT`); the SOP 6 shared-write gate applies to the output root.
- Unit A is settled: the CLI-side artifact adapter owns the read side; the capture writer stays here. Artifact names, keys and contents must not change.
- The light probe stays available with its flags unchanged; the private imports go away.
- The transport rider: operations are `read_memory`, `dump_framebuffer`, `read_palette`, `inject_key`, `step_to_retrace` and `close`, implemented by the live adapters and the mock alike.
- The trajectory streamer is a third consumer: `TacClient.read_memory`, `VsyncTrap` and the mock's `load_trajectory` migrate in the same landing as the transport deletion.
- No user-facing flag or output changes; framing and adversarial tests keep their value.

## 3. Decisions settled in the design round

- **Base:** the minimal-session design (one `run_session` entry, a one-step `Session`, a lazy `Page`) with four grafts: granular errors, explicit ordering invariants, the second variant's regression tests, and the shared-write gate inside the entry point.
- **Injection:** one `Emulator` seam whose start returns the operations transport; the packet-level transport stays the internal operations seam.
- **Capture policy:** `capture()` stays a sampler beside the artifact writer in `framebuffer.py`; the probe is the second sampler.
- **`Page`:** lazy properties with a `StalePage` lifetime rule.
- **Shared-write gate:** `run_session` applies it to `out` once, for both scripts.

## 4. Chosen design

### Interface

    def run_session(film: Path, out: Path, *, sample: Callable[..., T],  # sample(session) -> T
                    conf: Path = Path("dosbox-parity.conf"),
                    dgroup_segment: int = playone.DGROUP_RUNTIME_SEG,
                    no_launch: bool = False, emulator: Emulator | None = None) -> T

    class Session(Protocol):
        dgroup_segment: int
        def next_frame(self) -> Page: ...

    class Page:
        raster      -> bytes                 # exactly 64_000, Mode 13h
        film_clock  -> tuple[int, int]       # film clock, global tick
        palette     -> tuple[list[RGB], str] # 256 triples, "dacpal" | "fallback"
        def read_memory(self, segment: int, offset: int, length: int) -> bytes: ...

    class Emulator(Protocol):
        def start(self) -> Transport: ...    # binds the port before launching
        def stop(self, timeout: float) -> None: ...

    class Transport(Protocol):
        read_memory(address, length) -> bytes
        dump_framebuffer() -> bytes          # exactly 64_000, page 0
        read_palette() -> tuple[list[RGB], str]
        inject_key(key) -> None
        step_to_retrace() -> None            # arms the trap on the first call
        close() -> None

### Invariants

- `sample` runs exactly once, on the calling thread, after the dialog settles and the film is confirmed. The guest free-runs; the first `next_frame()` arms the post-retrace trap and stops at its next hit; each later call stops at the next hit. The session exists only inside the callback, so call-order errors are impossible.
- `Page` properties are lazy: a probe that reads only `film_clock` never dumps a raster or the DAC. A page is valid until the next `next_frame()` or session end; later use raises `StalePage`. `raster` is exactly 64,000 bytes or `ShortDump`.
- The port is bound before the process launches and held until teardown; one session per machine.
- Teardown order is transport close, then port release, then process stop (terminate, wait 10 s, kill). It is idempotent, and a callback exception never masks it; the first exception propagates.
- Errors are `PortTaken`, `EmulatorUnavailable`, `GuestTimeout`, `DialogUnsettled`, `TrapTimeout`, `ShortDump`, `SessionLost` and `StalePage`. Scripts keep exit 2 for a data-root refusal and 1 otherwise.
- Cost: at most 600 settle dumps; one round trip per `next_frame`; one 64 KB temp write and read per raster; one DAC read per recorded frame.

### What it hides

Staging (engine files, `.FLM`/`.ALL` adjacency, fresh mount, both conf rewrites); PATH lookup and `subprocess`; the accept and PING; dialog settle (five identical dumps after three changes, 600 cap); prefix, Down and Enter into the BDA ring buffer; trap arming at `0D51:0C5E`; `MEMDUMPBIN` to a per-process temp file and back; short-dump detection; `DACPAL` parsing and the SDK fallback; teardown order and port release.

## 5. Dependency strategy and adapters

- In-process: captured-frame filters, end-hold rule, artifact names and JSON, film hash - the samplers and the writer.
- Local-substitutable: stage directory, generated conf, the 64 KB temp file.
- Ports and adapters: the transport operations, with `ListenTransport` (DOSBox-X dials out), `LiveSocketTransport` (MCP server) and `MockTransport` (in-process fake).
- True external: the DOSBox-X process behind `Emulator.start/stop`, with `DosboxX` and `MockEmulator`.
- Not built: a `PortLock` adapter; the listener is its only implementation, so the port is the emulator adapter's responsibility.

`TacClient` shrinks to typed decoding over the operations transport for the streamer; `execute`, `ping`, breakpoints, `resume` and `VRT` go. `VsyncTrap` uses `step_to_retrace`. `MockTransport` keeps `load_trajectory` and loses `send_command`, `register_handler`, `_format_dump` and breakpoint state.

## 6. Migration (each landing green, artifacts byte-identical)

1. Add the operations to the three transports and the shared live base while keeping the text methods; retarget the framing tests to the line channel; gate green.
2. Add `session.py`, `Page` and the emulator adapters; port the capture sampler. Capture CTRY locally before and after: `tick_*.idx` bytes, palettes JSON and meta key-for-key must match.
3. Port the light probe and delete the private-helper and sibling-script imports; its flags keep working and it gains the same shared-write gate.
4. Port the streamer and `VsyncTrap` onto operations and migrate the mocks; delete `send_command` and `register_handler`; shrink `TacClient` and `VsyncTrap`.

No flag changes; success lines keep their prefixes and wording; the offline gate never imports DOSBox-X internals or the corpus.

## 7. Tests

- Survive, retargeted: the framing scenarios on the line channel; the second-listener refusal; the BDA adversarial tests on `inject_key`; the camera, actor, streamer and vsync tests on mock memory reads once the streamer port lands.
- Move: the capture-tags test to an offline session test driven by the mock; `_make_capture_mock` to a shared mock-emulator test module; mock transport operations split by operation; live-socket wire tests into the framing file.
- Die: the `MEMDUMPBIN` handler registration, the `D`/`SM`/`BP`/`RUN` verb assertions, and the `_wait_until_static`, `dump_frame` and `capture(client)` expectations.
- New: port taken before launch; launch failure releases the port; teardown stops the emulator after the transport; meta written last; clock-hold stop; probe samples only requested ticks; never-settling dialog; short dump; a raising callback still rebinds the port; stale page; palette fallback; two sessions on one port.

## 8. Deletions

`_wait_until_static`, `dump_frame`, `read_ticks`, `read_palette`; both scripts' `CONTROL_PORT`, `LAUNCH_TIMEOUT_SECONDS`, `EMULATOR_STOP_SECONDS`, `FRAME_CAP` and `stage_film`; `ListenTransport._dump_memory`; `MockTransport.send_command`, `register_handler`, `_format_dump` and breakpoint state; `TacClient.execute`, `ping`, breakpoint, `resume` and `VRT` methods; `VsyncTrap.arm`/`disarm`; `_scratch.idx` handling.

## 9. Kill criteria

Abandon if: either script still owns launch, settle, trap or teardown after step 3; the offline session needs a command handler or `send_command`; a local CTRY capture differs byte-wise; or `mise run check` needs DOSBox-X.

## 10. Open items

Names (`run_session`, `Session`, `Page`, `Emulator`, `Transport`) are proposals. `DACPAL` parsing is only exercised live, so the mock cannot prove it; keep a local live smoke step. The conf rewrite is string surgery on two literals and must fail loudly when either misses. The 64 KB temp file remains under the seam and is accepted. Link provisioning stays a CLI-edge line because it names the command.

## 11. Deviations recorded at implementation

1. `run_session` gained `progress: Callable[[SessionEvent], None] | None`, with typed `Launching(exe, conf, cwd)`, `WaitingForGuest(port)` and `DialogSettled(distinct_indices)` events. The capture script formats its existing lines from them; the probe passes `None` and stays silent.
2. The emulator protocol gained a read-only `exit_status`; `run_session` captures it before teardown and attaches `emulator_status` to the propagating exception, so the capture failure line keeps its `; emulator exit status N` suffix.
3. The six operations are the seam, but BDA injection needs writes: the live and mock transports additionally expose `write_memory` outside the `Transport` protocol, and `bda.BdaBuffer` is the narrow port.
4. `clear_frames` now runs inside the capture sampler after the shared-write gate, so a launch or dialog failure no longer clears the previous run's frames.
5. Dialog settle caps at exactly 600 dumps (the old code could do 601); the accept timeout message now says the guest did not connect in 30 s.
6. The probe's `FRAME_CAP` is gone: a requested clock that never arrives ends on the trap timeout (exit 1) instead of silently stopping after 2000 frames.

## 12. Live verification (2026-10-25)

With the user's explicit opt-in for the capture round, the live path was exercised:

- `mise run capture-ref -- --out build/tmp/live-capture-ctry` wrote 124 frames (249 files), held the film clock at 1342, and wrote the same top-level meta keys and film identity as the stored reference.
- A second run of the same code wrote 122 frames. The two runs shared only 11 film-clock tags, and the page stored for a nominally equal tag can differ; the existing capture note documents the same run-to-run non-repeatability from 2026-10-22. Byte identity across captures is not an invariant; the writer format and the tags are.
- Both captures score in the stored reference's band against the same render directory: mean SSIM 0.798 and 0.794 versus the reference's 0.793, IoU 0.978 for all three, 111-114 scored frames.
- The light probe sampled ticks 21 and 51, printed its `[shot]` lines and wrote 61,440-byte segment dumps, exit 0.

The offline scripted-guest tests pin the writer format and meta ordering; this run confirms the live emulator path and the probe still work.
