"""``expected_file``: the generated per-class expected-scores file's format."""

from __future__ import annotations

import tomllib
from pathlib import Path

from stunt_reel import expected_file
from stunt_reel.parity_artifacts import LOSS_CLASSES
from stunt_reel.references import Expected

CRATES = "a" * 40
SHA = "b" * 64
LOSS = {name: f"0.00{i}0000" for i, name in enumerate(LOSS_CLASSES)}


def _values(ssim: str = "0.9188707") -> dict[str, str]:
    return {
        "ssim": ssim,
        "iou": "0.9910143",
        "crates": f'"{CRATES}"',
        "sha256": f'"{SHA}"',
        "adapter": '"NVIDIA GeForce"',
    }


def test_render_writes_tables_in_film_and_key_order() -> None:
    text = expected_file.render([("land", _values(), LOSS), ("ctry", _values("0.5000000"), {})])
    body = text.removeprefix(expected_file.HEADER)
    assert body.index("[land]") < body.index("[land.loss]") < body.index("[ctry]")
    assert "[ctry.loss]" not in body
    loss_lines = "".join(f"{name} = {LOSS[name]}\n" for name in LOSS_CLASSES)
    assert body.startswith(
        "\n[land]\n"
        "ssim = 0.9188707\n"
        "iou = 0.9910143\n"
        f'crates = "{CRATES}"\n'
        f'sha256 = "{SHA}"\n'
        'adapter = "NVIDIA GeForce"\n'
        "\n[land.loss]\n" + loss_lines + "\n[ctry]\n"
    )
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_render_round_trips_through_tomllib() -> None:
    parsed = tomllib.loads(expected_file.render([("land", _values(), LOSS)]))
    assert parsed["land"]["ssim"] == 0.9188707
    assert parsed["land"]["crates"] == CRATES
    assert parsed["land"]["loss"] == {name: float(LOSS[name]) for name in LOSS_CLASSES}


def test_format_values_matches_the_written_form() -> None:
    expected = Expected(0.9188707, 0.9910143, "a" * 40, "b" * 64, "NVIDIA", all_sha256="c" * 64)
    values, loss = expected_file.format_values(expected)
    assert values["ssim"] == "0.9188707"
    assert values["crates"] == '"' + "a" * 40 + '"'
    assert values["all_sha256"] == '"' + "c" * 64 + '"'
    assert loss == {}
    bare, _ = expected_file.format_values(Expected(0.5, 0.5, "a" * 40, "b" * 64, "NVIDIA"))
    assert "all_sha256" not in bare


def test_path_is_beside_the_references_file() -> None:
    assert expected_file.path(Path("x/research/parity/references.toml"), "gpu") == Path(
        "x/research/parity/expected/gpu.toml"
    )
