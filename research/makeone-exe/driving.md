# `MAKEONE.EXE`: Driving the Film Linker Under DOSBox-X

`MAKEONE.EXE` is the retail film linker: it turns a film's `.FLM` into the `.ALL` archive that `PLAYONE.EXE` plays ([`all.md`](../formats/all.md)). The retail manual describes it as a DOS program that opens a Load File requester, prepares the chosen film and returns to DOS. This note records what it does when the capture harness drives it, so a film without an `.ALL` can be given one. The harness itself is in [`capture.md`](../playone-exe/capture.md); the design is in [`docs/process/plans/make-all-2026-10-29.md`](../../docs/process/plans/make-all-2026-10-29.md) and [ADR 0023](../../docs/adr/0023-make-all-generates-archives-with-makeone.md).

Every observation below is `[Bounded Observation]`: one film (`BALLOON.FLM` from the full game), one spike on 2026-10-29, `dosbox-x-v2026.10.01`, the parity profile (`core = normal`, `output = surface`). The tier of a statement is repeated in its section's first line.

---

## 1. Run Sequence

`[Bounded Observation]`, five harness runs and one run with no controller.

```mermaid
flowchart LR
    A[autoexec: makeone.exe] --> B["'Caching data' box"]
    B --> C[LOAD FILM requester]
    C -- "b, Enter" --> D[film plays in the theatre]
    D --> E[writes BALLOON.ALL into VAULT]
    E --> F["DOS prompt, VGA mode M_TEXT"]
```

| Stage | What the framebuffer shows | Notes |
|---|---|---|
| Caching | A grey box, "Caching data / 14912K in extended memory" | Without the `RES\` tree it stayed here for at least 25 s. |
| Requester | `LOAD FILM`: Filename `*.*`, Dir `C:\VAULT`, a list starting `[..]`, OK and Cancel, a DRIVE row, a bottom bar with Exit and Load | The live DAC palette read all black on these pages; a colour check of them is meaningless. |
| Playback | The theatre with a `00:00.00` timecode; the film runs in real time | About 76 s after Enter for `BALLOON.FLM`. |
| Done | A bare `C:\>` in text mode; the page dump has one distinct index | `VGA MODE` reports `mode=M_TEXT`. |

## 2. Keys

`[Bounded Observation]`. The prefix jump fills the Filename field, so the keys are the film's first letter and Enter, with no Down (unlike `PLAYONE`'s list box, which needs a Down; [`playone.py`](../../python/stunt_reel/tac/playone.py)). With only the target film in `VAULT` the list shows `balloon.flm` and `balloon.tke`, and `b` selects `balloon.flm`. The spike pressed `b` about 10 s after the controller connected, 0.7 s before Enter; the harness's dialog settle has not been tried on these screens (Open questions).

## 3. Completion

`[Bounded Observation]`. The only sign that `MAKEONE` has finished is the video mode returning to text. A framebuffer dump cannot see it (`MEMDUMPBIN A000:0000` reads the graphics page, which does not change in text mode), so the harness reads `VGA MODE`; a reply is a line such as `VGA mode info: | mode=M_VGA vref=70.087Hz href=31468.750Hz chrclk=3146875.000Hz dotclk=25175000.000Hz`. No file appears before the end, and no `SPOOL.$$$` was left behind. Text mode alone is not a signal, because the guest sits at a prompt before the program starts; a graphics mode must have been seen first.

## 4. Minimal Mount

`[Bounded Observation]`. Tested on `BALLOON.FLM`:

| Needed | Not needed |
|---|---|
| `MAKEONE.EXE`, `DRIVER1.BIN`, `DRIVER2.BIN`, `DRIVER3.BIN`, `GAME.CFG`, `INSTALL.CFG`, `PFONT.BIN`, `VDATA.BIN` at the root | `BALLOON.TKE` (tested absent) |
| `RES\` (about 9.8 MB) | `SETS\`, `SS\`, `PILOTS\`, `GAME.VAR` (tested absent), `SPOOL.$$$` |
| `VAULT\BALLOON.FLM` | |

The engine files were not dropped one at a time. A mount that already held an `.ALL` (copied from an earlier run) made the output ambiguous, so each run uses a fresh copy.

## 5. Output

`[Bounded Observation]`. `BALLOON.ALL` appears in the mount's `VAULT\`, beside the `.FLM`: 46,702 bytes, md5 `1db59e1edd4d3debaca5e6188ead38df`, identical in all five harness runs and the run with no controller. It parses as [`all.ksy`](../formats/all.ksy): 62 chunk ids, a 378-byte header, the first offset 378, offsets increasing, the last offset equal to the file size. `PLAYONE` plays it: `capture-ref` captured 30 frames (film ticks about 10 to 345, 43 to 72 distinct indices each) in 12.6 s. Whether `PLAYONE` insists that the archive's stem equals the film's was not tested; every pair in the corpus matches.

## 6. Routes

`[Bounded Observation]`.

| Route | Result |
|---|---|
| Controller session (port 0, BDA keys, poll `VGA MODE`) | Worked, about 91 s wall including the 0.8 s connect. No crash, no illegal-interrupt storm. |
| No controller: the parity conf with `autotype -w 12 -p 1 b enter`, `makeone.exe`, `exit` | Worked, exit 0 after about 90 s. The 12 s wait is long enough that the key is not dropped, unlike `autotype` at `PLAYONE`'s boot ([`capture.md`](../playone-exe/capture.md) § 2). |

A stale `dosbox-x.exe` from an earlier killed run holds the control port; kill it first.

---

## Ruled out

- **Running without `RES\`.** The run never left the caching box in 25 s.
- **Needing the `.TKE`.** `BALLOON` converted without its take file.
- **`autotype` at boot as the primary route.** It works only with a long wait and cannot tell completion from a stall; it is the fallback if a film breaks the controller.

## Open questions

1. Does the harness's dialog settle (five identical dumps after three changes) fire on the caching box and requester? The spike used a fixed delay.
2. Run time scales with the film's length; only `BALLOON` was timed. What do the longer films take?
3. Films that need more than the shipped `RES\` (community films with custom sounds) and films whose `.FLM` references takes: untested.
4. Does a `.ALL` made under DOSBox-X carry the sound set-up of the machine that ran `MAKEONE` (`corpus/siarchive/Films/Playing_Films.txt`)? Frames are unaffected.
5. A film whose name starts with a digit or a character outside [`bda.py`](../../python/stunt_reel/tac/bda.py)'s scan-code table.
6. Does `PLAYONE` require the archive's stem to equal the film's?

_Found 2026-10-29; see the [parity log](../parity/log.md)._
