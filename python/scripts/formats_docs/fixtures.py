"""Synthetic Fixture Consistency: catalog headers, offsets and opcodes match the fixtures."""

from __future__ import annotations

import importlib
import io
import json
import math
import struct
from pathlib import Path
from typing import Any

from formats_docs.catalog import VerificationResult
from stunt_reel import flm_walk
from stunt_reel.kaitai import (
    REQUIRED_KSC_VERSION,
    compile_schemas,
    compiler_version,
    load_generated_module,
    version_matches,
)
from stunt_reel.scratch import scratch_dir


def _validate_res_with_kaitai(repo_root: Path, res_bytes: bytes) -> tuple[list[str], list[str]]:
    """Validate the synthetic fixture with the parser generated from research/formats/res.ksy."""
    errors: list[str] = []
    details: list[str] = []

    version = compiler_version()
    if version is None:
        details.append(
            "Kaitai Struct Compiler not found on PATH; res.ksy fixture cross-check skipped"
        )
        return errors, details
    if not version_matches(version):
        errors.append(
            "Kaitai Struct Compiler version mismatch: expected "
            f"{REQUIRED_KSC_VERSION}, got '{version}'"
        )
        return errors, details

    schema_path = repo_root / "research" / "formats" / "res.ksy"
    try:
        with scratch_dir(prefix="stunt-kaitai-") as tmp:
            compile_schemas([schema_path], tmp)
            res_module = load_generated_module(Path(tmp) / "res.py", "stunt_kaitai_res")
            res_cls: Any = res_module.Res

            kaitaistruct_mod: Any = importlib.import_module("kaitaistruct")
            kaitai_stream_cls: Any = kaitaistruct_mod.KaitaiStream

            parsed = res_cls(kaitai_stream_cls(io.BytesIO(res_bytes)))

            if parsed.magic != b"RS":
                errors.append(
                    f"Kaitai res.ksy magic mismatch: expected b'RS', got {bytes(parsed.magic)!r}"
                )
            if parsed.res_index != 1:
                errors.append(
                    f"Kaitai res.ksy res_index mismatch: expected 1, got {parsed.res_index}"
                )
            if parsed.item_count != 3:
                errors.append(
                    f"Kaitai res.ksy item_count mismatch: expected 3, got {parsed.item_count}"
                )
            if parsed.ofs_data != 20:
                errors.append(f"Kaitai res.ksy ofs[0] mismatch: expected 20, got {parsed.ofs_data}")
            if list(parsed.offsets) != [20, 40, 56, 72]:
                errors.append(
                    "Kaitai res.ksy offset table mismatch: expected [20, 40, 56, 72], "
                    f"got {list(parsed.offsets)}"
                )
            segments = [bytes(segment.body) for segment in parsed.segments]
            if [len(segment) for segment in segments] != [20, 16, 16]:
                errors.append(
                    "Kaitai res.ksy segment lengths mismatch: expected [20, 16, 16], "
                    f"got {[len(segment) for segment in segments]}"
                )
            if not segments or segments[0] != b"PLANE.SOD\x00PROP.SOD\x00\x00":
                errors.append(
                    "Kaitai res.ksy name-table segment mismatch: expected "
                    f"b'PLANE.SOD\\x00PROP.SOD\\x00\\x00', got {segments[0] if segments else None!r}"
                )
            if segments[1:3] != [res_bytes[40:56], res_bytes[56:72]]:
                errors.append("Kaitai res.ksy payload segments do not match fixture bytes 40..72")

            bad_magic = bytearray(res_bytes)
            bad_magic[0] = 0x58
            bad_align = bytearray(res_bytes)
            struct.pack_into("<I", bad_align, 4, 21)
            for label, mutated in (("bad magic", bad_magic), ("unaligned ofs[0]", bad_align)):
                try:
                    res_cls(kaitai_stream_cls(io.BytesIO(bytes(mutated))))
                except Exception:  # noqa: S112
                    continue
                errors.append(f"Kaitai res.ksy accepted malformed fixture copy: {label}")

            details.append(
                f"synthetic_minimal.res parsed by Kaitai res.ksy "
                f"({len(res_bytes)} bytes, offsets {list(parsed.offsets)})"
            )
    except Exception as exc:
        errors.append(f"Kaitai RES fixture validation failed: {exc}")
    return errors, details


def _validate_flm_with_kaitai(repo_root: Path, flm_bytes: bytes) -> tuple[list[str], list[str]]:
    """Parse every fixture slice with the walker's masks and the flm_slice.ksy parser."""
    errors: list[str] = []
    details: list[str] = []

    version = compiler_version()
    if version is None:
        details.append(
            "Kaitai Struct Compiler not found on PATH; flm_slice.ksy fixture cross-check skipped"
        )
        return errors, details
    if not version_matches(version):
        errors.append(
            "Kaitai Struct Compiler version mismatch: expected "
            f"{REQUIRED_KSC_VERSION}, got '{version}'"
        )
        return errors, details

    try:
        views = flm_walk.walk_film(flm_bytes)
    except flm_walk.FlmWalkError as exc:
        errors.append(f"flm_walk rejected synthetic_minimal.flm: {exc}")
        return errors, details
    if [view.start for view in views] != [4, 13] or [view.end for view in views] != [13, 17]:
        errors.append(
            "flm_walk slice bounds mismatch: expected [4, 13]..[13, 17], "
            f"got {[(view.start, view.end) for view in views]}"
        )
        return errors, details

    schema_path = repo_root / "research" / "formats" / "flm_slice.ksy"
    try:
        with scratch_dir(prefix="stunt-kaitai-") as tmp:
            compile_schemas([schema_path], tmp)
            module = load_generated_module(Path(tmp) / "flm_slice.py", "stunt_kaitai_flm_slice")
            flm_cls: Any = module.FlmSlice
            kaitai_stream_cls: Any = importlib.import_module("kaitaistruct").KaitaiStream

            parsed_slices: list[Any] = []
            for view in views:
                chunk = flm_bytes[view.start : view.end]
                parsed = flm_cls(
                    view.moves, view.rotates, view.animates, kaitai_stream_cls(io.BytesIO(chunk))
                )
                parsed_slices.append(parsed)
                consumed = int(parsed._io.pos())
                if consumed != len(chunk):
                    errors.append(
                        f"flm_slice.ksy parsed {consumed} of {len(chunk)} bytes "
                        f"for slice {view.index}"
                    )
            first = parsed_slices[0]
            if int(first.first.tag) != 0x80 or int(first.first.body.body.value) != 0x9890:
                errors.append(
                    "flm_slice.ksy slice 0 var_set mismatch: expected tag 0x80 value 0x9890, "
                    f"got tag {int(first.first.tag)} value {int(first.first.body.body.value)}"
                )
            details.append(
                f"synthetic_minimal.flm parsed by Kaitai flm_slice.ksy "
                f"({len(flm_bytes)} bytes, {len(views)} slices)"
            )
    except Exception as exc:
        errors.append(f"Kaitai FLM fixture validation failed: {exc}")
    return errors, details


def verify_synthetic_fixtures_consistency(repo_root: Path) -> VerificationResult:
    """Validate documented offsets, signatures, and opcodes against synthetic fixtures in tests/fixtures/."""
    errors: list[str] = []
    details: list[str] = []
    fixtures_dir = repo_root / "tests" / "fixtures"

    # 1. synthetic_minimal.res
    res_path = fixtures_dir / "synthetic_minimal.res"
    if not res_path.exists():
        errors.append(f"Synthetic fixture missing: {res_path}")
    else:
        res_bytes = res_path.read_bytes()
        if len(res_bytes) != 72:
            errors.append(
                f"synthetic_minimal.res size mismatch: expected 72 bytes, got {len(res_bytes)}"
            )

        # Verify documentation in research/formats/res.md
        res_doc = (repo_root / "research" / "formats" / "res.md").read_text(encoding="utf-8")
        if 'b"RS"' not in res_doc and "0x52, 0x53" not in res_doc:
            errors.append("res.md does not document RS magic signature (0x52, 0x53)")
        if "synthetic_minimal.res" not in res_doc:
            errors.append("res.md does not cite tests/fixtures/synthetic_minimal.res in section 1")

        res_errors, res_details = _validate_res_with_kaitai(repo_root, res_bytes)
        errors.extend(res_errors)
        details.extend(res_details)

    # 2. synthetic_minimal.flm
    flm_path = fixtures_dir / "synthetic_minimal.flm"
    if not flm_path.exists():
        errors.append(f"Synthetic fixture missing: {flm_path}")
    else:
        flm_bytes = flm_path.read_bytes()
        if len(flm_bytes) != 17:
            errors.append(
                f"synthetic_minimal.flm size mismatch: expected 17 bytes, got {len(flm_bytes)}"
            )
        if flm_bytes[:4] != b"FILM":
            errors.append(
                f"synthetic_minimal.flm magic signature mismatch: expected b'FILM', got {flm_bytes[:4]!r}"
            )

        # Slice 0 header at 0x0004: prev_slice_len 0x0000, tick_duration 0x01.
        if struct.unpack_from("<H", flm_bytes, 4)[0] != 0 or flm_bytes[6] != 1:
            errors.append(
                "synthetic_minimal.flm slice 0 header mismatch: expected prev_slice_len 0, "
                f"tick_duration 1, got prev_slice_len "
                f"{struct.unpack_from('<H', flm_bytes, 4)[0]}, tick_duration {flm_bytes[6]}"
            )

        slice_0_bytecode = list(flm_bytes[7:13])
        if slice_0_bytecode != [0x80, 0x90, 0x98, 0x90, 0x98, 0xFF]:
            errors.append(f"synthetic_minimal.flm slice 0 bytecode mismatch: {slice_0_bytecode}")

        # Slice 1 header at 0x000D: 9-byte back-pointer to slice 0.
        if struct.unpack_from("<H", flm_bytes, 13)[0] != 9 or flm_bytes[15] != 1:
            errors.append(
                "synthetic_minimal.flm slice 1 header mismatch: expected prev_slice_len 9, "
                f"tick_duration 1, got prev_slice_len "
                f"{struct.unpack_from('<H', flm_bytes, 13)[0]}, tick_duration {flm_bytes[15]}"
            )
        if flm_bytes[16] != 0xFF:
            errors.append(
                f"synthetic_minimal.flm slice 1 terminator mismatch: expected 0xFF, got {flm_bytes[16]:#04x}"
            )

        # Verify documentation in research/formats/flm.md
        flm_doc = (repo_root / "research" / "formats" / "flm.md").read_text(encoding="utf-8")
        if 'b"FILM"' not in flm_doc and "FILM" not in flm_doc:
            errors.append("flm.md does not document FILM magic signature")
        if "synthetic_minimal.flm" not in flm_doc:
            errors.append("flm.md does not cite tests/fixtures/synthetic_minimal.flm in section 1")

        details.append(
            f"synthetic_minimal.flm validated against flm.md ({len(flm_bytes)} bytes, 2 slices)"
        )

        flm_errors, flm_details = _validate_flm_with_kaitai(repo_root, flm_bytes)
        errors.extend(flm_errors)
        details.extend(flm_details)

    # 3. synthetic_minimal.sod
    sod_path = fixtures_dir / "synthetic_minimal.sod"
    if not sod_path.exists():
        errors.append(f"Synthetic fixture missing: {sod_path}")
    else:
        sod_bytes = sod_path.read_bytes()
        if len(sod_bytes) != 76:
            errors.append(
                f"synthetic_minimal.sod size mismatch: expected 76 bytes, got {len(sod_bytes)}"
            )

        op_id = struct.unpack_from("<H", sod_bytes, 0)[0]
        if op_id != 0x000C:
            errors.append(
                f"synthetic_minimal.sod OP_ID mismatch: expected 0x000C, got 0x{op_id:04X}"
            )

        bounding_size = struct.unpack_from("<H", sod_bytes, 2)[0]
        scale = struct.unpack_from("<H", sod_bytes, 6)[0]
        if bounding_size != 100 or scale != 1:
            errors.append(
                f"synthetic_minimal.sod header fields mismatch: bounding_size={bounding_size}, scale={scale}"
            )

        # Check OP_VECTORS (0x0075) opcode at offset 10
        op_vectors = struct.unpack_from("<H", sod_bytes, 10)[0]
        if op_vectors != 0x0075:
            errors.append(f"synthetic_minimal.sod OP_VECTORS opcode mismatch: 0x{op_vectors:04X}")

        # Verify documentation in research/formats/sod.md
        sod_doc = (repo_root / "research" / "formats" / "sod.md").read_text(encoding="utf-8")
        if "0x000C" not in sod_doc and "0x000c" not in sod_doc:
            errors.append("sod.md does not document OP_ID 0x000C header")
        if "synthetic_minimal.sod" not in sod_doc:
            errors.append("sod.md does not cite tests/fixtures/synthetic_minimal.sod in section 1")

        details.append(
            f"synthetic_minimal.sod validated against sod.md ({len(sod_bytes)} bytes, OP_ID 0x000C)"
        )

    # 4. oracle_intro_trajectory.json
    traj_path = fixtures_dir / "oracle_intro_trajectory.json"
    if not traj_path.exists():
        errors.append(f"Synthetic fixture missing: {traj_path}")
    else:
        try:
            traj_data = json.loads(traj_path.read_text(encoding="utf-8"))
            if not isinstance(traj_data, list) or len(traj_data) != 2:
                errors.append(
                    f"oracle_intro_trajectory.json format error: expected 2 records list, got {len(traj_data)}"
                )
            else:
                for idx, record in enumerate(traj_data):
                    for req_key in ("tick", "camera", "actors", "audio_cues"):
                        if req_key not in record:
                            errors.append(
                                f"oracle_intro_trajectory.json record {idx} missing key '{req_key}'"
                            )

                    cam = record.get("camera", {})
                    for cam_key in ("eye", "target", "fov_degrees", "roll_radians"):
                        if cam_key not in cam:
                            errors.append(
                                f"oracle_intro_trajectory.json record {idx} camera missing '{cam_key}'"
                            )

                    actors = record.get("actors", [])
                    for actor_idx, actor in enumerate(actors):
                        q = actor.get("rotation_quat", [])
                        if len(q) == 4:
                            norm = math.sqrt(sum(c * c for c in q))
                            if abs(norm - 1.0) > 1e-4:
                                errors.append(
                                    f"Quaternion not normalized in tick {record.get('tick')} actor {actor_idx}: {norm}"
                                )

                details.append(
                    f"oracle_intro_trajectory.json validated ({len(traj_data)} discrete simulation ticks)"
                )
        except json.JSONDecodeError as exc:
            errors.append(f"Failed to parse oracle_intro_trajectory.json as JSON: {exc}")

    # 5. README.md in tests/fixtures
    readme_path = fixtures_dir / "README.md"
    if not readme_path.exists():
        errors.append("tests/fixtures/README.md is missing")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        for fixture_name in (
            "synthetic_minimal.res",
            "synthetic_minimal.flm",
            "synthetic_minimal.sod",
        ):
            if fixture_name not in readme_text:
                errors.append(
                    f"tests/fixtures/README.md does not document fixture '{fixture_name}'"
                )
        details.append("tests/fixtures/README.md documentation verified")

    return VerificationResult(
        category="Synthetic Fixture Consistency",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )
