### lavapipe-3680-3979

Adapter: llvmpipe (LLVM 21.1.7, 256 bits). Rounds: 4. Baseline: `a`.

| Variant | Loop ms by round | Median | Min | Range | Change | Faster | Wall median | Stores |
|---|---|---|---|---|---|---|---|---|
| a | 4867.3, 4378.7, 3680.8, 4259.3 | 4319 | 3680.8 | 3680.8..4867.3 | baseline | - | 7108.1 | same |
| b | 3975.7, 3800, 3853.2, 4518 | 3914.5 | 3800 | 3800..4518 | -9.4% | 2 of 4 | 6515.6 | same |
