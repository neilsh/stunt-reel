#!/bin/bash
# Retry the whole-film lavapipe A/B until it completes or 8 attempts stop on the load check.
cd /e/t3/worktrees/stunt-reel/t3-b886fb36-9b45ab9521a02610 || exit 9
W=work/2026-11/1001_prop-shape-shader-search
for n in $(seq 21 50); do
  rm -f build/scratch/ab-lvp.log
  mise run ab -- --out $W --name lavapipe-ab --variant "base binary=build/base-1001.exe" --variant "shape-word binary=build/new-1001.exe" --span 12..=8262 --adapter lavapipe --rounds 4 --order alternate > build/scratch/ab-lvp.log 2>&1
  rc=$?
  echo "attempt $n rc=$rc" >> build/scratch/ab-attempts.log
  if [ $rc -eq 0 ]; then echo "DONE" >> build/scratch/ab-attempts.log; exit 0; fi
  mkdir -p build/scratch/aborted; sleep 60
  mv $W/lavapipe-ab.csv build/scratch/aborted/lavapipe-ab-$n.csv 2>/dev/null
  mv $W/lavapipe-ab-summary.md build/scratch/aborted/lavapipe-ab-$n-summary.md 2>/dev/null
  cp build/scratch/ab-lvp.log build/scratch/aborted/ab-lvp-$n.log
done
echo "GAVEUP" >> build/scratch/ab-attempts.log
