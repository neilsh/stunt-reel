"""Runs `parity_probe.py register` on every readout tick of the films named (#990 journal)."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, "python/scripts")
import parity_probe
from stunt_reel import references, dataroot
films = sys.argv[1].split(",")
extra = dict(time_reach=4, shift_reach=6, pad=8, with_props="--with-props" in sys.argv)
for film in films:
    ticks = json.load(open(f"research/parity/readouts/{film}.json", encoding="utf-8"))["ticks"]
    with references.open_reference(dataroot.data_root(), film) as ref:
        print(f"== {film}", flush=True)
        parity_probe.cmd_register(argparse.Namespace(ours=Path(f"build/parity/ours/{film}_current"), reference=ref, ticks=",".join(map(str, ticks)), **extra))
