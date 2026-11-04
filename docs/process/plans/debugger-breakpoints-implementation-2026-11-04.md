# DOSBox-X Breakpoint Plans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `mise run debug-x`, a one-shot breakpoint-plan runner on DOSBox-X's built-in
debugger link, and use it to answer #66 (what sets the per-shot light) and #65 (who produces the
ground records and their colours) on both `PLAYONE.EXE` builds.

**Architecture:** A `python/stunt_reel/dbx/` package. `link` speaks the TCP protocol, `boot`
stages and starts a film, `addr` translates between image offsets and runtime addresses (patched
offsets come from #78's pairing), `watch` turns a memory-breakpoint stop into a writer with
iced-x86, `plan` parses TOML plans, and `run` drives the hit loop and writes JSONL. A CLI script
behind a mise task ties them together. The findings tasks then run plans and update the research
notes.

**Tech Stack:** Python 3.15, DOSBox-X v2026.10.01 (`mcp_server` link), iced-x86 1.22.0, stdlib
`socket`/`tomllib`, pytest, mypy strict, ruff.

**Spec:** [`debugger-breakpoints-2026-11-04.md`](debugger-breakpoints-2026-11-04.md). Read it
first: section numbers below (S3.2 and so on) point into it.

## Global Constraints

- Tests run offline with no corpus, emulator or network (AGENTS.md Directive 1); live runs never
  enter `mise run check`.
- `mise run check` passes before every commit that ends a task; stage files by name; Conventional
  Commit subjects; bodies per AGENTS.md "Commit Messages"; end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `stunt-core` is untouched (`[I7]`); everything here is Python.
- DOSBox-X conf: `core = normal`, `output = surface`; never send `VRT`; before the dialog settles,
  send only `MEMDUMPBIN A000:0000 FA00` (legacy S3).
- `MEMDUMPBIN` takes a literal `seg:off`, a hex length, and an unquoted forward-slash host path
  whose parent exists; the file name is upper-case 8.3 (`[I8]`).
- The listener binds port 0 on `127.0.0.1`; conf, stage and dump directory are per run (ADR 0021).
- Outputs go under `<data root>/debug/<film stem>/`; nothing writes `corpus/`.
- Every agent-facing script gets a `mise run` task (SOP 5).
- Plan offsets are unpatched image offsets.
- Posting on GitHub issues (the #69 comment) needs the user's yes at the time.

## Review Focus

1. **The emulator dies mid-run** (known `0xC0000409` exits): the run writes an `end` record with
   `reason = "link_lost"`, keeps the hits already written, exits 1. Test in Task 6.
2. **A probe site's live bytes differ from the image** (wrong build, wrong offset): the probe is
   refused before arming and the CLI exits 2. Tests in Tasks 2 and 6.
3. **A watch stop on bytes that do not decode cleanly** (data, a `rep` prefix, an instruction that
   moves its own address register): the verdict is `ambiguous` or `spurious`, never an exception.
   Test in Task 3.
4. **Two runs side by side**: distinct ports, stage roots and dump paths. Test in Task 1 (dump
   names are per link) and Task 5 (stage root per run).
5. **A probe that never fires or arms at a tick the film never reaches**: the run ends with
   `stop_tick` or `timeout` and an `end` record, not a hang. Test in Task 6.

## File Map

| Path | Task | Responsibility |
|---|---|---|
| `python/stunt_reel/dbx/__init__.py` | 1 | package docstring, re-exports |
| `python/stunt_reel/dbx/link.py` | 1 | TCP protocol, dumps, register reads |
| `tests/dbx_peer.py` | 1 | scripted fake DOSBox-X peer for tests |
| `python/stunt_reel/dbx/addr.py` | 2 | image/runtime translation, site check, patched mapping |
| `python/stunt_reel/dbx/watch.py` | 3 | watch-stop writer resolution with iced-x86 |
| `python/stunt_reel/dbx/plan.py` | 4 | plan TOML parsing and validation |
| `python/stunt_reel/dbx/boot.py` | 5 | conf, staging, dialog settle, BIOS keys, load paragraph, launch |
| `tools/dosbox-x/dosbox-x.conf` | 5 | conf template |
| `python/stunt_reel/dbx/run.py` | 6 | arming, hit loop, JSONL |
| `python/scripts/debug_x.py`, `mise.toml` | 7 | CLI, task, DOSBox-X pin |
| `docs/adr/0033-...md`, `research/playone-exe/debugger-plans.md` | 8 | records |
| `tools/dosbox-x/plans/light-*.toml` | 9 | #66 plans |
| `python/stunt_reel/ground_stream.py`, `python/scripts/ground_stream.py` | 11 | stream decoder |
| `tools/dosbox-x/plans/ground-*.toml` | 12-13 | #65 plans |

The spec gives `plan.py` both parsing and the hit loop; this plan splits the loop into `run.py`
so each file has one job. Nothing else departs from the spec.

---

## PR A: the tool

### Task 0: Base the branch on #78

- [ ] **Step 1:** Confirm `HEAD~1` is `3e147ee` (#78's iced-x86 commit) or its successor on the
  #78 PR branch; `git log --oneline -3`.
- [ ] **Step 2:** `mise exec -- uv sync --locked --all-groups`, then
  `mise exec -- uv run python -c "import iced_x86, stunt_reel.build_pairing"` prints nothing.

### Task 1: `link.py` and the fake peer

**Files:** Create `python/stunt_reel/dbx/__init__.py`, `python/stunt_reel/dbx/link.py`,
`tests/dbx_peer.py`, `tests/test_dbx_link.py`.

**Interfaces:**
- Produces:
  - `class LinkError(RuntimeError)`, `class LinkLost(LinkError)`, `class LinkTimeout(LinkError)`
  - `@dataclass(frozen=True, slots=True) class Regs` with int fields
    `cs ip ss sp ds es ax bx cx dx si di bp`, `def as_dict(self) -> dict[str, int]`, and
    `REGS_EV: str = "EV CS IP SS SP DS ES AX BX CX DX SI DI BP"`
  - `class Listener`: `__init__(self) -> None` binds `127.0.0.1:0`; `port: int`;
    `accept(self, timeout: float) -> socket.socket`; `close(self) -> None`
  - `class Link`: `__init__(self, sock: socket.socket, dump_dir: Path, *, timeout: float = 20.0)`
    (raises `LinkError` if `dump_dir` contains a space or does not exist);
    `req(self, command: str, *, timeout: float | None = None) -> list[str]` (body lines; `ERR`
    raises `LinkError` with the body);
    `ex(self, command: str) -> list[str]` (`req("EXEC " + command)`);
    `dump(self, seg: int, off: int, length: int) -> bytes`; `regs(self) -> Regs`;
    `close(self) -> None`
  - `tests/dbx_peer.py`: `class FakePeer` with `__init__(self, port: int, script: Callable[[str], list[str] | None])`.
    It connects to the port and answers each `REQ <id> <cmd>` with
    `BEGIN <id> OK`, the lines the script returns, `END <id>`. When the script returns `None` it
    closes the socket. It runs on a thread. `memory: dict[int, int]`, linear address to byte,
    serves `MEMDUMPBIN` by writing the file named in the command.

- [ ] **Step 1: Write the failing tests** in `tests/test_dbx_link.py`:
  - `test_req_matches_exact_id`: the peer answers request 1 with an unrelated `BEGIN 10 OK`/`END 10`
    pair first, then the real one; `req("PING") == ["PONG"]`.
  - `test_err_raises_with_body`: peer answers `BEGIN 1 ERR`, `bad`, `END 1`;
    `pytest.raises(LinkError, match="bad")`.
  - `test_timeout_raises`: peer never answers; `req("PING", timeout=0.2)` raises `LinkTimeout`.
  - `test_closed_socket_raises_link_lost`: script returns `None`; `LinkLost`.
  - `test_dump_command_and_bytes`: `memory` holds `0x15750 + 0x4896 -> 0x05, +1 -> 0x01`;
    `dump(0x1575, 0x4896, 2) == b"\x05\x01"`, and the command the peer saw is
    `EXEC MEMDUMPBIN 1575:4896 2 <dump_dir posix>/D0000001.BIN`.
  - `test_dump_names_count_per_link`: two dumps use `D0000001.BIN` then `D0000002.BIN`.
  - `test_regs_parses_ev`: peer answers `EV of '...' is:` then
    `1048 ec0 2aaa ee94 1575 67e7 63 7ffe 704 ffef c 809c 558b`;
    `regs() == Regs(cs=0x1048, ip=0xEC0, ss=0x2AAA, sp=0xEE94, ds=0x1575, es=0x67E7, ax=0x63, bx=0x7FFE, cx=0x704, dx=0xFFEF, si=0xC, di=0x809C, bp=0x558B)`.
  - `test_dump_dir_with_space_refused`: `LinkError`.
- [ ] **Step 2:** `mise run test-py -- tests/test_dbx_link.py`: FAIL (module missing).
- [ ] **Step 3:** Implement `link.py` to the interfaces. Read with a `makefile("rb")`; body lines
  are those between the matching `BEGIN` and `END`, others ignored. `dump` polls for the file up
  to 2 s after the response.
- [ ] **Step 4:** Same command: PASS. Then `mise run lint-py` and `mise run typecheck`.
- [ ] **Step 5:** Commit `feat(dbx): speak DOSBox-X's debugger link`.

### Task 2: `addr.py`

**Files:** Create `python/stunt_reel/dbx/addr.py`, `tests/test_dbx_addr.py`.

**Interfaces:**
- Consumes: `stunt_reel.build_pairing.LoadImage`, `Pairing`, `map_code`, `ALIGNED`.
- Produces:
  - `class Unmappable(ValueError)`, `class SiteMismatch(ValueError)`
  - `def vm_paragraph(image: LoadImage) -> int`: the paragraph of the dispatch-slot run, the first
    offset where 100 consecutive 9-byte slots `26 C7 44 FE ?? ?? E9 ?? ??` start, divided by 16.
    Raises `ValueError` when none is found.
  - `@dataclass(frozen=True, slots=True) class Runtime`, fields `image: LoadImage`, `load: int`,
    `dgroup_paragraph: int`, `vm: int`. Properties `ds -> int` (`load + dgroup_paragraph`) and
    `end -> int` (`load * 16 + len(image.data)`). Methods:
    `code_site(self, offset: int, cs: Literal["auto", "module", "vm"] = "auto") -> tuple[int, int]`
    and `to_image(self, seg: int, off: int) -> int | None` (`None` outside the image).
  - `def site_matches(image: LoadImage, offset: int, live: bytes) -> bool`: compares `live` with
    `image.data[offset:offset + len(live)]`, skipping both bytes of every word in `image.relocs`
    that overlaps the range.
  - `def to_patched(pairing: Pairing, offset: int) -> int`: `map_code(...)` must be `ALIGNED` and
    `pairing.function_at(offset)` must have ratio `1.0`, else `Unmappable` naming `how` and the
    ratio.

- [ ] **Step 1: Write the failing tests.** They use a synthetic `LoadImage`: 0x9000 bytes of
  zeros, 100 slots written at `0x8240`, `relocs = {0x9102}`.
  - `test_vm_paragraph_finds_slot_run == 0x824`
  - `test_code_site_auto`: with `Runtime(img, load=0x0824, dgroup_paragraph=0xD51, vm=0x824)`,
    `code_site(0x9100) == (0x1048, 0x0EC0)` and `code_site(0x2350) == (0x0824, 0x2350)`.
  - `test_to_image_round_trip`: `to_image(0x1048, 0x0EC0) == 0x9100`; `to_image(0x2AAA, 0xEE94) is None`.
  - `test_ds`: `ds == 0x1575`.
  - `test_site_matches_masks_relocs`: image bytes `1e bf d4 15 8e df` at `0x9100`, live
    `1e bf f8 1d 8e df` gives True; live `1e bf f8 1d 8e de` gives False.
  - `test_to_patched_refuses_estimated`: a `Pairing` stub whose `map_code` result is `ESTIMATED`
    raises `Unmappable`. Build the minimal `Pairing` with empty `functions` and one `code` entry,
    then ask for an address outside it.
- [ ] **Step 2:** `mise run test-py -- tests/test_dbx_addr.py`: FAIL.
- [ ] **Step 3:** Implement. `code_site` auto picks VM when `offset >= vm * 16`. The VM segment is
  `load + vm` and the module segment is `load`, with `off = offset - (seg - load) * 16`. Raise
  `ValueError` if `off > 0xFFFF`.
- [ ] **Step 4:** PASS, lint, typecheck.
- [ ] **Step 5:** Commit `feat(dbx): translate image offsets for both builds`.

### Task 3: `watch.py`

**Files:** Create `python/stunt_reel/dbx/watch.py`, `tests/test_dbx_watch.py`.

**Interfaces:**
- Consumes: `Regs` (Task 1).
- Produces:
  - `@dataclass(frozen=True, slots=True) class Candidate`: `start: int` (offset within the code
    segment), `length: int`, `text: str`, `linear: int` (the resolved write address)
  - `@dataclass(frozen=True, slots=True) class Verdict`: `kind: Literal["write", "ambiguous", "spurious"]`,
    `writer: Candidate | None`, `candidates: tuple[Candidate, ...]`
  - `def resolve_writer(code: bytes, ip: int, regs: Regs, watch: range) -> Verdict`. `code` holds
    the 6 bytes before the stop `ip` and 8 bytes from it (`ip - 6 .. ip + 8`), `regs` are the
    registers at the stop, and `watch` is a range of linear addresses.

Rule (spec S3.4, made exact):

- **Candidates.** Decode one 16-bit instruction (`Decoder(16, ...)`, `ip` set) at each start
  `ip-6 .. ip-1` that ends exactly at `ip`, plus the instruction at `ip` itself if it is a
  `rep`-prefixed string op (DOSBox re-executes those in place).
- **Addresses.** For each `used_memory()` entry with access `WRITE`, `COND_WRITE` or `READ_WRITE`,
  compute `seg_value * 16 + ((base + index * scale + displacement) & 0xFFFF)`, taking the segment
  register's value and the base and index registers from `regs`.
- **Self-moving address registers.** For string ops, accept a match within `±memory_size` of the
  computed address, because `SI`/`DI` already moved. For `push` and `call`, the stopped `SP` is the
  written address.
- **Verdict.** It is a candidate when any write address intersects `watch`. `write` means exactly
  one candidate, `ambiguous` more than one, `spurious` none. An invalid decode is skipped, never
  raised.

- [ ] **Step 1: Write the failing tests**, each with hand-built bytes and `Regs`:
  - `test_adc_direct_is_write`: bytes from the spike, `... 11 06 96 48 | 72 10 85 c0 ...`, stop
    `ip = 0x43EA`, `ds = 0x1575`, watch `range(0x1575 * 16 + 0x4896, +2)`; `kind == "write"`,
    `writer.start == 0x43E6`, `"adc" in writer.text`.
  - `test_mov_cx_ax_is_spurious`: bytes ending `8b c8` at `0x759C`; `kind == "spurious"`.
  - `test_stosw_matches_moved_di`: `ab` (stosw) ending at the stop, `es:di` after the stop
    `= watch + 2`; `write`.
  - `test_rep_movsw_at_ip`: `f3 a5` at `ip`, with `es:di` inside the watch; `write`.
  - `test_push_writes_at_sp`: `ff 36 ec 22` (`push [0x22EC]`) ending at the stop, with
    `ss:sp` = watch start; `write`.
  - `test_two_candidates_ambiguous`: bytes where both a 2-byte and a 4-byte decode end at `ip` and
    write the watch, e.g. `89 07` / `26 89 07` with `ds == es`; `ambiguous`, two candidates.
  - `test_garbage_never_raises`: `bytes(range(0xF0, 0xFE))`; `kind == "spurious"`.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement with `iced_x86.Decoder`, `InstructionInfoFactory`, `OpAccess` and
  `Register`. Map `Register.ES` and the other registers to `Regs` fields with a dict.
- [ ] **Step 4:** PASS, lint, typecheck.
- [ ] **Step 5:** Commit `feat(dbx): name the instruction behind a memory-breakpoint stop`.

### Task 4: `plan.py`

**Files:** Create `python/stunt_reel/dbx/plan.py`, `tests/test_dbx_plan.py`.

**Interfaces:**
- Produces:
  - `class PlanError(ValueError)`
  - `@dataclass(frozen=True, slots=True) class Capture`: `kind: Literal["stack", "mem"]`,
    `seg: str` (a register name or `""` for `stack`), `off: str | int` (a register name or an
    int), `length: int` (words for `stack`, bytes for `mem`), `key: str` (the original text)
  - `@dataclass(frozen=True, slots=True) class Probe`: `name`,
    `kind: Literal["break", "watch", "int"]`, `at: int | None`, `patched_at: int | None`,
    `cs: Literal["auto", "module", "vm"]`, `mem: tuple[str, int] | None`, `linear: int | None`,
    `size: int`, `int_no: int | None`, `ah: int | None`, `arm: Literal["dialog"] | int`
    (an int is a film tick), `hits: int`, `capture: tuple[Capture, ...]`,
    `ignore_ip: tuple[tuple[int, int], ...]`
  - `@dataclass(frozen=True, slots=True) class Plan`: `name: str`, `cycles: int`,
    `stop_tick: int | None`, `probes: tuple[Probe, ...]`, `sha256: str`
  - `def parse_plan(text: str, name: str) -> Plan`, `def load_plan(path: Path) -> Plan`

Defaults: `cycles = 8000`, `stop_tick = None`, `cs = "auto"`, `size = 1`, `arm = "dialog"`,
`hits = 1`, `capture = ()`. Validation (each raises `PlanError` naming the probe):
- `break` needs `at`;
- `watch` needs exactly one of `mem` and `linear`, and `1 <= size <= 16`; a watch of `size` *n*
  sets *n* one-byte `BPM`s;
- `int` needs `int`;
- names are unique;
- `hits >= 1`;
- capture keys match `stack:<n>` or `mem:<SEG>:<OFF>:<LEN>`, where `SEG` is in
  `CS DS ES SS` and `OFF` is a register or a hex or decimal int;
- `ignore_ip` is a list of `[lo, hi]` pairs.

- [ ] **Step 1: Write the failing tests:**
  - `test_spec_example_parses`: the three probes of spec S3.2 verbatim. Check
    `probes[0].arm == 10`, `probes[1].mem == ("DS", 0x49EC)`, `probes[1].size == 6`,
    `probes[1].ignore_ip == ((0x8240, 0x860B),)`, `probes[2].ah == 0x3F`,
    `probes[0].capture[1] == Capture("mem", "ES", "SI", 64, "mem:ES:SI:64")`.
  - `test_defaults`: a one-probe plan gives `cycles == 8000`, `hits == 1`, `arm == "dialog"`.
  - `test_rejects` (parametrized): break without `at`; watch with both `mem` and `linear`;
    `size = 17`; duplicate names; `capture = ["mem:FS:SI:4"]`; `hits = 0`. Each raises
    `PlanError`.
  - `test_sha256_is_of_text`: the same text gives the same `sha256`, and a changed byte changes it.
- [ ] **Step 2:** FAIL. **Step 3:** Implement with `tomllib`. **Step 4:** PASS, lint, typecheck.
- [ ] **Step 5:** Commit `feat(dbx): parse breakpoint plans`.

### Task 5: `boot.py` and the conf template

**Files:** Create `python/stunt_reel/dbx/boot.py`, `tools/dosbox-x/dosbox-x.conf`,
`tests/test_dbx_boot.py`, `tests/fixtures/dbx/mcbs.txt`; modify `tests/fixtures/README.md`.

**Interfaces:**
- Consumes: `Listener`, `Link` (Task 1); `staging.stage_film`, `staging.unstage`;
  `game_builds.BUILDS_DIR`; `dataroot.data_root`; `playone.film_selection_names`.
- Produces:
  - `DOSBOX_X_VERSION: str = "2026.10.01"`
  - `def dosbox_x_exe() -> Path` (`mise where github:joncampbell123/dosbox-x` plus
    `bin/x64/Release SDL2/dosbox-x.exe`; raises `tac.emulator.EmulatorUnavailable`)
  - `def render_conf(template: str, *, mount: Path, cycles: int) -> str`
  - `class DialogSettle` with `feed(self, page: bytes) -> bool`: True once 5 consecutive identical
    pages each have exactly 6 distinct bytes
  - `def key_writes(head: int, tail: int, keys: Sequence[tuple[int, int]]) -> list[tuple[int, bytes]]`:
    the BDA writes (offset in segment `0x40`, bytes), the key words at the tail, then the new tail
    word at `0x1C`, wrapping `0x1E..0x3D`. Raises `ValueError` if the keys would overrun the head.
  - `def char_key(ch: str) -> tuple[int, int]` and `KEY_DOWN = (0x00, 0x50)`,
    `KEY_ENTER = (0x0D, 0x1C)`: restore `_SCAN_CODES` and `char_to_key` from
    `git show e8bc1b3^:python/stunt_reel/tac/bda.py`
  - `def parse_mcbs(lines: Sequence[str], program: str = "PLAYONE") -> int`: the PSP segment of the
    block owned by `program`; the load paragraph is that plus `0x10`
  - `@contextmanager def booted(film: Path, build: Literal["unpatched", "patched"], *, cycles: int)`,
    a generator yielding one `Booted`, with `@dataclass class Booted`: `link: Link`, `load: int`, `stage: Path`. It stages from
    `<data root>/builds/<build>`, renders the conf into the stage root, launches with
    `-conf <conf> -fastlaunch -set "dosbox mcp_server=<port>"`, accepts within 60 s, waits for the
    dialog (at most 600 dumps, 0.1 s apart, `GuestTimeout` otherwise), sends the film's keys 1 s
    apart, reads `DOS MCBS` and yields. On exit it sends `BREAK`, kills the process and unstages.

Template `tools/dosbox-x/dosbox-x.conf`: `[dosbox] memsize = 16`; `[sdl] output = surface`,
`autolock = false`; `[cpu] core = normal`, `cycles = {cycles}`; `[sblaster]` as the retired
`dosbox-mcp.conf` (`sb16`, `220`, irq 7, dma 1, hdma 5); `[autoexec]` with `mount c "{mount}"`,
`c:` and `PLAYONE.EXE`. The mount path goes in forward slashes.

- [ ] **Step 1: Capture the MCBS fixture.** With Task 1's `Listener`/`Link`, a scratch script
  launches `dosbox-x.exe -conf <rendered template> -fastlaunch -set "dosbox mcp_server=<port>"`,
  dumps `A000` until the dialog settles, and sends `EXEC DOS MCBS`. Save the body lines to
  `tests/fixtures/dbx/mcbs.txt`; it is emulator output, not a game asset. Record its origin in
  `tests/fixtures/README.md`. Note the PSP of `PLAYONE`; the load paragraph must come out as
  `0x0824`.
- [ ] **Step 2: Write the failing tests:**
  - `test_render_conf_fills_fields`: `cycles = 8000` and `mount c "E:/x/stage/m"` appear, and
    `core = normal` and `output = surface` are present.
  - `test_dialog_settle`: four identical 6-index pages give False, the fifth True, and a
    41-index page in between resets the count.
  - `test_key_writes_wrap`: `tail = 0x3C` and two keys write `0x3C` then `0x1E`, and the tail
    word becomes `0x20`.
  - `test_key_writes_overrun_raises`.
  - `test_char_key`: `char_key("c") == (0x63, 0x2E)`.
  - `test_parse_mcbs_fixture`: `parse_mcbs(fixture) + 0x10 == 0x0824`.
  - `test_parse_mcbs_missing_raises`: `ValueError`.
- [ ] **Step 3:** FAIL. **Step 4:** Implement. `booted` is not unit-tested; Task 7 runs it live.
- [ ] **Step 5:** PASS, lint, typecheck.
- [ ] **Step 6:** Commit `feat(dbx): boot a film in DOSBox-X with the debugger link`.

### Task 6: `run.py`

**Files:** Create `python/stunt_reel/dbx/run.py`, `tests/test_dbx_run.py`.

**Interfaces:**
- Consumes: Tasks 1 to 4; `playone.PlayoneLayout` (`film_clock`).
- Produces:
  - `@dataclass(frozen=True, slots=True) class Armed`: `probe: Probe`, `sites: tuple[tuple[int, int], ...]`
    (break sites `seg:off`, or watch byte addresses as linear), `watch: range | None`
  - `def arm_probe(link: Link, rt: Runtime, probe: Probe, *, at: int) -> Armed`: `at` is the
    build-specific image offset the caller resolved. It reads 8 live bytes at the site and raises
    `SiteMismatch` unless `site_matches`, then sends `BP`, `BPM` per byte, `BPLM`, or
    `BPINT <nn> <ah>`.
  - `@dataclass(frozen=True, slots=True) class RunResult`: `reason: Literal["spent", "stop_tick", "timeout", "link_lost"]`,
    `hits: dict[str, int]`, `spurious: int`, `ignored: dict[str, int]`
  - `def run_plan(link: Link, rt: Runtime, plan: Plan, sites: Mapping[str, int], film_clock: int, out: TextIO, *, header: Mapping[str, object], poll: float = 0.05, tick_poll: float = 0.1, hit_timeout: float = 120.0) -> RunResult`

JSONL records, written as each happens and flushed:
- `{"type": "run", **header, "load": rt.load, "plan": plan.name, "plan_sha256": plan.sha256}`
- `{"type": "hit", "probe": str, "n": int, "film_tick": int, "regs": {...}, "cs_ip_image": int|null, "return_far_image": int|null, "return_near_image": int|null, "stack": [int...], "mem": {capture.key: hex}, "verdict": str|null, "writer": {"start": int, "image": int|null, "text": str}|null, "candidates": [...]}`
  - `return_far_image` reads `stack[0..1]` as `ip, cs`; `return_near_image` reads `stack[0]`
    with the stopped `cs`. Both are `null` outside the image.
- `{"type": "end", "reason": str, "hits": {...}, "spurious": int, "ignored": {...}}`

Loop (spec S3.5):
- Probes with `arm = "dialog"` are armed at once. Tick-armed probes wait until a 2-byte dump of
  `ds:film_clock` taken every `tick_poll` s reads at least their tick.
- After `RUN`, poll `regs()` every `poll` s until two snapshots in a row are equal. That is a
  stop.
  - A stop whose `cs:ip` is an armed break site counts for that probe.
  - Otherwise, if the bytes at `cs:ip` are `CD <int_no>` and `ah` matches, it counts for that
    `int` probe.
  - Otherwise it is resolved with `resolve_writer` against each armed watch. A writer inside a
    probe's `ignore_ip` counts as `ignored` for that probe. A `write` or `ambiguous` verdict counts
    for the watch it hits. A `spurious` verdict raises the global count.
- A probe that reaches `hits` is spent: send `BPDEL *`, then re-arm the others.
- The run ends `spent` when every probe is spent, `stop_tick` when the clock reaches
  `plan.stop_tick`, `timeout` when no stop comes within `hit_timeout`, and `link_lost` on
  `LinkLost`. It always writes the `end` record.

- [ ] **Step 1: Write the failing tests** with `FakePeer`. The script answers `EV` from a register
  sequence, `MEMDUMPBIN` from `memory`, and every other command `OK`.
  - `test_break_hit_record`: a break probe at `0x9100` with `hits = 2`, and a peer that reports
    `1048:0EC0` with `ss:sp` pointing at words `2350 0824`. The JSONL has a `run` record, two
    `hit` records with `cs_ip_image == 0x9100` and `return_far_image == 0x2350`, and an `end`
    record with `reason == "spent"`.
  - `test_site_mismatch_refuses`: live bytes differ, so `arm_probe` raises `SiteMismatch`.
  - `test_watch_spurious_counted`: a watch stop at the `0x759C` bytes leaves no `hit` record and
    gives `RunResult.spurious == 1`.
  - `test_watch_ignored_in_slot_run`: the writer sits inside `ignore_ip`, so `ignored[name] == 1`
    and there is no hit.
  - `test_link_lost_writes_end`: the peer closes after the first hit. The result is `link_lost`,
    and the file has one `hit` and an `end`.
  - `test_timeout_ends_run`: registers never repeat. With `hit_timeout = 0.3` the result is
    `timeout`.
  - `test_tick_arm_waits`: the clock word reads 5, then 9, then 12, and `arm = 10`. `BP` is sent
    only after the read of 12.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS, lint, typecheck.
- [ ] **Step 5:** Commit `feat(dbx): run a breakpoint plan and record its hits`.

### Task 7: CLI, task, pin, live check

**Files:** Create `python/scripts/debug_x.py`, `tools/dosbox-x/plans/smoke.toml`,
`tests/test_debug_x_script.py`; modify `mise.toml`.

**Interfaces:**
- Consumes: everything above; `unlzexe.unpack` and the pairing loader as in
  `python/scripts/pair_builds.py:load`; `playone.UNPATCHED` and `playone.PATCH3`.
- Produces: `def parse_args(argv: list[str]) -> argparse.Namespace` with `--plan` (required),
  `--film` (default `corpus/stisldem/VAULT/CTRY.FLM`), `--build` (`unpatched` or `patched`,
  default `unpatched`), and `--out` (default `<data root>/debug`). `def main(argv: list[str]) -> int`
  returns 0, 1 (run failed) or 2 (plan or site refused).

- [ ] **Step 1: Write the failing tests:** `test_parse_args_defaults`;
  `test_unknown_build_rejected`; `test_patched_unmappable_exits_2`. For the last, monkeypatch the
  pairing so that `to_patched` raises; `main` returns 2 before any launch, asserted by a
  `booted` that fails if it is called.
- [ ] **Step 2:** FAIL. **Step 3:** Implement `debug_x.py`:
  1. Load the plan.
  2. Load the build's unpacked image from `<data root>/builds/<build>/PLAYONE.EXE`.
  3. For `patched`, load both and pair them, then resolve every probe's `at` through
     `patched_at` or `to_patched`.
  4. Boot, build the `Runtime` from `booted.load`, `vm_paragraph` and the layout's
     `dgroup_paragraph`.
  5. Run, writing to `<out>/<film stem>/<plan>-<build>-<UTC stamp>.jsonl`.
  6. Print the summary: one row per probe (hits, ignored), the spurious count, and the distinct
     `return_far_image` and writer image offsets, at most 40 lines.
- [ ] **Step 4:** `mise.toml`: add the tool block below (the old pin from `01a1ae4^`, version
  string exact), and the task.
  ```toml
  [tools."github:joncampbell123/dosbox-x"]
  version = "dosbox-x-v2026.10.01"
  os = ["windows"]
  asset_pattern = "dosbox-x-vsbuild-win64-*.zip"
  bin_path = "bin/x64/Release SDL2"

  [tasks.debug-x]
  description = "Run a breakpoint plan on DOSBox-X's debugger (mise run debug-x -- --plan tools/dosbox-x/plans/smoke.toml [--build patched])"
  run = "uv run python python/scripts/debug_x.py"
  ```
- [ ] **Step 5:** PASS. Then `smoke.toml` gets one break probe at `0x9100`, `hits = 2`,
  `capture = ["stack:4", "mem:DS:0x49EC:6"]`, `stop_tick = 600`.
- [ ] **Step 6 (live):** `mise run debug-x -- --plan tools/dosbox-x/plans/smoke.toml`. Expected:
  two hits, `return_far_image` `0x2350`, `mem DS:0x49EC:6` equal to the hit's `AX BX DX`, exit 0.
  Repeat with `--build patched`. Expected: two hits, with the return mapped through the pairing.
  Record both summaries in the commit body.
- [ ] **Step 7:** `mise run check`, then commit `feat(dbx): mise run debug-x runs a breakpoint plan`.

### Task 8: Records, then PR A

**Files:** Create `docs/adr/0033-breakpoints-run-on-dosbox-x.md` and
`research/playone-exe/debugger-plans.md`. Modify `research/playone-exe/dosbox-x-legacy.md` (a
pointer line), `docs/ARCHITECTURE.md` (route `python/stunt_reel/dbx/` to the note and the ADR),
and `AGENTS.md` (add `debugger-plans.md` to the Binary Disassembly row, using the
`writing-for-agents` skill).

- [ ] **Step 1:** The ADR, using the `domain-modeling` skill's ADR shape. Record the decision
  (breakpoints on DOSBox-X, capture and per-frame sampling on dosbox-automation), the rejected
  hook probe, and the consequence that guest time is not halted.
- [ ] **Step 2:** `debugger-plans.md`, in the research-note shape of `research/README.md`:
  - the link, boot, addresses and watch filter;
  - the measured costs from Task 7: boot time, seconds per hit;
  - the plan format pointer;
  - **Ruled out**: the hook probe and the MCP server for agents;
  - **Open questions**.
- [ ] **Step 3:** `mise run check` (doc-invariant tests cover new anchors and links).
- [ ] **Step 4:** Commit `docs(dbx): record why breakpoints run on DOSBox-X`. Then open PR A with
  `gh-stack` on top of the #78 PR, body from the `pr` skill. Confirm with the user before pushing.

---

## PR B: #66, what sets the per-shot light

### Task 9: Light plans and runs

**Files:** Create `tools/dosbox-x/plans/light-caller.toml` and `light-writers.toml`.

- [ ] **Step 1:** `light-caller.toml`: two break probes at `0x9100`, named `light-entry-10`
  (`arm = 10`) and `light-entry-448` (`arm = 448`), `hits = 3` each, `capture =
  ["stack:8", "mem:DS:0x49EC:6", "mem:DS:0x22EC:2"]`, `stop_tick = 600`.
- [ ] **Step 2:** `light-writers.toml`: a watch with `mem = "DS:0x49EC"`, `size = 6`,
  `arm = "dialog"`, `hits = 200`, and `ignore_ip = [[0x8240, 0x860B]]`; a break at `0x196C`
  (`hits = 50`, `capture = ["stack:8"]`); `stop_tick = 1300`.
- [ ] **Step 3 (live):** Run both plans on both builds. Expected for `light-caller`: every hit has
  `return_far_image == 0x2350` (the patched mapping of it on `patched`) and
  `mem DS:0x49EC:6 == AX BX DX`. A different caller is a finding: keep it and record it.
- [ ] **Step 4:** From `light-writers`, list each distinct writer's image offset with the ticks it
  fired at. Read the variable-13 value at the `0x196C` hits from the registers and stack, and find
  where variable 13 is stored (static decode of `0x196C`'s entry with iced-x86).

### Task 10: Static decode and per-frame comparison

**Files:** Modify `python/scripts/probe_playone_light.py`; test `tests/test_probe_light_script.py`
(create it if absent).

- [ ] **Step 1:** Decode the routine holding `0x234B` with iced-x86 (a scratch script over the
  unpacked image). Record:
  - the loop bounds and where the object list lives (the stack words stepping by 2 from `0x782C`);
  - the header fields `es:[2]`, `es:[4]` and `es:[8]`;
  - `[0x22EC]`;
  - the path from variable 13 to `DS:0x49EC`.
- [ ] **Step 2: Write the failing test** `test_extra_words_flag`. The parser accepts
  `--words DS:0x49EC,DS:0x49EE,DS:0x49F0,DS:<offset>` and maps each item to a
  `(segment, offset)` pair, with `DS` resolved to the layout's `ds`. `<offset>` is variable 13's
  storage, found in Task 9 step 4.
- [ ] **Step 3:** FAIL. **Step 4:** Add `--words` (passed as the `words` argument of
  `luagen.script`, which the trace pass already samples every frame) and `--trace-words`, which
  prints those words for every traced frame. PASS, lint, typecheck.
- [ ] **Step 5 (live):** `mise run probe-light -- --trace-words --words ...` on `CTRY.FLM`.
  Reduce the output to a per-shot table: tick range, var 13, `DS:0x49EC..F0`, `L`, and whether
  they agree. The raw output stays in the data root.

### Task 11: Write-up, then PR B

**Files:** Modify `research/playone-exe/terrain-shade.md` § 4 and open question 1,
`research/playone-exe/memory-map.md` (a `DS:0x49EC` row if it lacks one; add a `# [MEM-*]` anchor
only through `python/stunt_reel/doc_anchors.py`), and `research/parity/log.md` (a row at the end).

- [ ] **Step 1:** The caller (`0x234B`, plus its patched offset), its inputs, every writer at image
  offsets, the per-shot table, and whether variable 13 alone reproduces `L`. Tier
  `[Bounded Observation]` or better, with the plan files and JSONL names cited.
- [ ] **Step 2:** `mise run check`. Commit `docs(research): name what sets PLAYONE's terrain light (#66)`.
  Then stack PR B on A, with `Closes #66`. Confirm with the user before pushing.

---

## PR C: #65, who produces the ground records

### Task 12: `ground_stream.py`

**Files:** Create `python/stunt_reel/ground_stream.py`, `python/scripts/ground_stream.py`,
`tests/test_ground_stream.py`; modify `mise.toml`.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True, slots=True) class Polygon`: `offset: int`, `op: int` (handler image
    offset), `colour: int`, `count: int`, `shades: tuple[int, ...]`, `next_ip: int`
  - `@dataclass(frozen=True, slots=True) class Walk`: `polygons: tuple[Polygon, ...]`,
    `stopped_at: int`, `reason: str`
  - `def walk(stream: bytes, start: int, handlers: Mapping[int, str], vm: int) -> Walk`:
    `handlers` maps VM-space handler IPs to names (`0x171C` is `ground168` and `0x17E4` is
    `ground2BE`, from `world-scene.md` § 4, plus `OP_IPG 0x141F`, `SHADES 0x1241`). The walk
    follows `next_ip` while it names a ground handler and stops with a reason otherwise.
  - CLI `ground_stream.py <jsonl> [--probe ground-objects]` decodes every `mem:ES:SI:4096`
    capture in a debug-x JSONL and prints polygons by colour; the mise task is `ground-stream`.

- [ ] **Step 1: Write the failing tests** on synthetic streams: `test_walks_two_records`,
  `test_count_low_nibble_only` (`w0 = 0xC32D` gives colour `0xC3`, count 13),
  `test_stops_on_unknown_ip`, `test_truncated_stream_stops_cleanly`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement to `world-scene.md` § 2's layout.
  **Step 4:** PASS, lint, typecheck. **Step 5:** Commit `feat(re): decode PLAYONE's live ground stream`.

### Task 13: Find the stream and its producer

**Files:** Create `tools/dosbox-x/plans/ground-objects.toml` and `ground-writer.toml`.

- [ ] **Step 1:** `ground-objects.toml`: three break probes at `0x9100` armed at ticks 10, 273 and
  448 (`hits = 40` each, more than one frame's objects; `capture = ["mem:ES:0:16",
  "mem:ES:SI:4096"]`); breaks at `0x995C` and `0x9A24` (`hits = 300`,
  `capture = ["mem:ES:SI:40"]`).
- [ ] **Step 2 (live):** Run it on `CTRY.FLM` (unpatched) and once on `INTRO.FLM`.
  `mise run ground-stream` over the JSONL lists the polygons per object. Pick one airfield record
  with a colour in 192 to 199 and note its linear address (`ES * 16 + offset + 1`).
- [ ] **Step 3:** `ground-writer.toml`: a watch with `linear = <that address>`, `size = 1`,
  `arm = "dialog"`, `hits = 20`, `ignore_ip = [[0x8240, 0x860B]]`; and an `int` probe, `int = 0x21`,
  `ah = 0x3F`, `hits = 200`, `capture = ["mem:DS:DX:16"]`, plus one with `ah = 0x42`.
- [ ] **Step 4 (live):** Run it. If the watch catches a writer, record its image offset and, for a
  copy loop, the source `DS:SI`. Match the source buffer to an `INT 21h/3Fh` read to get the file
  and offset. If the watch catches nothing because the address moved, take the spec's fallback
  (S5 step 3): re-target the watch at the buffer of the `CTRY.ALL` read.
- [ ] **Step 5:** Repeat steps 2 and 4 with `--build patched`.

### Task 14: Cross-check, compare, write-up, then PR C

**Files:** Modify `research/playone-exe/world-scene.md`, `research/parity/log.md`.

- [ ] **Step 1:** Decode `CTRY.ALL` at the file offset Task 13 found, with the relocation rule.
  The colours must equal the live stream's; a mismatch is a finding and goes in the note.
- [ ] **Step 2:** Build the per-polygon table on `CTRY.FLM`: colour, count, centroid where the
  vertex operands decode, the `MAP.BIN` patch under the centroid (loader order as in
  `terrain-shade.md` § 9) and its colour. Cover the airfield and the coastline first. If vertices
  do not decode, compare colour sets and counts per region and say so.
- [ ] **Step 3:** Name the renderer change (re-bake or draw the player's records), with its sign
  on each film from `attribution.md`'s bounds. Check the INTRO dump for the sand in #70.
- [ ] **Step 4:** Write `world-scene.md`:
  - the producer and colour source at image offsets on both builds;
  - the tiers promoted;
  - open questions 1 to 4 closed or narrowed;
  - the new **Ruled out** entries.

  Add a parity-log row.
- [ ] **Step 5:** `mise run check`. Commit `docs(research): name the producer of PLAYONE's ground records (#65)`.
  Stack PR C on B with `Closes #65`. Ask the user before posting the renderer change on #69.
