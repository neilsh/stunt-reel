---
title: "Find and repair torn frames in full-rate capture video"
started: 2026-11-27
issue: 1211
outcome: ""
---

# Find and repair torn frames in full-rate capture video

## Handoff

* **Step 2 (this branch):** `capture-video --stream` writes `stream.log` beside `capture.avi`.
  Each frame is either `p<frame>:<hex of A000 rows 0..191>` or `t<frame>` (held), between a header `h<token>:<layout>:1` and a trailer `e<end>`.
  The log also carries the emulator's own debug lines, so a reader keeps only payloads after `] debugmsg: `.
  Decisions of 2026-11-28 (Neil): the ZMBV video stays the parity reference, and composites use the stream; revisit once the stream is shown whole on every frame.
* **Step 3 should add a held-rate check.** The plan (§ (b), open question 8) asks that a film whose share of composed frames is low fail the capture. Step 2 does not enforce it, so decode should refuse or warn above a threshold. On `CTRY`, 85 of 1,907 frames are held.
* **The Windows log directory is unverified.** `debug_log_dir()` assumes `%LOCALAPPDATA%\dosbox-automation\logs`; check it on the first Legion run (#1201), or set `STUNT_DOSBOX_LOG_DIR`.
