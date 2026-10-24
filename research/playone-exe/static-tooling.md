# `PLAYONE.EXE`: Static-Analysis Tooling (Capstone, Ghidra, rea)

* **Binary**: `PLAYONE.EXE` (LZEXE 0.91), unpacked with [`unlzexe.py`](../../python/scripts/unlzexe.py) to the load image `build/re/playone.img`, or with `--mz` to the full MZ file `build/re/playone_unpacked.exe` (201,548 bytes, SHA-256 `4e68d100…ef83f`)
* **Method**: Ghidra 12.1.4 headless and `rea-agents` 6.7.0 trials on 2026-10-23, checked against the facts in [`startup.md`](startup.md), [`sod-vm.md`](sod-vm.md) and [`research/playone-exe/memory-map.md`](memory-map.md)
* **Scope**: which tool answers which question, what Ghidra cannot see in this binary, the address coordinate systems, setup, and the next tooling step
* **Evidence tier**: `[Established]` for the address arithmetic and the slot table; `[Bounded Observation]` for the tool behaviour, which was measured on one binary and one version of each tool

The trial record (timings, the Windows refusal, the load-image attestation) is on branch `rea-eval`, `research/rea-evaluation.md`. This note keeps only what applies going forward.

---

## 1. Which Tool For Which Question

| Question | Tool | Why |
|---|---|---|
| Does this byte pattern or operand occur, and where? | Capstone script over `playone.img` | Seconds, no setup. The DGROUP writer scan for `0x22C4/0x22CE/0x22D0` and the slot-table decode were done this way. |
| What are the functions, their bodies, callers and callees? What does one decompile to? | Ghidra (headless or GUI) on the MZ file | 222 functions recovered, with decompilation and reference tracking. |
| Who reads or writes a fixed DGROUP offset? | Ghidra | Works for absolute `[disp16]` accesses once `DS` is known. The `0x22C4` writer in `entry` shows up in the listing and the pseudocode. |
| The same questions, asked by an agent over MCP, with results that record their inputs | rea, with `--snapshot` | Each result carries the target SHA-256, tool versions and analysis profile. Without a snapshot every call re-imports (about 12 s); with one, about 1.4 s. |
| What value does it hold at tick *n*? Which handler actually runs? What's in the EMS page frame? | DOSBox-X harness ([`capture.md`](capture.md)) | Static tools don't execute or emulate anything. |

## 2. What Ghidra Cannot See Here

* **The display-list VM handlers.** Every handler is reached through a self-patching dispatch slot and a `jmp ax` on a value read from the stream ([`sod-vm.md`](sod-vm.md) section 1). Ghidra finds no function starting in image `0x9100..0xB85C` and reports no xrefs to `0x995C`, `0x9481`, `OP_IPG` (`0x965F`), `OP_FRACTAL` (`0xA56C`) or the slots.
* **Indirect entries.** The light-setup entry `0x9100` has no direct caller, so it has no xref.
* **Work-segment accesses through a pointer.** Accesses via `ES` or a pointer into the display-list work segment don't resolve to a fixed address, so they don't appear as data references.
* **Function boundaries are heuristic.** The PSP parser at `0x0C7C` is inline in `entry`, not a separate function, and the function list is not exhaustive.
* **The packed file.** Analysing `PLAYONE.EXE` itself finds only the LZEXE stub. Always load the `--mz` output.

## 3. Address Coordinate Systems

One instruction has several names. Convert to the image offset before comparing addresses from different sources; a breakpoint copied without converting lands on the wrong bytes ([`capture.md`](capture.md) section 2).

| Coordinate system | Image offset `0x995C` (ground handler) | Conversion from image offset | Where it's used |
|---|---|---|---|
| Image offset | `0x995C` | — | All of `research/playone-exe/` unless stated otherwise |
| Notebook `CS = 0x0F17` | `0x2A2C` | `- 0x6F30` | Older notes, e.g. the `CS:0x1316` dispatch-table address in [`sod-vm.md`](sod-vm.md) |
| VM segment (paragraph `0x824`) | `0x171C` | `- 0x8240` | Opcode words, slot `imm16` values, patched stream words |
| Ghidra / rea analysis address | `0x1995C` | `+ 0x10000` | Load segment `0x1000`; Ghidra shows `1824:171C` in `CODE_1` |
| Runtime linear, `CTRY.FLM` session | `0x11B9C` | `+ 0x8240` | Image loaded at paragraph `0x0824` (`DS = 0x1575`); a VM address is `1048:off` |

DGROUP is image paragraph `0x0D51` (offset `0xD510`). It runs at `DS = 0x1575` in the captured session and at segment `0x1D51` in Ghidra/rea. A `DS:` offset therefore maps to image `0xD510 + off`.

## 4. Setup

These are local tools: they are not in `mise run check`, not in CI, and nothing they produce goes into Git.

| Component | Version | Notes |
|---|---|---|
| Ghidra | 12.1.4 | From the NSA GitHub release (`ghidra_12.1.4_PUBLIC_20260921.zip`). rea accepts only 12.1.x. |
| JDK | 21 (Temurin) | Set `JAVA_HOME` and `GHIDRA_INSTALL_DIR`. |
| Node.js | 24.22.1 | Only needed for rea. |
| rea | `rea-agents` 6.7.0 | Install into a local prefix (`npm install --prefix <dir>`), not globally. Don't run `rea setup`, which writes global agent configuration. |

* **Plain Ghidra runs on Windows.** Its `MzLoader` imports the MZ file directly with language `x86:LE:16:Real Mode`.
* **rea needs Linux.** Its Windows Ghidra adapter refuses DOS MZ ("Windows Ghidra P0 accepts native PE and explicitly selected raw 6502 targets only"), so run rea under WSL2 with a Linux JDK and Node. The Ghidra zip is the same on both platforms.
* **Keep outputs local.** Snapshots, projects and query output go under `build/` (for example `build/scratch/rea/`) or the WSL home directory.
* **rea forgets annotations.** Renames and comments last only for one session. Notes in `research/` are the durable record.

## 5. Next Step: Turn The Slot Table Into Functions

The slot table at image `0x8240` gives the address of every one of the 108 handlers (`imm16 + 0x8240`). A short Ghidra headless post-script could use it to:

1. create a function at each handler address,
2. name it from the opcode table in [`research/formats/sod.md`](../formats/sod.md),
3. save the project under `build/re/ghidra/`.

That would make the VM handlers decompilable and give them callers, callees and data references. That's what the open static questions need: the 14 unimplemented opcodes in [`sod-opcode-coverage.md`](../sod-opcode-coverage.md), the viewport setter for `0x41C8/0x41CA`, and who sets `0x9100`'s inputs. rea can't do this itself, because it only edits existing functions and keeps nothing between sessions, so this is plain Ghidra work. If the script proves useful, keep it under `python/scripts/` or a `tools/ghidra/` directory with a note on how to run it.

## 6. Evidence Rules For Tool Output

* Decompiler pseudocode and auto-generated names (`FUN_1824_0e4e`) are `[Hypothesis]` until the instruction bytes at the address are checked in the image.
* Record each finding by its image offset. Give a Ghidra/rea address alongside it only when it helps someone re-run the query.
* Note the tool and version that found it (for example "Ghidra 12.1.4 via rea 6.7.0") and the target SHA-256 when a result depends on the loader.
* Absence of an xref is a `[Bounded Observation]` about Ghidra's analysis, not proof that no reference exists (section 2).
