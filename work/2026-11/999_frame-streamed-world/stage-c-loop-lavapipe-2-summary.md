### lavapipe-12-8262

Adapter: llvmpipe (LLVM 21.1.7, 256 bits). Rounds: 4. Baseline: `base`.

| Variant | Loop ms by round | Median | Min | Range | Change | Faster | Wall median | Other load | Stores |
|---|---|---|---|---|---|---|---|---|---|
| base | 24051.9, 24321.8, 24145.9, 24184.1 | 24165 | 24051.9 | 24051.9..24321.8 | baseline | - | 25819 | 10% | same |
| stream | 23679.7, 24167.8, 24227.1, 23969.2 | 24068.5 | 23679.7 | 23679.7..24227.1 | -0.4% | 3 of 4 | 25641.4 | 10% | same |
