"""A two-entry wave-program opcode ends on its frame's last play call.

Opened as drum-frequency-sequences-off-grid: Lion_Heart `$1167` (record 3,
`set $81 $5F / slide $41 $015A / slide $41 $0452 / ...`) reads, a frame each,
`5F67 100D 0BBB 5FBB` in the original and read `5CF1 1168 100E 6278` in ours
at -S3 -- the first slide's travel one frame late and the second never
sampled (the next `set` overwrote it).

The trace samples a frame after its LAST call (`heard.frames`). Under
gt2reloc's default startup row the first wavetable call of a note is the
last call of its frame at -S3 (`call_phase.default_onset_position`), and the
pair "waveform on the note, then the portamento" started there: the waveform
was sampled and the portamento ran on the NEXT frame's first call. The
previous opcode's hold now gives up one call so the pair ends on the sample
(`wave_program.PAIR_ENDS_FRAME`).

Only where `convert` knows the position (`call_phase.onset_position_scope`):
the same shift on a song with a startup record (ACE_II, Thundercats,
Saboteur_II) or at -S2 puts the waveform a frame EARLY (heard.py instr
93.8 -> 91.0, 87.3 -> 83.1, 92.1 -> 49.2 with it applied everywhere).
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

PORTADOWN, PORTAUP = 0xF2, 0xF1
LION_HEART_DRUM = 2                    # record 3: set / slide / slide / sets


def _calls(left):
    """Wavetable call number (1-based) of each entry: a delay of `v` is
    `v + 1` calls (gplay.c:697-704), every other entry one."""
    at, out = 1, []
    for b in left:
        out.append(at)
        at += b + 1 if 1 <= b <= 0x0F else 1
    return out


def _entries(position, multiplier=3, i=LION_HEART_DRUM):
    from h2g.convert import _detect_tables
    from h2g.goatwriter import call_phase
    from h2g.goatwriter.wave_program import _wave_program_entries
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / "Lion_Heart.sid")),
                              lambda *a, **k: None)
    with call_phase.onset_position_scope(position):
        got = _wave_program_entries(sid, det, i, [], "gts5", multiplier, 60)
    assert got is not None
    return list(got[0]), list(got[1])


def _travel_calls(left):
    return [c for c, b in zip(_calls(left), left) if b in (PORTADOWN, PORTAUP)]


def test_default_onset_position_is_the_last_call_only_at_s3():
    from h2g.goatwriter.call_phase import default_onset_position
    assert [default_onset_position(m) for m in (2, 3, 4, 5)] == [0, 2, 2, 2]
    assert default_onset_position(3) == 3 - 1


def test_position_is_unknown_outside_a_scope():
    from h2g.goatwriter import call_phase
    assert call_phase.onset_position() is None
    with call_phase.onset_position_scope(2):
        assert call_phase.onset_position() == 2
    assert call_phase.onset_position() is None


@needs_corpus
def test_travel_lands_on_the_sampled_call_under_the_default_phase():
    # wavetable call 1 sits on position 2 of its frame, so the sample (the
    # frame's last call) is every call c with c % 3 == 1
    left, _ = _entries(2)
    travel = _travel_calls(left)
    assert len(travel) >= 2, [hex(b) for b in left]
    assert all(c % 3 == 1 for c in travel), travel


@needs_corpus
def test_it_was_the_frames_first_call_before():
    left, _ = _entries(None)
    assert all(c % 3 == 2 for c in _travel_calls(left)), _travel_calls(left)


@needs_corpus
def test_it_costs_no_entry_and_no_call():
    on_l, on_r = _entries(2)
    off_l, off_r = _entries(None)
    assert len(on_l) == len(off_l) and len(on_r) == len(off_r)
    # every opcode is as long in calls as it was, so each later `set` opcode
    # (noise, `$80`/`$81`) runs on the call it ran on; only the stop moves,
    # one call earlier, because the closing pair (restore, then the travel of
    # the slides' sum) ends on the sample too and nothing holds after it
    assert _calls(on_l)[-1] == _calls(off_l)[-1] - 1
    def sets(left, right):
        # a noise entry that writes a pitch (right `$80` is "keep": a hold)
        return [c for c, b, r in zip(_calls(left), left, right)
                if b in (0x80, 0x81) and r != 0x80]
    # (the last is the closing restore, which moves with the closing pair)
    assert sets(on_l, on_r)[:-1] == sets(off_l, off_r)[:-1]


@needs_corpus
def test_a_rate_that_is_not_s3_keeps_the_layout():
    # the position is only 2 at -S3; at -S2 the pair is whole in its frame
    # already, and a caller that says 0 there must not be shifted
    assert _entries(0, multiplier=2) == _entries(None, multiplier=2)


@needs_corpus
def test_short_circuit_restores_the_old_layout(monkeypatch):
    from h2g.goatwriter import wave_program
    monkeypatch.setattr(wave_program, "PAIR_ENDS_FRAME", False)
    left, _ = _entries(2)
    assert all(c % 3 == 2 for c in _travel_calls(left))


@needs_corpus
def test_convert_names_the_position_only_for_the_default_phase(monkeypatch):
    """Lion_Heart is on the default startup row; ACE_II gets a startup record
    (17 calls where the default is 18), so its position is unknown."""
    import json

    import fidelity
    from h2g.convert import convert
    from h2g.goatwriter import call_phase

    seen = []
    real = call_phase.onset_position_scope

    def spy(position):
        seen.append(position)
        return real(position)
    monkeypatch.setattr(call_phase, "onset_position_scope", spy)
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    got = {}
    for name in ("Lion_Heart.sid", "ACE_II.sid"):
        del seen[:]
        convert(str(CORPUS / name), log=lambda m: None,
                **fidelity._preset_opts(doc, name))
        got[name] = seen[-1]
    assert got["Lion_Heart.sid"] == 2, got
    assert got["ACE_II.sid"] is None, got
