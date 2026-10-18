# `PLAYONE.EXE`: Memory Architecture & Data Segment Layout

This document details the real-mode x86 memory layout, static data segment (`DGROUP`) pointers, dynamic heap allocations, and Memory Control Block (MCB) structure of `PLAYONE.EXE`.

---

## 1. Segment Architecture & DGROUP Map

`PLAYONE.EXE` executes as a 16-bit MS-DOS real-mode application. Static variables, string literals, and system buffers reside within the primary data segment `DGROUP`.

* **DGROUP Segment**: `0x0D51` (unpacked file offset `0xD910`)
* **Register Context**: `DS` points to `DGROUP` throughout core execution.

### DGROUP Offset Reference Table

| Offset in `DS` | Data Type | Value / Purpose |
|---|---|---|
| `0x05AC` | Null-terminated string | `"game.cfg"` — Hardware and sound driver configuration file |
| `0x05B5` | Null-terminated string | `"game.var"` — Game variables and runtime state definition |
| `0x05BE` | Null-terminated string | `"install.exe"` — Configuration installer executable |
| `0x05CA` | Null-terminated string | `"pfont.bin"` — Proportional UI font metrics and bitmap data |
| `0x05D4` | Null-terminated string | `"pilots"` — Pilot profile folder path |
| `0x05DB` | Null-terminated string | `"res\*.res"` — Core resource archive wildcard pattern |
| `0x065D` | DOS String (`$`-terminated) | `"Not enough memory.  Stunt Island requires 570,000 bytes free."` |
| `0x069B` | DOS String (`$`-terminated) | `"Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."` |
| `0x0A58` | Null-terminated string | `"VAULT\*.*"` — Search pattern for film loading dialog |
| `0x0A62` | Null-terminated string | `"LOAD FILM"` — Title string rendered on file dialog header |
| `0x0AAB` | Character Buffer | Destination buffer storing the selected film relative path |
| `0x2263` | 8-bit Byte | Active video/display mode flag |
| `0x2264` | 8-bit Byte | Sound driver hardware mode |
| `0x2265` | 8-bit Byte | Audio playback channel flag |
| `0x22C4` | 16-bit Word | Stored PSP segment address |
| `0x22CE` | 16-bit Word | Preserved `SS` register during `INSTALL.EXE` child execution |
| `0x22D0` | 16-bit Word | Preserved `SP` register during `INSTALL.EXE` child execution |

---

## 2. Conventional Memory Organization & MCB Layout

Under MS-DOS, conventional memory (0 to 640 KB) is managed as a linked list of Memory Control Blocks (MCBs). Each block begins on a 16-byte paragraph boundary with a 16-byte header:

```
+-----------------------------------------------------------------------+
| Byte 0: Block Type ('M' = Member block, 'Z' = End of chain)           |
| Bytes 1-2: Owner PSP Segment address                                  |
| Bytes 3-4: Size of allocated memory block in paragraphs (1 para = 16B)|
| Bytes 5-7: Reserved                                                   |
| Bytes 8-15: Program or Block Name (DOS 4.0+)                          |
+-----------------------------------------------------------------------+
| Payload: Allocated memory paragraphs                                  |
+-----------------------------------------------------------------------+
```

### Runtime MCB Chain Analysis

When `PLAYONE.EXE` is loaded and running film playback, conventional memory is partitioned into the following primary blocks:

| Block Role | Typical Size | Relative Segment | Description |
|---|---|---|---|
| **Environment Block** | ~1,168 bytes | Base allocation | Holds DOS environment variables and execution paths |
| **Program Binary Block** | ~202,832 bytes | Executable base | Unpacked code, static `DGROUP` data, stack, and font buffers |
| **Dynamic Scene Graph Buffer** | ~419,408 bytes | Heap allocation | 3D world geometry, camera tracks, and actor motion vectors |
| **Upper Memory / Driver Blocks** | ~81,904 bytes | Upper memory | Audio driver buffers, hardware DMA buffers |

### Memory Requirement Rationale

During startup, `PLAYONE.EXE` explicitly checks for at least **570,000 bytes** (`0x8B29` paragraphs) of free conventional RAM:

$$\text{Required Free Memory} = 570{,}000\text{ bytes} \approx 556.6\text{ KB}$$

This requirement accounts for:
1. **The uncompressed executable image**: $\approx 203\text{ KB}$.
2. **The 3D scene and trajectory buffer**: $\approx 419\text{ KB}$ dynamically allocated when `.ALL` and `.FLM` assets are loaded into memory.
3. **DOS scratch structures and I/O buffers**: File handle tables and sound hardware buffers.

If total available conventional memory falls below this threshold, the application aborts prior to allocating the dynamic scene graph.
