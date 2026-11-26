### lavapipe-3680-3979

Adapter: llvmpipe (LLVM 21.1.7, 256 bits). Rounds: 4. Baseline: `a`.

| Variant | Loop ms by round | Median | Min | Range | Change | Faster | Wall median | Other load | Stores |
|---|---|---|---|---|---|---|---|---|---|
| a | 2302.9, 2354.6, 2431.1, 2405.9 | 2380.2 | 2302.9 | 2302.9..2431.1 | baseline | - | 3896.4 | 11% | same |
| b | 2356.5, 2445.3, 2311.6, 2352.9 | 2354.7 | 2311.6 | 2311.6..2445.3 | -1.1% | 2 of 4 | 3869.9 | 11% | same |
