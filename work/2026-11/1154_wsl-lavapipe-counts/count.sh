#!/usr/bin/env bash
# Count one headless lavapipe render's instructions under Valgrind, or time it natively,
# with mise run ab's render flags (ab_timing.render_argv) and --report-memory for --report-timing.
# usage: count.sh <cachegrind|callgrind|native> <binary> <film> <all> <first..=last> <label>
# Appends one row to counts.csv beside this script; raw tool output goes to raw/<label>.*.
set -euo pipefail
tool=$1 bin=$2 film=$3 all=$4 span=$5 label=$6
here=$(cd "$(dirname "$0")" && pwd)
raw=$here/raw store=${ICOUNT_STORES:-build/scratch/icount}/$label
mkdir -p "$raw" "$(dirname "$store")"
rm -rf "$store"
icd=/usr/share/vulkan/icd.d/lvp_icd.json
export VK_DRIVER_FILES=$icd VK_ICD_FILENAMES=$icd LP_NUM_THREADS=1 MESA_SHADER_CACHE_DISABLE=true
sidata=${STUNT_DATA_ROOT:?}/corpus/siarchive/Developer/FreeFlight/SIDATA
args=(--headless "$film" --all "$all" --tick-range "$span" --sidata "$sidata" --width 320 --height 200
      --viewport-rows 185 --software-only --out-dir "$store" --report-memory)
case $tool in
  cachegrind) pre=(valgrind --tool=cachegrind --cache-sim=no --smc-check=all-non-file
                   "--cachegrind-out-file=$raw/$label.cg") ;;
  callgrind) pre=(valgrind --tool=callgrind --separate-threads=yes --smc-check=all-non-file
                  "--callgrind-out-file=$raw/$label.cl") ;;
  native) pre=() ;;
  *) echo "unknown tool $tool" >&2; exit 2 ;;
esac
log=$raw/$label.log
start=$(date +%s.%N)
setarch "$(uname -m)" -R "${pre[@]}" "$bin" "${args[@]}" >"$log" 2>&1
end=$(date +%s.%N)
wall=$(echo "$end - $start" | bc)
peak=$(grep -oE 'peak [0-9.]+ MiB' "$log" | tail -1 | grep -oE '[0-9.]+' || true)
ir=$(grep -oE 'I +refs: +[0-9,]+' "$log" | tr -dc '0-9' || true)
main='' other=''
if [[ $tool == callgrind ]]; then
  total=0
  for f in "$raw/$label.cl"-*; do
    n=$(grep -m1 '^summary:' "$f" | awk '{print $2}')
    total=$((total + n))
    if [[ $f == *-01 ]]; then main=$n; fi
  done
  ir=$total other=$((total - main))
fi
hash=$(cat "$store"/frames.zst "$store"/layers.zst "$store"/palettes.zst "$store"/shapes.zst | sha256sum | cut -c1-16)
csv=$here/counts.csv
[[ -f $csv ]] || echo "label,tool,binary_sha,span,ir_total,ir_main_thread,ir_other_threads,wall_s,peak_rss_mib,store_hash,load_spinners,machine" >"$csv"
bsha=$(sha256sum "$bin" | cut -c1-12)
machine="$(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs | tr ',' ' ') nproc=$(nproc)"
echo "$label,$tool,$bsha,$span,$ir,$main,$other,$wall,$peak,$hash,${ICOUNT_SPINNERS:-0},$machine" >>"$csv"
echo "$label $tool ir=$ir main=$main wall=$wall store=$hash"
