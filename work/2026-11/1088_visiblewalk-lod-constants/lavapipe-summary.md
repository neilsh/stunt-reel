### lavapipe-3680-3979

Adapter: llvmpipe (LLVM 21.1.7, 256 bits). Rounds: 8. Baseline: `old`.

| Variant | Loop ms by round | Median | Min | Range | Change | Faster | Wall median | Other load | Stores |
|---|---|---|---|---|---|---|---|---|---|
| old | 2506.9, 2570.9, 2552.7, 2517.6, 2597.4, 2661.4, 2576.6, 2547.3 | 2561.8 | 2506.9 | 2506.9..2661.4 | baseline | - | 4210.1 | 10% | same |
| new | 2492.9, 2528.3, 2659, 2519.1, 2467.9, 2579, 2488.5, 2466.6 | 2506 | 2466.6 | 2466.6..2659 | -2.2% | 6 of 8 | 4159.2 | 12% | same |
