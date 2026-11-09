"""The stub-sound-samples command: refusals, the written archive and the printed hashes."""

from __future__ import annotations

import hashlib
import importlib.util
import struct
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.all_archive import stub_sound_samples

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location(
        "stub_sound_samples_script", SCRIPTS / "stub_sound_samples.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load()


def _archive(chunks: list[tuple[int, bytes]]) -> bytes:
    count = len(chunks)
    offsets = [6 * count + 6]
    for _, payload in chunks:
        offsets.append(offsets[-1] + len(payload))
    head = struct.pack(f"<H{count}H{count + 1}I", count, *(i for i, _ in chunks), *offsets)
    return head + b"".join(payload for _, payload in chunks)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "IN.ALL"
    path.write_bytes(_archive([(0x0001, b"shape"), (0xC302, b"sample" * 9)]))
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_run_writes_the_stub_and_prints_both_hashes(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "OUT.ALL"

    assert script.main([str(source), "-o", str(out)]) == 0

    assert out.read_bytes() == stub_sound_samples(source.read_bytes())
    assert capsys.readouterr().out.splitlines() == [
        f"in  {_sha(source)}  {source}",
        f"out {_sha(out)}  {out}",
    ]


def test_sound_ids_from_is_passed_through(source: Path, tmp_path: Path) -> None:
    own = tmp_path / "OWN.ALL"
    own.write_bytes(_archive([(0xC302, b"a"), (0xC319, b"b")]))
    out = tmp_path / "OUT.ALL"

    assert script.main([str(source), "-o", str(out), "--sound-ids-from", str(own)]) == 0

    expected = stub_sound_samples(source.read_bytes(), sound_ids_from=own.read_bytes())
    assert out.read_bytes() == expected


def test_a_missing_output_option_is_refused(source: Path) -> None:
    with pytest.raises(SystemExit) as exc:
        script.main([str(source)])
    assert exc.value.code == 2


def test_an_existing_output_is_refused_and_untouched(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "OUT.ALL"
    out.write_bytes(b"keep me")

    assert script.main([str(source), "-o", str(out)]) == 2

    assert out.read_bytes() == b"keep me"
    assert "exists" in capsys.readouterr().err


def test_an_output_that_is_the_input_is_refused(source: Path) -> None:
    before = source.read_bytes()
    same = source.parent / "." / source.name

    assert script.main([str(source), "-o", str(same)]) == 2

    assert source.read_bytes() == before


def test_an_output_in_a_missing_directory_is_refused(source: Path, tmp_path: Path) -> None:
    out = tmp_path / "nowhere" / "OUT.ALL"

    assert script.main([str(source), "-o", str(out)]) == 2

    assert not out.parent.exists()


def test_a_malformed_input_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "BAD.ALL"
    bad.write_bytes(b"\x00\x00")

    assert script.main([str(bad), "-o", str(tmp_path / "OUT.ALL")]) == 2

    assert "declares no chunks" in capsys.readouterr().err
    assert not (tmp_path / "OUT.ALL").exists()
