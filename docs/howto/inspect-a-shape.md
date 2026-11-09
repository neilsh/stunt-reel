# Inspect a shape's geometry

## Trace its `.SOD` walk

Print the instructions one shape's `.SOD` walk executes, one line each (offset, mnemonic, operand words, `->` and the target of a taken branch), instead of adding traces to `vm.rs`:

```powershell
cargo run -p stunt-cli -- sod-trace --archive "<data root>/corpus/stisldem/VAULT/CTRY.ALL" --shape 0x7F37
```

## Draw its views

Draw orthographic top, side and front views of an archive's shapes, one `<ID>.png` each, with `manifest.json` recording each shape's geometry hash. `SUPERSET.ALL` is built by `mise run superset-all`, which needs the full game in the corpus:

```powershell
cargo run --release -p stunt-cli -- shape-views --archive target/linked/superset/SUPERSET.ALL --shapes 7F02..=7F38 --out build/scratch/views
```

## Find the shapes a switch changes

`mise run shape-diff -- --var DBG_X=0,1 [--shapes IDS|FILE] [--archive X.ALL] [--views top,side,front] [--tile PX] [--no-build]` runs `stuntreel shape-views` once per value of a `DBG_*` switch and lists the shapes whose geometry hash or decode failure changes; `build/scratch/shape-diff/sheet.png` draws only those shapes, one column per value. The archive defaults to `target/linked/superset/SUPERSET.ALL` (`mise run superset-all`).
