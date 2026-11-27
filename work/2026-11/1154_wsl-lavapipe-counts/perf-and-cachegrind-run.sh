#!/bin/bash
# Step 2 (perf stat, native) then step 3 (Cachegrind B30 x3), on WSL, build of 70b0f76.
BIN=/root/stunt-reel/target/release/stuntreel
DR=/root/stunt-reel.data
FILM=$DR/builds/patch3/VAULT/LOCATION.FLM
ALL=$DR/captures/vault-location/archives/LOCATION.ALL
SIDATA=$DR/corpus/siarchive/Developer/FreeFlight/SIDATA
ICD=/usr/share/vulkan/icd.d/lvp_icd.json
export BIN FILM ALL SIDATA
PERF=/usr/lib/linux-tools-6.8.0-151/perf
mkdir -p /root/icount/perf && cd /root/icount
export VK_DRIVER_FILES=$ICD VK_ICD_FILENAMES=$ICD MESA_SHADER_CACHE_DISABLE=true STUNT_DATA_ROOT=$DR
render() { # span store
  setarch "$(uname -m)" -R "$BIN" --headless "$FILM" --all "$ALL" --tick-range "$1" --sidata "$SIDATA" \
    --width 320 --height 200 --viewport-rows 185 --software-only --out-dir "$2" --report-memory
}
echo "== perf stat native"
for cfg in default t1; do
  for span in B30:3680..=3709 B60:3680..=3739; do
    name=${span%%:*}; rng=${span#*:}
    for r in 1 2 3; do
      out=/root/icount/perf/$cfg-$name-r$r.txt
      if [[ $cfg == t1 ]]; then export LP_NUM_THREADS=1; else unset LP_NUM_THREADS; fi
      rm -rf /root/icount/perf/store
      $PERF stat -x, -e instructions:u -o "$out" -- bash -c "$(declare -f render); render $rng /root/icount/perf/store" > /root/icount/perf/$cfg-$name-r$r.log 2>&1
      echo "$cfg $name r$r: $(grep instructions "$out")"
    done
  done
done
unset LP_NUM_THREADS
echo "== cachegrind B30"
cd /root/icount
for r in 1 2 3; do
  ./count.sh cachegrind $BIN "$FILM" "$ALL" 3680..=3709 wsl-b30-r$r
done
echo "CG DONE"
