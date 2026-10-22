# `PLAYONE.EXE`: UI Navigation, File Selection & Input Mechanics

This document details the graphical interface navigation, file selection dialog architecture, keyboard input routing, film file format dependencies, and low-level BIOS input mechanics used to control `PLAYONE.EXE`.

---

## 1. File Selection Dialog Architecture

The film loading interface is a modal dialog. Rather than offering a freeform text input box, it presents a scrollable listbox populated from the `VAULT\` directory. `PLAYONE.EXE` runs the dialog as its **first screen at startup**: launching the executable with no command tail lands directly in `LOAD FILM`, with the listbox cursor on `[..]`.

### Dialog Invocation (`0x49C6` – `0x49D2`)

The dialog is set up and executed by passing pointers within the `DGROUP` data segment to the dialog runner routine at `0x0787`:

```assembly
0x49c6: mov    si, 0A58h            ; DS:0A58h -> "VAULT\*.*" (search pattern)
0x49c9: mov    di, 0AABh            ; DS:0AABh -> Destination buffer for selected path
0x49cc: mov    bx, 0A62h            ; DS:0A62h -> "LOAD FILM" (dialog header title)
0x49cf: call   0787h                ; Initialize & execute modal file picker
0x49d2: jb     0x49ed               ; If Carry Flag set, dialog was cancelled (Esc)
```

### Dialog Event Loop & Key Dispatch (`0x0C10` – `0x0C2C`)

The modal event loop polls the keyboard and evaluates incoming keystrokes:

* **`Enter` (`0x0D`)**:
  Branches to `0x0A1B` to confirm the selected entry. The routine copies the chosen filename into the destination buffer (`DS:0AABh`) and begins the playback pipeline.
* **`Esc` (`0x1B`)**:
  Branches to `0x0A14` to dismiss the dialog without taking action, returning to the main menu.
* **All Other Keystrokes**:
  Dispatched to the listbox navigation routine at `0x5EC6`.

When the dialog opens it discards keystrokes that were already queued in the BIOS ring buffer, so a harness must inject its keys only after the dialog has been painted (see §4).

---

## 2. Listbox Navigation & Prefix Searching

The file listbox implements single-character prefix jumping rather than multi-character autocomplete.

### Prefix Search Implementation (`0x5EC6` – `0x5F15`)

```assembly
0x5ec6: cmp    ah, 49h              ; Page Up
0x5ecb: cmp    ah, 51h              ; Page Down
0x5ed0: cmp    ah, 48h              ; Up Arrow
0x5ed5: cmp    ah, 50h              ; Down Arrow
0x5eda: cmp    al, 20h              ; Filter out non-printable ASCII (< 0x20)
0x5ede: cmp    al, 'a'
0x5ee2: sub    al, 20h              ; Convert lowercase input to uppercase
...
0x5f00: mov    ah, byte ptr [si]    ; Read first character of current list item
0x5f07: sub    ah, 20h              ; Convert list item character to uppercase
0x5f0a: cmp    al, ah               ; Compare input character with item initial
0x5f0c: je     0x5f44               ; Match found -> select and highlight entry
0x5f0e: inc    bx                   ; Advance to inspect next directory entry
```

### Key Navigation Behaviors

* **Single-Character Initial Jump**:
  Pressing an alphanumeric key scans the loaded directory entries and immediately jumps to the first entry whose filename starts with that letter (case-insensitive).
* **No Multi-Character Typing**:
  Each keystroke is evaluated independently as a new initial-character search. Typing `c`, `t`, `r`, `y` sequentially will first select a file starting with `C` (e.g., `CTRY.FLM`), then jump to a file starting with `T` if present, and so forth.
* **Directional Scrolling**:
  Up Arrow (`0x48`) and Down Arrow (`0x50`) move the selection cursor by one entry. Page Up (`0x49`) and Page Down (`0x51`) scroll the viewport by full pages.

---

## 3. Film Asset Pairing (`.FLM` & `.ALL`)

Playable films located in the `VAULT\` directory require two companion files sharing the same base filename:

| Extension | Component | Purpose & Format |
|---|---|---|
| **`*.FLM`** | Film Track Script | Camera definitions, track positions, camera cut events, focal lengths, and director cues. |
| **`*.ALL`** | 3D World Geometry | 3D actor meshes, flight trajectories, model coordinates, and motion paths. |

### Loading Mechanics

1. When a film is selected, `PLAYONE.EXE` reads the `.FLM` descriptor.
2. It then looks for the corresponding `.ALL` file on disk. The `.ALL` file is read in large blocks (typically $\approx 64\text{ KB}$ reads via DOS function `INT 21h, AH=3Fh`).
3. If the `.ALL` file is missing, playback is aborted and the player presents an alert:
   ```text
   "That film does not have a matching .ALL file."
   ```

---

## 4. Keyboard Architecture & Input Injection

For test harnesses, automated runners, or external control tools, keyboard input can be programmatically provided via the standard IBM PC BIOS Data Area (BDA).

### BIOS Keyboard Buffer Structure (`Segment 0040h`)

In real-mode x86 systems, the BIOS keyboard handler stores keystrokes in a circular ring buffer located in conventional RAM:

| Memory Address | Data Type | Description |
|---|---|---|
| `0040:001Ah` | 16-bit Word | **Buffer Head**: Byte offset of next keystroke to read (default: `0x001E`). |
| `0040:001Ch` | 16-bit Word | **Buffer Tail**: Byte offset of next free slot to write (default: `0x001E`). |
| `0040:001Eh` – `0040:003Dh` | 32 Bytes | **Ring Buffer**: Holds up to 16 keystroke words. |

### Keystroke Word Format

Each keystroke in the BIOS buffer is stored as a 16-bit word (`[Scan Code : ASCII Character]`):

| Key | ASCII Code (Low Byte) | BIOS Scan Code (High Byte) | 16-bit Word (Little-Endian) |
|---|---|---|---|
| **Enter** | `0x0D` | `0x1C` | `0x1C0D` (`0D 1C`) |
| **Esc** | `0x1B` | `0x01` | `0x011B` (`1B 01`) |
| **Space** | `0x20` | `0x39` | `0x3920` (`20 39`) |
| **'c' / 'C'** | `0x63` / `0x43` | `0x2E` | `0x2E63` / `0x2E43` |
| **'i' / 'I'** | `0x69` / `0x49` | `0x17` | `0x1769` / `0x1749` |
| **Up Arrow** | `0x00` | `0x48` | `0x4800` (`00 48`) |
| **Down Arrow** | `0x00` | `0x50` | `0x5000` (`00 50`) |

### Automated Navigation Sequences

Navigation is deterministic, and DOSBox-X's guest `INT 16h` does consume words written straight into the BIOS ring buffer. The ring buffer carries the keys the guest polls; the emulator must be **free-running** for that poll to happen, because a debugger that single-steps the CPU never lets the modal loop reach its `INT 16h` call.

Observed sequence for `CTRY.FLM` (listbox order `[..]`, `CTRY.ALL`, `CTRY.FLM`, …):

```
['c'] (prefix jump -> CTRY.ALL)  --->  [Down] (CTRY.FLM)  --->  [Enter] (Confirm & Play)
```

1. **Wait for the dialog**: the listbox must be on screen before the keys are queued, otherwise the dialog discards them on entry.
2. **Populate Buffer**: Write the key words into `0040:001E`.
3. **Advance Tail**: Set `0040:001C` to `0x001E + (2 * number_of_keys)`.
4. When the application runs its input polling loop (`INT 16h`), it drains the buffer in FIFO order.

Entering on `[..]` does not confirm or cancel: it re-lists the parent directory (`C:\`, showing `[VAULT]`, `driver1.bin`, …). Sequencing a `Down` before the confirming `Enter` is therefore required — an `Enter` alone lands on `[..]` and walks out of `VAULT`.

### Harness Constraints (`[Established]`)

* **Superseded recipe:** the former `SPEC.md` § 3.3 offered DOSBox-X `autotype -w 2 -p 0.5 enter c enter` as a selection protocol. It is contradicted by [`capture.md` § 2](capture.md#2-emulator-constraints) (`[Bounded Observation]`: with several keys queued at boot, only the earliest survives, and the dialog discards keys queued before it opens), so the harness uses BIOS Data Area injection instead.

* Keystroke injection into `0040:001E` works against the live emulator: the head pointer at `0040:001A` advances as the guest consumes the words.
* Injection fails while the controller steps the guest; the modal loop never reaches `INT 16h`. This is why the dialog appeared frozen in earlier harness runs.
* Patching the dialog call site (`0x49CF`) to force the confirm branch is not a viable shortcut: the patch requires reading and writing `DGROUP`, and any debugger command issued while `PLAYONE.EXE` is still unpacking kills the guest (see [`capture.md`](capture.md)). By the time such accesses are safe the four-instruction setup (`0x49C6`–`0x49D2`) has already executed, so the pre-written path buffer would never be read anyway.
