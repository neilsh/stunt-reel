"""Unelevated stack sampler for #1002: where Windows lavapipe spends the render loop.

`record` launches a command, waits for its `[probe] loop_start` stderr line, then on every
sweep suspends each of the child's threads, reads its instruction and stack pointers, keeps
the stack's first qwords that point into a loaded module, and resumes it, until
`[probe] loop_ms`.
`report` resolves those addresses with dbghelp and the modules' PDBs, keeps the stack
qwords that follow a call instruction as an approximate call stack, and sorts each sample
into the parts #1002 names.

Kernel ETW sampling (WPR) needs an elevated shell, which an unattended run lacks; this
needs only access to its own child.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import struct
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

K32 = ctypes.WinDLL("kernel32", use_last_error=True)
NTDLL = ctypes.WinDLL("ntdll")

PROCESS_QUERY_INFORMATION = 0x400
PROCESS_VM_READ = 0x10
THREAD_ACCESS = 0x2 | 0x8 | 0x40 | 0x800
CONTEXT_CONTROL = 0x100001
CTX_SIZE = 1232
CTX_FLAGS, CTX_RSP, CTX_RIP = 0x30, 0x98, 0xF8
STACK_BYTES = 32 * 1024
MAX_CANDS = 96
MAX_FRAMES = 32


class THREADENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ThreadID", wt.DWORD),
        ("th32OwnerProcessID", wt.DWORD),
        ("tpBasePri", wt.LONG),
        ("tpDeltaPri", wt.LONG),
        ("dwFlags", wt.DWORD),
    ]


class MODULEINFO(ctypes.Structure):
    _fields_ = [("base", ctypes.c_void_p), ("size", wt.DWORD), ("entry", ctypes.c_void_p)]


class THREAD_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("ExitStatus", wt.LONG),
        ("TebBaseAddress", ctypes.c_void_p),
        ("UniqueProcess", ctypes.c_void_p),
        ("UniqueThread", ctypes.c_void_p),
        ("AffinityMask", ctypes.c_void_p),
        ("Priority", wt.LONG),
        ("BasePriority", wt.LONG),
    ]


K32.OpenThread.restype = wt.HANDLE
K32.OpenProcess.restype = wt.HANDLE
K32.CreateToolhelp32Snapshot.restype = wt.HANDLE
K32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
K32.GetThreadContext.argtypes = [wt.HANDLE, ctypes.c_void_p]
K32.SuspendThread.argtypes = [wt.HANDLE]
K32.ResumeThread.argtypes = [wt.HANDLE]
K32.GetThreadTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
K32.GetThreadDescription.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]


def thread_ids(pid: int) -> list[int]:
    snap = K32.CreateToolhelp32Snapshot(4, 0)
    entry = THREADENTRY32()
    entry.dwSize = ctypes.sizeof(entry)
    out = []
    ok = K32.Thread32First(snap, ctypes.byref(entry))
    while ok:
        if entry.th32OwnerProcessID == pid:
            out.append(entry.th32ThreadID)
        ok = K32.Thread32Next(snap, ctypes.byref(entry))
    K32.CloseHandle(snap)
    return out


def modules(hproc: int) -> list[dict]:
    arr = (ctypes.c_void_p * 1024)()
    needed = wt.DWORD()
    K32.K32EnumProcessModulesEx(hproc, arr, ctypes.sizeof(arr), ctypes.byref(needed), 3)
    out = []
    for i in range(needed.value // ctypes.sizeof(ctypes.c_void_p)):
        name = ctypes.create_unicode_buffer(1024)
        K32.K32GetModuleFileNameExW(hproc, ctypes.c_void_p(arr[i]), name, 1024)
        info = MODULEINFO()
        K32.K32GetModuleInformation(
            hproc, ctypes.c_void_p(arr[i]), ctypes.byref(info), ctypes.sizeof(info)
        )
        out.append({"path": name.value, "base": info.base, "size": info.size})
    return out


def thread_cpu_100ns(h: int) -> int:
    t = [wt.FILETIME() for _ in range(4)]
    K32.GetThreadTimes(h, *[ctypes.byref(x) for x in t])
    return sum((x.dwHighDateTime << 32) | x.dwLowDateTime for x in t[2:])


class Thread:
    def __init__(self, tid: int, hproc: int) -> None:
        self.tid = tid
        self.h = K32.OpenThread(THREAD_ACCESS, False, tid)
        tbi = THREAD_BASIC_INFORMATION()
        NTDLL.NtQueryInformationThread(
            wt.HANDLE(self.h), 0, ctypes.byref(tbi), ctypes.sizeof(tbi), None
        )
        base = ctypes.c_uint64()
        K32.ReadProcessMemory(
            hproc, ctypes.c_void_p((tbi.TebBaseAddress or 0) + 8), ctypes.byref(base), 8, None
        )
        self.stack_base = base.value
        desc = ctypes.c_wchar_p()
        K32.GetThreadDescription(self.h, ctypes.byref(desc))
        self.name = desc.value or ""
        self.cpu0 = thread_cpu_100ns(self.h) if self.h else 0


def record(args: argparse.Namespace) -> None:
    env = dict(os.environ)
    for kv in args.env or []:
        k, _, v = kv.partition("=")
        env[k] = v
    proc = subprocess.Popen(
        args.cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
    )
    state = {"start": threading.Event(), "stop": threading.Event(), "loop_ms": None}
    lines: list[str] = []

    def pump() -> None:
        for line in proc.stderr:
            lines.append(line.rstrip())
            if line.startswith("[probe] loop_start"):
                state["start"].set()
            elif line.startswith("[probe] loop_ms"):
                state["loop_ms"] = int(line.split()[-1])
                state["stop"].set()
        state["stop"].set()
        state["start"].set()

    threading.Thread(target=pump, daemon=True).start()
    hproc = K32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, proc.pid)
    first_tids = []
    while not first_tids:
        first_tids = thread_ids(proc.pid)
    main_tid = first_tids[0]
    state["start"].wait()
    mods = modules(hproc)
    ranges = np.array(sorted((m["base"], m["base"] + m["size"]) for m in mods), dtype=np.uint64)
    lo, hi = ranges[:, 0], ranges[:, 1]
    threads: dict[int, Thread] = {}
    ctx_raw = ctypes.create_string_buffer(CTX_SIZE + 16)
    ctx_addr = (ctypes.addressof(ctx_raw) + 15) & ~15
    stack = ctypes.create_string_buffer(STACK_BYTES)
    got = ctypes.c_size_t()
    sweeps, tids, rips, cands = [], [], [], []
    sweep_t = []
    interval = 1.0 / args.rate if args.rate > 0 else 0.0
    next_refresh = 0.0
    t0 = time.perf_counter()
    n = 0
    busy = 0.0
    while args.rate > 0 and not state["stop"].is_set():
        now = time.perf_counter()
        if now >= next_refresh:
            for tid in thread_ids(proc.pid):
                if tid not in threads:
                    threads[tid] = Thread(tid, hproc)
            next_refresh = now + 0.25
        for th in threads.values():
            if not th.h or K32.SuspendThread(th.h) == 0xFFFFFFFF:
                continue
            struct.pack_into("<I", (ctypes.c_char * CTX_SIZE).from_address(ctx_addr), CTX_FLAGS, CONTEXT_CONTROL)
            ok = K32.GetThreadContext(th.h, ctypes.c_void_p(ctx_addr))
            if ok:
                rsp, rip = struct.unpack_from("<Q", (ctypes.c_char * CTX_SIZE).from_address(ctx_addr), CTX_RSP)[0], struct.unpack_from("<Q", (ctypes.c_char * CTX_SIZE).from_address(ctx_addr), CTX_RIP)[0]
                want = min(STACK_BYTES, max(0, th.stack_base - rsp)) & ~7
                rd = K32.ReadProcessMemory(hproc, ctypes.c_void_p(rsp), stack, want, ctypes.byref(got)) if want else 0
            K32.ResumeThread(th.h)
            if not ok:
                continue
            row = np.zeros(MAX_CANDS, dtype=np.uint64)
            if rd:
                q = np.frombuffer(stack.raw[: got.value], dtype=np.uint64)
                idx = np.searchsorted(lo, q, side="right") - 1
                inr = (idx >= 0) & (q < hi[np.clip(idx, 0, None)])
                hits = q[inr][:MAX_CANDS]
                row[: len(hits)] = hits
            sweeps.append(n)
            tids.append(th.tid)
            rips.append(rip)
            cands.append(row)
        sweep_t.append(now - t0)
        n += 1
        busy += time.perf_counter() - now
        delay = now + interval - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
    state["stop"].wait()
    wall = time.perf_counter() - t0
    cpu = {tid: (thread_cpu_100ns(th.h) - th.cpu0) / 1e4 for tid, th in threads.items() if th.h}
    proc.wait()
    out = Path(args.out)
    np.savez_compressed(
        out.with_suffix(".npz"),
        sweep=np.array(sweeps, dtype=np.uint32),
        tid=np.array(tids, dtype=np.uint32),
        rip=np.array(rips, dtype=np.uint64),
        cands=np.array(cands, dtype=np.uint64),
    )
    meta = {
        "cmd": args.cmd,
        "env": args.env,
        "main_tid": main_tid,
        "loop_ms": state["loop_ms"],
        "sweeps": n,
        "sample_wall_s": wall,
        "sampler_busy_s": busy,
        "threads": {th.tid: {"name": th.name, "cpu_ms": cpu.get(th.tid)} for th in threads.values()},
        "modules": mods,
        "exit": proc.returncode,
        "stderr_tail": lines[-20:],
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(f"loop_ms {state['loop_ms']} sweeps {n} samples {len(tids)} busy {busy:.1f}s/{wall:.1f}s exit {proc.returncode}")


# ---------------------------------------------------------------- report


class SYMBOL_INFOW(ctypes.Structure):
    _fields_ = [
        ("SizeOfStruct", wt.ULONG),
        ("TypeIndex", wt.ULONG),
        ("Reserved", ctypes.c_uint64 * 2),
        ("Index", wt.ULONG),
        ("Size", wt.ULONG),
        ("ModBase", ctypes.c_uint64),
        ("Flags", wt.ULONG),
        ("Value", ctypes.c_uint64),
        ("Address", ctypes.c_uint64),
        ("Register", wt.ULONG),
        ("Scope", wt.ULONG),
        ("Tag", wt.ULONG),
        ("NameLen", wt.ULONG),
        ("MaxNameLen", wt.ULONG),
        ("Name", ctypes.c_wchar * 1024),
    ]


class Image:
    """A module's file bytes addressed by RVA, to test whether a stack qword follows a call."""

    def __init__(self, path: str) -> None:
        self.data = Path(path).read_bytes()
        pe = struct.unpack_from("<I", self.data, 0x3C)[0]
        nsec = struct.unpack_from("<H", self.data, pe + 6)[0]
        opt = struct.unpack_from("<H", self.data, pe + 20)[0]
        sec = pe + 24 + opt
        self.secs = []
        for i in range(nsec):
            vsize, va, rsize, raw = struct.unpack_from("<IIII", self.data, sec + 40 * i + 8)
            chars = struct.unpack_from("<I", self.data, sec + 40 * i + 36)[0]
            if chars & 0x20000000:  # executable
                self.secs.append((va, va + min(vsize, rsize), raw))

    def follows_call(self, rva: int) -> bool:
        for va, end, raw in self.secs:
            if va + 7 <= rva < end:
                b = self.data[raw + rva - va - 7 : raw + rva - va]
                if b[2] == 0xE8:
                    return True
                for k in (2, 3, 4, 6, 7):
                    if b[7 - k] == 0xFF and ((b[7 - k + 1] >> 3) & 7) == 2:
                        return True
                return False
        return False


class Symbols:
    def __init__(self, mods: list[dict], search: str) -> None:
        dbghelp_path = r"C:\Program Files (x86)\Windows Kits\10\Debuggers\x64\dbghelp.dll"
        self.dh = ctypes.WinDLL(dbghelp_path if Path(dbghelp_path).exists() else "dbghelp")
        self.dh.SymSetOptions(0x2 | 0x4 | 0x10)  # undname, deferred loads, no-cpp... lines off
        self.h = wt.HANDLE(0x1002)
        self.dh.SymInitializeW(self.h, ctypes.c_wchar_p(search), False)
        self.dh.SymLoadModuleExW.restype = ctypes.c_uint64
        self.dh.SymLoadModuleExW.argtypes = [
            wt.HANDLE, wt.HANDLE, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_uint64, wt.DWORD, ctypes.c_void_p, wt.DWORD,
        ]
        self.dh.SymFromAddrW.argtypes = [
            wt.HANDLE, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(SYMBOL_INFOW)
        ]
        self.mods = sorted(mods, key=lambda m: m["base"])
        self.bases = [m["base"] for m in self.mods]
        self.images: dict[str, Image | None] = {}
        for m in self.mods:
            self.dh.SymLoadModuleExW(self.h, None, m["path"], None, m["base"], m["size"], None, 0)
            m["short"] = Path(m["path"]).name.lower()
        self.cache: dict[int, str] = {}
        self.returns: dict[int, bool] = {}

    def module(self, addr: int) -> dict | None:
        import bisect

        i = bisect.bisect_right(self.bases, addr) - 1
        if i >= 0 and addr < self.mods[i]["base"] + self.mods[i]["size"]:
            return self.mods[i]
        return None

    def image(self, m: dict) -> Image | None:
        if m["short"] not in self.images:
            try:
                self.images[m["short"]] = Image(m["path"])
            except OSError:
                self.images[m["short"]] = None
        return self.images[m["short"]]

    def name(self, addr: int) -> str:
        if addr in self.cache:
            return self.cache[addr]
        m = self.module(addr)
        if m is None:
            s = "<jit>"
        else:
            info = SYMBOL_INFOW()
            info.SizeOfStruct = 88
            info.MaxNameLen = 1024
            disp = ctypes.c_uint64()
            if self.dh.SymFromAddrW(self.h, addr, ctypes.byref(disp), ctypes.byref(info)):
                s = f"{m['short']}!{info.Name}"
            else:
                s = f"{m['short']}!?"
        self.cache[addr] = s
        return s

    def is_return(self, addr: int) -> bool:
        hit = self.returns.get(addr)
        if hit is None:
            m = self.module(addr)
            img = self.image(m) if m else None
            hit = bool(img and img.follows_call(addr - m["base"]))
            self.returns[addr] = hit
        return hit


WAITS = (
    "NtWait", "ZwWait", "NtDelay", "WaitFor", "SleepCondition", "NtRemove", "NtYield",
    "SwitchToThread", "RtlSleepConditionVariable",
)
# Functions that bin a primitive for lines and triangles alike: the primitive's own setup
# function further up names the part.
BINNING = ("lp_setup_bin_triangle", "lp_scene_bin", "lp_scene_new_cmd_block", "lp_setup_alloc_triangle")
LINE = ("try_setup_line", "lp_setup_line", "setup_line_coefficients", "line_both")
TRI = (
    "do_triangle_ccw", "triangle_ccw", "triangle_cw", "triangle_both", "retry_triangle_ccw",
    "lp_setup_whole_tri", "setup_rect", "try_rect", "lp_setup_bin_rectangle", "try_setup_rect",
    "lp_setup_analyse_triangles", "do_rect_ccw", "lp_setup_triangle", "setup_tri_coefficients",
)
STATE = (
    "lp_setup_update_state", "llvmpipe_update_derived", "llvmpipe_update_fs", "llvmpipe_update_setup",
    "lp_make_setup_variant_key", "handle_graphics_pipeline", "handle_graphics_stages",
    "handle_vertex_buffers", "emit_state", "compute_vertex_info", "prepare_shader_images",
    "lp_setup_set_", "cso_", "apply_dynamic_offsets", "lvp_descriptor_set_create",
    "handle_descriptor_sets", "handle_set_stage", "llvmpipe_bind_", "llvmpipe_set_", "draw_set_",
    "draw_bind_", "draw_prepare_shader_outputs", "handle_push_constants", "update_pcbuf",
    "llvmpipe_delete_", "llvmpipe_create_", "lp_setup_update_shader", "draw_compute_vertex_size",
)
VERTEX = (
    "llvm_pipeline_generic", "llvm_middle_end", "draw_pt_", "vsplit_", "draw_vbo", "draw_instances",
    "draw_new_instance", "draw_pipeline_run", "pipe_run_elts", "do_clip_", "clip_", "vbuf_",
    "draw_llvm", "fetch_", "translate_", "draw_do_flush", "draw_flush", "draw_pipeline_flush",
    "draw_unfilled", "draw_cull", "do_cull",
)
COMPILE = ("llvm::", "gallivm_", "lp_build_", "generate_variant", "generate_setup_variant", "lp_bld_", "LLVM")
FLUSH = (
    "llvmpipe_flush", "lp_setup_flush", "set_scene_state", "lp_rast_queue_scene", "lp_scene_end",
    "lp_scene_begin", "lp_fence", "finish_fence", "llvmpipe_fence", "lp_setup_end_query",
    "lp_scene_free", "lp_scene_reset", "lp_scene_create", "lp_setup_get_empty_scene", "begin_binning",
    "lp_setup_rasterize_scene", "lp_rast_finish", "execute_clears",
)
CLEAR = ("render_clear", "llvmpipe_clear", "util_clear_", "util_fill_", "lp_setup_clear")
COPY = (
    "handle_copy_image_to_buffer", "util_copy_", "lp_resource_copy", "llvmpipe_transfer_map",
    "util_resource_copy_region", "handle_copy_buffer", "handle_update_buffer",
)
DISPATCH = (
    "lvp_execute_cmd_buffer", "lvp_execute_cmds", "lvp_queue_submit", "vk_queue_submit_final",
    "vk_queue_", "lvp_", "vk_common_", "vk_sync", "vk_free", "llvmpipe_draw_vbo",
)


def has(f: str, names: tuple[str, ...]) -> bool:
    return any(f.startswith(n) or n in f for n in names)


def classify_setup(fn: list[str], leaf_mod: str) -> str:
    """The part a queue- or main-thread sample belongs to: its first owning frame, leaf first."""
    if any(w in fn[0] for w in WAITS):
        for f in fn[1:12]:
            if has(f, ("lp_fence", "llvmpipe_fence", "finish_fence", "llvmpipe_flush")):
                return "wait: rasterizer threads (fence)"
            if f.startswith("lvp_pipe_sync") or f.startswith("vk_sync") or "timeline" in f:
                return "wait: lavapipe queue (fence)"
            if f.startswith("vk_queue_submit_thread_func"):
                return "idle: queue thread awaiting a submit"
        return "wait: other"
    binned = False
    for f in fn:
        if f == "<jit>":
            continue
        if f.startswith("try_update_scene_state"):
            return "state: storing the fragment state (try_update_scene_state)"
        if has(f, BINNING):
            binned = True
            continue
        if has(f, LINE):
            return "setup: lines (setup and binning)"
        if has(f, TRI):
            return "setup: triangles (setup and binning)"
        if f.startswith("lp_setup_draw_elements"):
            return "setup: primitive dispatch (lp_setup_draw_elements)"
        if has(f, COMPILE):
            return "jit compile (LLVM)"
        if has(f, FLUSH):
            return "scene flush and reset"
        if has(f, CLEAR):
            return "clears"
        if has(f, COPY):
            return "copies (readback, uploads)"
        if has(f, STATE):
            return "state: other changes and pipeline binds"
        if has(f, VERTEX):
            return "vertex: draw module (fetch, shade, clip)"
        if has(f, DISPATCH):
            return "dispatch: command execution and queue submit"
        if f.startswith(("wgpu_core::", "wgpu_hal::", "wgpu::")):
            return "wgpu (main thread)"
        if f.startswith(("stunt_", "stuntreel")):
            return "stunt-reel code (main thread)"
    if binned:
        return "setup: binning, primitive not found"
    if fn[0] == "<jit>":
        return "jit code, caller not found"
    return f"unattributed ({leaf_mod})"


def planes_of(f: str) -> str | None:
    """The plane count a rasterizer function's name carries (`lp_rast_triangle_32_4` is 4)."""
    for prefix in ("lp_rast_triangle_32_", "lp_rast_triangle_", "do_block_16_32_", "do_block_16_", "do_block_4_"):
        if f.startswith(prefix):
            rest = f[len(prefix) :]
            if rest[:1].isdigit():
                return rest[:1]
    return None


def classify_raster(fn: list[str], leaf_mod: str) -> str:
    """The part a rasterizer-thread sample belongs to, with the primitive's plane count."""
    if any(w in fn[0] for w in WAITS):
        return "idle"
    prim = "?"
    for f in fn:
        if f.startswith("lp_rast_shade_tile"):
            prim = "whole tile"
            break
        n = planes_of(f)
        if n:
            prim = f"{n}-plane"
            break
    leaf = fn[0]
    if leaf == "<jit>":
        return f"fragment shading (JIT) [{prim}]"
    if leaf.startswith(("lp_rast_shade", "lp_rast_blit")):
        return f"shading dispatch [{prim}]"
    if planes_of(leaf) or leaf.startswith(("lp_rast_triangle", "do_block", "build_mask")):
        return f"coverage [{prim}]"
    if "clear" in leaf:
        return "clears"
    if leaf.startswith(("lp_rast", "lp_scene", "rasterize")):
        return "rasterizer bookkeeping"
    if leaf.startswith(("memcpy", "memset")):
        return f"memcpy/memset [{prim}]"
    return f"unattributed ({leaf_mod})"


def part(frames: list[str], role: str) -> str:
    fn = [f.split("!", 1)[-1] for f in frames]
    mod = frames[0].split("!", 1)[0]
    return classify_raster(fn, mod) if role == "raster" else classify_setup(fn, mod)


def report(args: argparse.Namespace) -> None:
    base = Path(args.rec)
    meta = json.loads(base.with_suffix(".json").read_text())
    with np.load(base.with_suffix(".npz")) as npz:
        data = {k: npz[k] for k in npz.files}  # an NpzFile decompresses on every access
    syms = Symbols(meta["modules"], args.search)
    roles: dict[int, str] = {}
    main_tid = meta["main_tid"]
    stacks: dict[int, list[list[str]]] = defaultdict(list)
    for tid, rip, row in zip(data["tid"].tolist(), data["rip"].tolist(), data["cands"].tolist()):
        frames = [syms.name(rip)]
        for c in row:
            if c == 0 or len(frames) >= MAX_FRAMES:
                break
            if syms.is_return(c):
                frames.append(syms.name(c))
        stacks[tid].append(frames)
    for tid, ss in stacks.items():
        joined = Counter(f for s in ss for f in s)
        if tid == main_tid:
            roles[tid] = "main"
        elif any("vk_queue_submit_thread_func" in f for f in joined):
            roles[tid] = "queue"
        elif any("lp_cs_tpool_worker" in f for f in joined):
            roles[tid] = "compute pool"
        elif any(f.split("!")[-1].startswith("lp_rast_") for f in joined):
            roles[tid] = "raster"
        else:
            roles[tid] = "other"
    out = {"loop_ms": meta["loop_ms"], "sweeps": meta["sweeps"], "threads": {}, "parts": {}}
    for tid, ss in sorted(stacks.items(), key=lambda kv: -len(kv[1])):
        role = roles[tid]
        info = meta["threads"].get(str(tid), {})
        c = Counter(part(s, role) for s in ss)
        leaf = Counter(s[0] for s in ss)
        out["threads"][tid] = {
            "role": role,
            "name": info.get("name"),
            "cpu_ms": info.get("cpu_ms"),
            "samples": len(ss),
            "parts": c.most_common(),
            "leaf_top": leaf.most_common(args.top),
        }
    agg: dict[str, Counter] = defaultdict(Counter)
    for tid, ss in stacks.items():
        role = roles[tid]
        for s in ss:
            agg[role][part(s, role)] += 1
    out["parts"] = {r: c.most_common() for r, c in agg.items()}
    if args.dump_main:
        ms = Counter(" < ".join(s[:6]) for s in stacks[main_tid])
        out["main_stacks"] = ms.most_common(args.dump_main)
    if args.dump_role:
        rs = Counter(
            " < ".join(s[:8]) for tid, ss in stacks.items() if roles[tid] == args.dump_role for s in ss
        )
        out["role_stacks"] = rs.most_common(args.top)
    text = json.dumps(out, indent=1)
    Path(args.json_out or base.with_suffix(".report.json")).write_text(text)
    print(f"wrote {args.json_out or base.with_suffix('.report.json')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd_name", required=True)
    r = sub.add_parser("record")
    r.add_argument("--out", required=True)
    r.add_argument("--rate", type=float, default=250.0)
    r.add_argument("--env", action="append")
    r.add_argument("cmd", nargs=argparse.REMAINDER)
    p = sub.add_parser("report")
    p.add_argument("rec")
    p.add_argument("--search", required=True)
    p.add_argument("--top", type=int, default=40)
    p.add_argument("--dump-main", type=int, default=0)
    p.add_argument("--dump-role")
    p.add_argument("--json-out")
    args = ap.parse_args()
    if args.cmd_name == "record":
        if args.cmd and args.cmd[0] == "--":
            args.cmd = args.cmd[1:]
        record(args)
    else:
        report(args)


if __name__ == "__main__":
    sys.exit(main())
