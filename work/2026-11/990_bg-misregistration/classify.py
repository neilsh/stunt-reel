"""Classifies `register` output per tick as time, page, either or neither (#990 journal)."""
import sys, statistics as st
FLOOR, MARGIN, MINPX = 0.02, 0.02, 500
film=None; rows={}
for line in open(sys.argv[1], encoding="utf-8"):
    line=line.strip()
    if line.startswith("== "): film=line[3:]; rows[film]=[]; continue
    if not line or line.startswith("tick"): continue
    parts=line.replace("|"," ").split()
    if "no" in parts: rows[film].append((int(parts[0]),"none",0,None,None,None)); continue
    tick,px,base=int(parts[0]),int(parts[1]),float(parts[2])
    tk,tg=int(parts[3]),float(parts[7]); pdx,pdy,pg=int(parts[9]),int(parts[10]),float(parts[12])
    if px<MINPX: c="few"
    elif tg<FLOOR and pg<FLOOR: c="neither"
    elif tg>=pg+MARGIN: c="time"
    elif pg>=tg+MARGIN: c="page"
    else: c="either"
    rows[film].append((tick,c,px,(tk,tg),(pdx,pdy,pg),base))
for f,rs in rows.items():
    cnt={k:sum(1 for r in rs if r[1]==k) for k in ("time","page","either","neither","few","none")}
    ks=[r[3][0] for r in rs if r[1] in("time","either")]
    ps=[(r[4][0],r[4][1]) for r in rs if r[1] in("page","either")]
    tg=[r[3][1] for r in rs if r[1] not in("few","none")]; pg=[r[4][2] for r in rs if r[1] not in("few","none")]
    print(f, cnt, "k:",ks, "page:",ps, f"median gain time {st.median(tg):.3f} page {st.median(pg):.3f}")
    print("   ", " ".join(f"{r[0]}:{r[1]}" for r in rs))
from collections import Counter
dy=Counter(); dx=Counter(); n=0
for f,rs in rows.items():
    for r in rs:
        if r[1] in ("page","either"): dy[r[4][1]]+=1; dx[r[4][0]]+=1; n+=1
print("page/either ticks", n, "dy", sorted(dy.items()), "dx", sorted(dx.items()))
tot=Counter(r[1] for rs in rows.values() for r in rs); print("all", dict(tot))
