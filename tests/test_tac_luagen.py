"""The Lua a dosbox-automation run executes, checked as text (no emulator starts here)."""

from __future__ import annotations

import re

import pytest

from stunt_reel.tac import luagen, playone

KEYS = ["KBD_c", "KBD_down", "KBD_enter"]


def _script(**kwargs: object) -> str:
    args: dict[str, object] = {
        "keys": KEYS,
        "first": 1300,
        "last": 1400,
        "layout": playone.UNPATCHED,
    }
    args.update(kwargs)
    return luagen.script(**args)  # type: ignore[arg-type]


def test_ds_is_derived_from_the_image_and_dgroup_paragraphs() -> None:
    assert playone.AUTOMATION_DS == 0x0F46
    assert "local DS = 0x0F46" in _script()


def test_boot_waits_to_the_start_frame_then_presses_keys_with_gaps_and_holds() -> None:
    text = _script()

    assert text.index("wait_until(1200)") < text.index('{"KBD_c", "KBD_down", "KBD_enter"}')
    assert "dosbox.wait_frames(20)" in text
    assert "dosbox.key(k, true); dosbox.wait_frames(5); dosbox.key(k, false)" in text


def test_the_cursor_is_parked_bottom_left_after_the_keys_without_spending_frames() -> None:
    """The cursor is drawn on the captured page; bottom-left puts it over the button bar."""
    for text in (_script(), luagen.keys_script(["KBD_c", "KBD_enter"])):
        move = text.index("dosbox.mouse_move(-2000, 2000)")
        assert move > text.index("dosbox.key(k, false)")
        assert "wait_frames" not in text[move : text.index("\n", move)]


def test_the_trace_reads_both_clocks_and_compares_the_page_as_strings() -> None:
    text = _script()

    assert "dosbox.mem_read_word(DS, 0x4896)" in text
    assert "dosbox.mem_read_word(DS, 0x22B8)" in text
    assert "dosbox.mem_read(0xA000, 0, 64000)" in text
    assert "(pg ~= prev)" in text
    assert 'out.trace = "x" .. table.concat(tr, ",")' in text
    assert "out.done = true" in text


def test_the_patched_layout_reads_its_own_segment_and_offsets() -> None:
    text = _script(layout=playone.PATCH3, dump_frames=[1350])

    assert "local DS = 0x0E66" in text
    assert "dosbox.mem_read_word(DS, 0x421C)" in text
    assert "dosbox.mem_read_word(DS, 0x1C3E)" in text
    assert "dosbox.mem_read(DS, 0x20EE, 768)" in text
    assert "0x4896" not in text


def test_extra_words_join_each_trace_entry() -> None:
    text = _script(words=[(0x0F46, 0x41C8)])

    assert "dosbox.mem_read_word(0x0F46, 0x41C8)" in text


def test_a_trace_pass_dumps_nothing() -> None:
    text = _script()

    assert 'out["p"' not in text
    assert "gsub" not in text


def test_a_dump_pass_hex_encodes_with_gsub_and_prefixes_every_string() -> None:
    text = _script(dump_frames=[1310, 1350], ranges=[luagen.MemRange(0x17C9, 0, 1024)])

    assert "local dumps = {1310, 1350}" in text
    assert 'out["p" .. f] = "x" .. pg:gsub(".", H)' in text
    assert 'out["c" .. f] = "x" .. dosbox.mem_read(DS, 0x2768, 768):gsub(".", H)' in text
    assert 'out["m" .. f .. "_1"] = "x" .. dosbox.mem_read(0x17C9, 0x0, 1024):gsub(".", H)' in text


def test_no_per_byte_loop_over_a_page() -> None:
    text = _script(dump_frames=[1310], ranges=[luagen.MemRange(0x17C9, 0, 4096)])

    assert not re.search(r"for\s+\w+\s*=\s*\d+\s*,\s*(64000|65535|63999)", text)
    assert ":byte(" not in text
    assert "string.byte" not in text
    assert ":sub(" not in text


def test_the_trace_cannot_start_before_the_keys_have_finished() -> None:
    boot_end = luagen.START_FRAME + len(KEYS) * (luagen.KEY_GAP + luagen.KEY_HOLD)

    with pytest.raises(ValueError, match="boot"):
        _script(first=boot_end - 1)
    assert f"for f = {boot_end}, 1400" in _script(first=boot_end)


@pytest.mark.parametrize("bad", ["KBD_c; os.exit()", "c", 'KBD_"x"', ""])
def test_key_names_are_validated_before_they_reach_lua(bad: str) -> None:
    with pytest.raises(ValueError, match="key name"):
        _script(keys=[bad])


def test_dump_frames_must_ascend_inside_the_window_and_stay_under_the_output_cap() -> None:
    with pytest.raises(ValueError, match="ascend"):
        _script(dump_frames=[1350, 1310])
    with pytest.raises(ValueError, match="window"):
        _script(dump_frames=[1500])
    with pytest.raises(ValueError, match=str(luagen.MAX_DUMPS)):
        _script(
            first=1300, last=1300 + 200, dump_frames=list(range(1300, 1300 + luagen.MAX_DUMPS + 1))
        )


def test_a_range_longer_than_one_read_is_refused() -> None:
    with pytest.raises(ValueError, match="65535"):
        luagen.MemRange(0x17C9, 0, 65536)


def test_film_selection_names_match_the_dialog_sequence() -> None:
    assert playone.film_selection_names("CTRY") == ["KBD_c", "KBD_down", "KBD_enter"]
    assert playone.film_selection_names("INTRO")[0] == "KBD_i"
    assert playone.film_selection_names("")[0] == "KBD_c"


def test_end_hold_stops_the_trace_when_the_film_clock_stops_advancing() -> None:
    text = _script(end_hold=3)

    assert "if t == lt then hold = hold + 1 else hold = 0; lt = t end" in text
    assert "if t > 0 and hold >= 3 then break end" in text
    assert "break" not in _script()


def test_end_hold_must_be_positive() -> None:
    with pytest.raises(ValueError, match="end_hold"):
        _script(end_hold=0)


def test_keys_script_boots_presses_the_keys_and_ends_without_a_trace() -> None:
    text = luagen.keys_script(["KBD_m", "KBD_enter"])

    assert text.index("wait_until(1200)") < text.index('{"KBD_m", "KBD_enter"}')
    assert "dosbox.mem_read" not in text
    assert text.endswith("out.done = true\n")
    with pytest.raises(ValueError, match="key name"):
        luagen.keys_script(["bad"])
