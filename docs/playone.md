# Reverse Engineering Reference: PLAYONE.EXE (Stunt Island Player)

This document records the internal structure, memory locations, argument parsing, file formats, and runtime behavior of `PLAYONE.EXE` (from the Stunt Island Demo / corpus `stisldem`), discovered through binary disassembly, static analysis, and dynamic tracing via the DOSBox-X debugger MCP server.

---

## 1. Executable Overview

| Attribute | Details |
|---|---|
| **Binary Name** | `PLAYONE.EXE` |
| **Origin** | Walt Disney Computer Software / The Assembly Line (1992) |
| **Executable Format** | 16-bit x86 MS-DOS MZ Executable |
| **Compression** | Packed with **LZEXE 0.91** (`LZ91` header at offset `0x1C`) |
| **Packed File Size** | 102,703 bytes |
| **Unpacked File Size** | 201,548 bytes |
| **Unpacked Entry Point** | `CS:IP = 0000:0C5Eh` |
| **Header Paragraphs** | 64 paragraphs (1,024 bytes header in unpacked form) |
| **Relocation Entries** | 213 relocations |
| **DGROUP (Data Segment)** | Segment `0x0D51` (file offset `0xD910` in unpacked image) |

---

## 2. Command-Line Argument Parsing

`PLAYONE.EXE` does **not** accept film paths or file arguments. It evaluates only the first non-space character of the command tail:

### Disassembly (`0x0C7C` – `0x0CBD`)
```assembly
0x0c7c: mov    si, 80h              ; PSP:0080h (command tail length byte)
0x0c7f: lodsb  al, es:[si]          ; Read length byte
0x0c81: mov    bl, al               ; BL = length
0x0c83: xor    al, al
0x0c85: mov    bh, al
0x0c87: mov    es:[bx + si], al     ; Null-terminate the command tail in PSP
0x0c8a: lodsb  al, es:[si]          ; Read next character
0x0c8c: cmp    al, 20h              ; Skip leading whitespace (' ')
0x0c8e: je     0x0c8a
0x0c90: cmp    al, 3Fh              ; Check if character is literal '?' (ASCII 0x3F)
0x0c92: jne    0x0ccc               ; If NOT '?', jump to normal startup!
; If character is '?':
0x0cb0: mov    dx, 05BEh            ; DS:05BEh -> "install.exe"
0x0cb3: mov    ax, ds
0x0cb5: mov    es, ax
0x0cb7: mov    bx, 0701h            ; Parameter block for EXEC
0x0cba: mov    ax, 4B00h            ; INT 21h AH=4Bh (EXEC program)
0x0cbd: int    21h                  ; Run INSTALL.EXE
```

### Key Findings
* **`playone.exe ?`**: Spawns `INSTALL.EXE` (the hardware / sound setup utility).
* **`playone.exe /?`**: The first non-space character is `'/'` (`0x2F`), which fails the `cmp al, 3Fh` check. It is treated as normal startup and launches straight into the GUI.
* **Filenames / switches (`playone.exe CTRY.FLM`)**: All command-line arguments other than a lone `?` are ignored.

---

## 3. Startup & Memory Requirements

Following argument parsing (at `0x0CCC`):

1. **Configuration Verification**:
   - Attempts to open `game.cfg` (`DS:05ACh`).
   - If `game.cfg` is missing or unreadable (`0x0CD5: jb 0x0C94`), it immediately falls back to launching `install.exe`.
2. **Memory Size Check (`0x0CF6` – `0x0D0A`)**:
   - Reads the top of available memory from `PSP:0002h`.
   - Requires at least **570,000 bytes** (`0x8B29` paragraphs) of free conventional memory.
   - If memory is insufficient, prints string at `DS:065Dh` via `INT 21h AH=09h` and exits:
     ```text
     "Not enough memory.  Stunt Island requires 570,000 bytes free."
     ```
3. **Disk Space Check (`0x0D0D` – `0x0D34`)**:
   - Calls `INT 21h, AH=36h` (Get Free Disk Space).
   - Requires at least **70,000 bytes** free on the current drive.
   - Error string at `DS:069Bh`:
     ```text
     "Not enough free disk space to run.  Stunt Island requires 70,000 bytes of free disk space."
     ```

---

## 4. DGROUP Data Segment Pointers (`DS = 0xD51`)

| Offset in DS | String / Content | Purpose |
|---|---|---|
| `0x05AC` | `"game.cfg"` | Sound and hardware settings file |
| `0x05B5` | `"game.var"` | Game variables / runtime state |
| `0x05BE` | `"install.exe"` | Configuration installer executable |
| `0x05CA` | `"pfont.bin"` | Proportional UI font data |
| `0x05D4` | `"pilots"` | Pilots profile directory |
| `0x05DB` | `"res\*.res"` | Resource package files |
| `0x065D` | `"Not enough memory..."` | Out-of-memory error message |
| `0x069B` | `"Not enough free disk space..."` | Out-of-disk-space error message |
| `0x0A58` | `"VAULT\*.*"` | File search pattern for Load dialog |
| `0x0A62` | `"LOAD FILM"` | Dialog title text |
| `0x0AAB` | Buffer | Selected film destination path buffer |
| `0x2263` | Byte | Active display / video mode flag |
| `0x2264` | Byte | Sound driver mode |
| `0x2265` | Byte | Audio playback channel flag |
| `0x22C4` | Word | Saved PSP segment address |
| `0x22CE` | Word | Saved SS during `install.exe` exec |
| `0x22D0` | Word | Saved SP during `install.exe` exec |

---

## 5. File Selection Dialog & Keystroke Handling

The film load interface does **not** contain an editable text field. It is implemented as a single-character prefix search listbox.

### Invocation (`0x49C6` – `0x49D2`)
```assembly
0x49c6: mov    si, 0A58h            ; "VAULT\*.*"
0x49c9: mov    di, 0AABh            ; Output buffer
0x49cc: mov    bx, 0A62h            ; "LOAD FILM"
0x49cf: call   0787h                ; Initialize & run file picker dialog
0x49d2: jb     0x49ed               ; Cancelled (Esc)
```

### Dialog Key Evaluation (`0x0C10` – `0x0C2C`)
* **`Enter` (`0x0D`)**: Jumps to `0x0A1B` to confirm the selected file and initiate playback.
* **`Esc` (`0x1B`)**: Jumps to `0x0A14` to close the dialog and return to the main menu.
* **Other Keys**: Forwarded to `0x5EC6` (listbox navigation handler).

### Listbox Prefix Search (`0x5EC6` – `0x5F15`)
```assembly
0x5ec6: cmp    ah, 49h              ; Page Up
0x5ecb: cmp    ah, 51h              ; Page Down
0x5ed0: cmp    ah, 48h              ; Up Arrow
0x5ed5: cmp    ah, 50h              ; Down Arrow
0x5eda: cmp    al, 20h              ; Ignore controls below space
0x5ede: cmp    al, 'a'
0x5ee2: sub    al, 20h              ; Convert input character to uppercase
...
0x5f00: mov    ah, byte ptr [si]    ; Read first letter of filename in list item
0x5f07: sub    ah, 20h              ; Convert to uppercase
0x5f0a: cmp    al, ah               ; Match first letter?
0x5f0c: je     0x5f44               ; Match found -> highlight & select this entry!
0x5f0e: inc    bx                   ; Check next file in listbox
```

### Consequence for Automation
* Pressing **`c`** immediately highlights `CTRY.FLM`.
* Pressing **`i`** immediately highlights `INTRO.FLM`.
* Typing multiple letters (`c`, `t`, `r`, `y`) does not type a word; each key press searches the list for a file beginning with that specific letter.
* Automation sequence to play a film:
  $$\text{Enter (open Load)} \longrightarrow \text{Initial letter of film (e.g. 'c')} \longrightarrow \text{Enter (play)}$$

---

## 6. Film File Format Pairing

Films stored in `VAULT\` require two companion files sharing the same base name:

1. **`*.FLM`** (e.g. `CTRY.FLM`):
   - Camera definitions, focal lengths, camera tracks, scene cutting, and event triggers.
2. **`*.ALL`** (e.g. `CTRY.ALL`):
   - 3D world geometry, stunt actors, model identifiers, flight paths, and motion trajectories.
   - Loaded in large blocks (typically $\approx 64\text{ KB}$ reads via `INT 21h AH=3Fh`).
   - If the `.ALL` file is absent, `PLAYONE.EXE` displays:
     ```text
     "That film does not have a matching .ALL file."
     ```

---

## 7. BIOS Keyboard Buffer Reference (MCP Keystroke Injection)

When controlling `PLAYONE.EXE` via the DOSBox-X MCP debugger server, keystrokes can be injected directly into the IBM PC BIOS Data Area (BDA) at segment `0040h`:

| Address | Size | Description |
|---|---|---|
| `0040:001Ah` | Word | Buffer Head pointer (points to next character to read, default `0x001E`) |
| `0040:001Ch` | Word | Buffer Tail pointer (points to next slot to write, default `0x001E`) |
| `0040:001Eh`–`0040:003Dh` | 32 Bytes | Circular buffer (holds up to 16 key words) |

### Key Scancode / ASCII Pairs
Each entry in the buffer is a 16-bit word (`[ASCII, Scancode]`):
* **`Enter`**: `0x0D, 0x1C` (`1C0Dh`)
* **`c`**: `0x63, 0x2E` (`2E63h`)
* **`i`**: `0x69, 0x17` (`1769h`)
* **`Space`**: `0x20, 0x39` (`3920h`)
* **`Esc`**: `0x1B, 0x01` (`011Bh`)

### Keystroke Injection Procedure via MCP
To inject `Enter` $\rightarrow$ `'c'` $\rightarrow$ `Enter`:
1. Write keystroke words to buffer starting at `0040:001E`:
   ```text
   debug_exec SM 0040:001E 0D 1C 63 2E 0D 1C
   ```
2. Update Head to `0x001E` and Tail to `0x0024` (3 keys $\times 2 = 6$ bytes):
   ```text
   debug_exec SM 0040:001A 1E 00 24 00
   ```
3. Resume execution:
   ```text
   debug_run run
   ```

---

## 8. Runtime Memory Footprint (Observed via MCP `DOS MCBS`)

```text
MCB Seg   Size (bytes)   PSP Seg   Filename / Purpose
------------------------------------------------------------------
07C9h            1,168     0814h   PLAYONE environment block
0813h          202,832     0814h   PLAYONE code, static data, stack
3999h          419,408     0814h   3D scene graph, actor trajectory buffer
CC00h           81,904     0814h   Upper memory allocation
```
Total dynamic scene allocation during playback is $\approx 419\text{ KB}$, leaving conventional memory within the 570 KB minimum specification.
