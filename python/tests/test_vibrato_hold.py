"""The classic vibrato as a frame-held wavetable program (h2g.vibrato_hold).

Thanatos voice 0, original (siddump -m1, frames 3-17): `3A8C 3B5E 3A8C 39BA 3A8C
3B5E ...`, one value per frame, +-$D2. The instrument vibrato stepped `$37` on
every one of the four calls a frame (C:/t/thanatos-s4-vibrato-frame-hold). The
held program steps `$F4 nn` once every `multiplier` calls and waits between.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import vibrato_hold as vh                           # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
STEP = (vh._WAVECMD_VIBRATO, 10)


def run_program(rows, start, calls):
    """Which calls execute the `$F4` row, by gplay.c's wavetable loop: a delay
    row `d` holds `d + 1` calls, any other row one, `$FF` jumps for free."""
    ptr, wavetime, hits = start, 0, []
    for call in range(calls):
        left, right = rows[ptr - 1]
        if left <= 0x0F:
            if left != wavetime:
                wavetime += 1
                continue
        elif left == vh._WAVECMD_VIBRATO:
            hits.append(call)
        wavetime = 0
        ptr += 1
        if rows[ptr - 1][0] == 0xFF:
            ptr = rows[ptr - 1][1]
    return hits


def vibtime_signs(cmp_value, steps):
    """The sign of each step (gplay.c:795-801)."""
    vt, out = 0, []
    for _ in range(steps):
        if vt < 0x80 and vt > cmp_value:
            vt ^= 0xFF
        vt = (vt + 2) & 0xFF
        out.append(-1 if vt & 1 else 1)
    return out


# Thanatos instrument 1: waveform, hold 3 calls, waveform, hold 7, waveform, stop.
THANATOS_1 = {0: (0x41, 0x80), 4: (0x21, 0x80), 12: (0x41, 0x80)}


@pytest.mark.parametrize("calls", [2, 3, 4])
def test_the_program_steps_on_the_frame_lattice_and_nowhere_else(calls):
    events = {t * calls // 4 * 1: v for t, v in THANATOS_1.items()}
    end_t = 13 * calls // 4
    rows = vh._held_rows(events, end_t, STEP, calls, calls, 1)
    hits = run_program(rows, 1, 40 * calls)
    # one step per frame from the first frame after the note; a step that
    # lands on a waveform row is one call late
    taken = {t for t in events}
    expect = [t + (1 if t in taken else 0)
              for t in range(calls, 40 * calls, calls)]
    assert hits[:len(expect) - 2] == expect[:len(expect) - 2]
    assert rows[-1][0] == 0xFF and rows[-1][1] <= len(rows)


def test_thanatos_staircase_is_plus_minus_minus_plus():
    """cmp = bound - 2: bound 2 walks + - - + + - - + from the note, the
    original's `3A8C 3B5E 3A8C 39BA 3A8C 3B5E`."""
    assert vibtime_signs(0, 8) == [1, -1, -1, 1, 1, -1, -1, 1]


@pytest.mark.parametrize("bound", [2, 3, 4, 5, 8])
def test_the_half_period_is_bound_steps(bound):
    """`cmp = bound - 2` (VIBRATO_CMP_BIAS): after the first, half-length half,
    each run of one sign is `bound` steps -- the player's counter walking 0 to
    `bound` and back, a step a frame."""
    signs = vibtime_signs(bound - 2, 12 * bound)[bound:]
    runs, n = [], 1
    for a, b in zip(signs, signs[1:]):
        if a == b:
            n += 1
        else:
            runs.append(n)
            n = 1
    assert runs[1:-1] and set(runs[1:-1]) == {bound}


def test_a_one_call_wait_repeats_the_last_waveform():
    """No delay row holds one call (`d` 0 is no delay): the row is the last
    waveform again with no note."""
    rows = vh._held_rows({0: (0x41, 0x80)}, 1, STEP, 2, 2, 1)
    assert (0x41, 0x80) in rows[1:]
    assert all(left != 0 for left, _ in rows)
    assert run_program(rows, 1, 12) == [2, 4, 6, 8, 10]


def test_a_one_call_wait_with_no_waveform_declines():
    with pytest.raises(vh._Unsupported):
        vh._held_rows({}, 0, STEP, 2, 2, 1)


def test_off_by_default():
    import inspect
    assert inspect.signature(convert).parameters["vibrato_hold"].default is False


def _opts(name, on):
    doc = json.loads(PRESETS.read_text())
    return dict(fidelity._preset_opts(doc, name), vibrato_hold=on)


@needs_corpus
def test_thanatos_takes_every_vibrato_record_and_only_those():
    lines = []
    off = convert(str(CORPUS / "Thanatos.sid"), log=lambda m: None,
                  **_opts("Thanatos.sid", False))
    on = convert(str(CORPUS / "Thanatos.sid"), log=lines.append,
                 **_opts("Thanatos.sid", True))
    assert any("Frame-held vibrato" in m and "5 record(s)" in m for m in lines)
    a, b = songview.parse_sng(off), songview.parse_sng(on)
    assert [i.vib_ptr for i in a.instruments if i.vib_ptr]
    assert not [i for i in b.instruments if i.vib_ptr]
    assert [(i.ad, i.sr, i.name) for i in a.instruments] == \
        [(i.ad, i.sr, i.name) for i in b.instruments]
    assert a.patterns == b.patterns and a.tracks == b.tracks
    assert on != off


@needs_corpus
def test_a_song_at_the_player_rate_is_unchanged():
    """A multiplier-1 song has no sub-frame step to hold."""
    name = "Commando.sid"
    path = CORPUS / name
    if not path.exists():
        pytest.skip("no Commando in the corpus")
    off = convert(str(path), log=lambda m: None, vibrato_hold=False)
    on = convert(str(path), log=lambda m: None, vibrato_hold=True)
    assert on == off
