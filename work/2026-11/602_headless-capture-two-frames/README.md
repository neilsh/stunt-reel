---
title: "Headless capture waits for each tick's readback before preparing the next"
started: 2026-11-15
issue: 602
outcome: "Adopted: two frames in flight left the stores byte-identical on the GPU over the seven reference films' captured ticks (20,621 ticks) and on lavapipe over LOCATION ticks 12-300, and took LOCATION ticks 12-300 to 76.3-78.2 s on lavapipe (from 88.7-89.9 s) and 12.4-12.6 s on the GPU (from 16.6-16.7 s); research/parity/lavapipe.md section 6 and open question 5 hold the finding."
---

# Headless capture waits for each tick's readback before preparing the next
