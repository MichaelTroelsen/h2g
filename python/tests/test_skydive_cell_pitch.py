"""The skydive falls from the pitch a byte past the table really sounds.

Last_V8 pattern `$12` is instrument `$0D` (skydive) on the byte `$7C`, which
the player reads from two scratch variables: the original starts the note at
`$6001` (`patterns.PLAYER_CELL_PITCH`) and the nearest entry of its table, 78,
is `$6278` in Goattracker's, two high bytes and a bit above it. The fall is
measured from Goattracker's note, so it read two high bytes up for its whole
length (29 stores). The window's program is the group's program entered two
stores later (`goatwriter.skydive.pinned_key` inside `skydive_plan`): store k
of the fall `n` high bytes deeper is the same program's store `k + n`, so it
costs a lead and a wavetable jump, not 95 rows of its own.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g import patterns                                     # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

import test_skydive_multispeed as M                          # noqa: E402

RIPS = ["Last_V8", "Last_V8_C128_version"]


def test_a_pinned_start_may_sit_far_from_its_anchor():
    far = S.SkydiveVibrato(counter=3, base=0x6001, step=375, anchor=0x6278,
                           pinned=True)
    assert S.anchor_bias(far) == 0x277
    # Declined as a tuning difference unless it is a measured pitch, and
    # where the pinned layout is off.
    assert S.anchor_bias(far, pinned=False) == 0
    assert S.anchor_bias(S.SkydiveVibrato(3, 0x6001, 375, 0x6278)) == 0


def test_a_pinned_key_goes_after_the_programs_it_is_the_tail_of():
    main = ((2, 30, True), None, 14)
    tail = ((2, 28, True), None, 526, True)
    assert S._program_order(main) < S._program_order(tail)
    assert sorted([tail, main], key=S._program_order) == [main, tail]


@needs_corpus
@pytest.mark.parametrize("name", RIPS)
def test_only_the_cell_note_is_pinned(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, log=lambda m: None)
    assert patterns.player_cell_pitch(sid, det, 78) == 0x6001
    assert patterns.player_cell_pitch(sid, det, 77) is None
    assert patterns.player_cell_pitch(sid, det, 79) is None
    from dataclasses import replace
    assert patterns.player_cell_pitch(replace(sid, name="Commando"), det,
                                      78) is None
    pinned = S.window_vibrato(sid, 1, 78, 6403, det)
    assert (pinned.base, pinned.anchor, pinned.pinned) == (0x6001, 0x6278,
                                                          True)
    # Without the file it is the entry's own start; the table's.
    plain = S.window_vibrato(sid, 1, 78, 6403)
    assert not plain.pinned and plain.base == 0x6270


@needs_corpus
@pytest.mark.parametrize("name", RIPS)
def test_the_reverse_lookup_by_entry_meets_one_window(name, monkeypatch):
    """`player_cell_pitch` finds the cell by the entry its byte was rounded
    to, so it is right only while no genuine byte lands on that entry of a
    skydive record: the plan asks for exactly one window on entry 78."""
    seen = []
    real = S.window_vibrato

    def spy(sid, shift, note, counter, det=None):
        got = real(sid, shift, note, counter, det)
        seen.append((note, got is not None and got.pinned))
        return got

    monkeypatch.setattr(S, "window_vibrato", spy)
    M._converted(name)
    on_78 = [pinned for note, pinned in seen if note == 78]
    assert on_78 == [True], seen
    assert not any(pinned for note, pinned in seen if note != 78), seen


@needs_corpus
@pytest.mark.parametrize("name", RIPS)
def test_the_window_is_a_second_program_laid_as_the_first_ones_tail(name):
    sng, lines = M._converted(name)
    (msg,) = M._sky(lines)
    assert "not emitted" not in msg, msg
    # 30 stores on the group's program; the pinned window is two high bytes
    # deeper, so its program is two stores shorter.
    assert "2 program(s)" in msg, msg
    assert "(1, 28, True)" in msg or "(2, 28, True)" in msg, msg
    import songview
    wt = songview.parse_sng(sng).tables["WTBL"]
    assert len(wt) <= S.GT_MAX_TABLELEN


@needs_corpus
def test_without_a_tail_to_share_the_window_is_laid_as_any_other(monkeypatch):
    """Where no layout takes the pinned program the plan falls back to the
    unpinned one: the skydive is emitted as before this window was pinned
    (one program), never dropped."""
    monkeypatch.setattr(S, "share_program_tail",
                        lambda prog, rows, min_saving=2: (prog, None))
    sng, lines = M._converted("Last_V8")
    (msg,) = M._sky(lines)
    assert "not emitted" not in msg, msg
    assert "1 program(s)" in msg, msg


@needs_corpus
@M.needs_siddump
@M.needs_gt2reloc
def test_last_v8_cell_note_falls_from_the_cells_high_byte(tmp_path):
    """Packed at -S2 and traced at -m2, 150 s: every store of the window at
    frames 6400-6470 (pattern $12, the fall from $60) names the original's
    high byte, but the last two. Before: 29 stores, each two high bytes up."""
    seconds = 150
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Last_V8.sid", seconds, 0)
    stores = {f: hi for f, hi in M._store_frames(orig, n)[0].items()
              if 6400 <= f <= 6470}
    assert len(stores) >= 25, len(stores)
    sng, _ = M._converted("Last_V8")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=2)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, seconds + 1, 0, calls=2)
    lag = fidelity.startup_lag(orig, ours)[0]
    fq = fidelity.register_timeline(ours[0].freq_events, n + lag)
    # The program is the group's, entered two stores in, so it ends two
    # stores short of the original's 29: the last two (frames 6461, 6463)
    # are the cost of laying it as a tail, and stay misses.
    short = {f for f in stores if f > 6459}
    assert short == {6461, 6463}, short
    assert sum(fq[f + lag] >> 8 == hi
               for f, hi in stores.items() if f not in short) == (
        len(stores) - len(short))
    assert not any(fq[f + lag] >> 8 == stores[f] for f in short)
