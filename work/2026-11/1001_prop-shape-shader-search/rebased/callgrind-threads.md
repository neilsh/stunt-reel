# Callgrind --separate-threads, base 5951161 vs shape acf55a0 (2 repeats each, stores matched)
Thread summaries (mean of 2), Ir:
B30 main  base 20,160,411,809  shape 20,773,231,013  +612,819,204 (+3.04%)  base repeat gap 654,810
B30 thr2  base  5,339,191,488  shape  4,805,152,115  -534,039,373 (-10.00%) gap 5,842,700
B30 thr3  base  2,605,161,552  shape  1,107,018,777  -1,498,142,775 (-57.51%) gap 209,116
B60 main  base 20,831,896,756  shape 21,456,361,768  +624,465,012 (+3.00%)  gap 6,127,276
B60 thr2  base  5,927,175,174  shape  5,395,137,979  -532,037,196 (-8.98%)  gap 74,079
B60 thr3  base  5,101,948,822  shape  2,160,574,004  -2,941,374,818 (-57.65%) gap 101,577
Total B30 -5.05%, B60 -8.94% (Callgrind totals ~0.2% below Cachegrind's whole-run counts).
