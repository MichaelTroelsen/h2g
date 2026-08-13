"""What the `onset` column's disagreements are made of.

The column reports a rate, and a rate says how much is wrong without saying
what to do about it. The census classifies the same comparison by the *kind* of
its disagreement, which is the difference between a report and a queue: the
first grouping of `flat` misses by the source record's effect byte turned "18%
disagree" into `$01 x19, $04 x11, $80 x6, $0A x6`, and the last of those groups
was a decoded mechanism (v0.5.231) within the same session.

The property these tests exist to hold is that the census cannot drift from the
column it classifies: same population, same modal reduction, and a `phase`
count that is the report's own `onset_ours_early` + `_late`.
"""
from collections import Counter

import fidelity as F


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad),
                  attack_frames=list(at))
          for wf, ad, at in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


def _wf(*classes):
    """Waveform events spelling one four-frame onset shape."""
    return [(i, c | 0x01) for i, c in enumerate(classes)]


def _side(*classes, adsr=0x0A09):
    return _voices((_wf(*classes), [(0, adsr)], [0]))


TRI, NOI, PUL, SAW = 0x10, 0x80, 0x40, 0x20


# ---- the kinds ------------------------------------------------------------

def test_identical_shapes_are_a_match():
    assert F.classify_onset((TRI, NOI, TRI, PUL), (TRI, NOI, TRI, PUL)) == "match"


def test_ours_one_frame_early_is_phase():
    """We never played the original's first frame -- section 7.www's defect."""
    assert F.classify_onset((TRI, NOI, TRI, PUL), (NOI, TRI, PUL, NOI)) == "phase"


def test_ours_one_frame_late_is_phase_too():
    assert F.classify_onset((NOI, TRI, PUL, NOI), (TRI, NOI, TRI, PUL)) == "phase"


def test_a_held_waveform_against_a_moving_one_is_flat():
    """A mechanism the original runs and we do not render at all."""
    assert F.classify_onset((TRI, NOI, TRI, TRI), (TRI, TRI, TRI, TRI)) == "flat"


def test_moving_where_the_original_holds_is_invented():
    assert F.classify_onset((TRI, TRI, TRI, TRI), (TRI, NOI, TRI, TRI)) == "invented"


def test_some_frames_right_is_partial():
    assert F.classify_onset((TRI, NOI, TRI, PUL), (TRI, PUL, SAW, NOI)) == "partial"


def test_no_frame_right_is_wrong():
    assert F.classify_onset((TRI, NOI, TRI, PUL), (SAW, PUL, NOI, TRI)) == "wrong"


def test_a_shifted_shape_that_is_also_flat_counts_as_phase():
    """Ordering, and the reason for it: the report's early/late test is the
    same shift test computed independently, so a shape that satisfies both
    definitions has to land in `phase` or the two readings of one corpus stop
    matching -- which is the check that makes either worth quoting."""
    orig, ours = (NOI, TRI, TRI, TRI), (TRI, TRI, TRI, TRI)
    assert F.classify_onset(orig, ours) == "phase"


# ---- the census against the column it classifies --------------------------

def test_the_population_is_the_columns_denominator():
    """Instruments both sides sound, and only those: one we drop entirely is
    absent here rather than counted wrong, because `melody` already reports it."""
    o = _voices((_wf(TRI, NOI, TRI, PUL), [(0, 0x0A09)], [0]),
                (_wf(SAW, SAW, SAW, SAW), [(0, 0x0F00)], [0]))
    u = _voices((_wf(TRI, NOI, TRI, PUL), [(0, 0x0A09)], [0]))
    census = F.onset_census(o, u, 8)
    agree = F.onset_agreement(o, u, 8)
    assert len(census) == agree["onset_instruments"] == 1


def test_the_match_count_is_the_columns_numerator():
    o = _voices((_wf(TRI, NOI, TRI, PUL), [(0, 0x0A09)], [0]),
                (_wf(SAW, SAW, SAW, SAW), [(0, 0x0F00)], [0]))
    u = _voices((_wf(TRI, NOI, TRI, PUL), [(0, 0x0A09)], [0]),
                (_wf(SAW, NOI, SAW, SAW), [(0, 0x0F00)], [0]))
    census = F.onset_census(o, u, 8)
    agree = F.onset_agreement(o, u, 8)
    assert sum(1 for r in census if r["kind"] == "match") == agree["onset_matched"]
    assert Counter(r["kind"] for r in census)["invented"] == 1


def test_the_phase_count_is_the_reports_early_plus_late():
    """The census is a classification of the column's own comparison; if these
    two ever disagree, one of them has changed its mind about what a shift is."""
    o = _voices((_wf(TRI, NOI, TRI, PUL), [(0, 0x0A09)], [0]),
                (_wf(NOI, TRI, PUL, NOI), [(0, 0x0F00)], [0]))
    u = _voices((_wf(NOI, TRI, PUL, NOI), [(0, 0x0A09)], [0]),
                (_wf(TRI, NOI, TRI, PUL), [(0, 0x0F00)], [0]))
    agree = F.onset_agreement(o, u, 8)
    phase = sum(1 for r in F.onset_census(o, u, 8) if r["kind"] == "phase")
    assert phase == agree["onset_ours_early"] + agree["onset_ours_late"] == 2


def test_a_stamp_attaches_the_effect_byte_to_the_instrument():
    o = _side(TRI, NOI, TRI, PUL)
    u = _side(TRI, TRI, TRI, TRI)
    rec = F.onset_census(o, u, 8, {0x0A09: {"gt": 3, "effect": 0x04}})[0]
    assert (rec["kind"], rec["gt"], rec["effect"]) == ("flat", 3, 0x04)


# ---- the join key ---------------------------------------------------------

def test_stamps_are_read_out_of_the_shipped_file():
    """The instrument name is the converter's provenance stamp, so the source
    record's effect byte is recoverable from the output without re-running
    detection."""
    from pathlib import Path
    sng = Path(__file__).resolve().parents[2] / "Commando.sng"
    stamps = F.instrument_stamps(sng.read_bytes())
    assert stamps, "no instruments parsed out of the fixture"
    assert all(isinstance(v["gt"], int) for v in stamps.values())
    assert any(v.get("effect") is not None for v in stamps.values())


def test_two_instruments_sharing_an_adsr_are_marked_rather_than_guessed():
    """The trace cannot say which of them it heard, so the entry says so: an
    effect byte named for the wrong instrument is a wrong work-list entry."""
    import songview

    class _Ins:
        def __init__(self, n, ad, sr, eff):
            self.number, self.ad, self.sr, self._eff = n, ad, sr, eff

        @property
        def effect_byte(self):
            return self._eff

    class _Song:
        instruments = [_Ins(1, 0x0A, 0x09, 0x04), _Ins(2, 0x0A, 0x09, 0x80)]

    real = songview.parse_sng
    songview.parse_sng = lambda blob: _Song()
    try:
        stamps = F.instrument_stamps(b"")
    finally:
        songview.parse_sng = real
    assert stamps[0x0A09]["gt"] == 1
    assert stamps[0x0A09]["ambiguous"] is True


# ---- the document ---------------------------------------------------------

def test_the_work_list_groups_flat_misses_by_effect_byte():
    rows = [{"file": "a.sid", "onset_census": [
        {"adsr": 0x0A09, "kind": "flat", "orig": [TRI, NOI, TRI, TRI],
         "ours": [TRI, TRI, TRI, TRI], "orig_notes": 9, "our_notes": 9,
         "gt": 1, "effect": 0x01},
        {"adsr": 0x0F00, "kind": "match", "orig": [TRI] * 4, "ours": [TRI] * 4,
         "orig_notes": 3, "our_notes": 3, "gt": 2, "effect": 0x00}]},
            {"file": "b.sid", "onset_census": [
                {"adsr": 0x0B09, "kind": "flat", "orig": [PUL, NOI, PUL, PUL],
                 "ours": [PUL] * 4, "orig_notes": 4, "our_notes": 4,
                 "gt": 1, "effect": 0x01}]}]
    text = F.census_report(rows)
    assert "| `$01` | 2 | a.sid, b.sid |" in text
    assert "| match | 1 |" in text
    assert "`tri noi tri tri`" in text


def test_a_note_that_ends_inside_the_window_is_short_not_phase():
    """Three of the corpus's six `phase` entries were this: `noi noi noi --`
    against `noi noi noi noi`, which satisfies the shift test vacuously because
    the original's shape is constant. It is a note-length difference, and
    calling it a phase error sends the reader to the wrong fix."""
    assert F.classify_onset((NOI, NOI, NOI, NOI), (NOI, NOI, NOI, 0)) == "short"


def test_short_outranks_invented():
    """`invented` would say we move where the original holds -- true of the
    register and misleading about the cause."""
    assert F.classify_onset((TRI, TRI, TRI, TRI), (TRI, TRI, 0, 0)) == "short"


def test_a_real_shift_is_still_phase():
    """Rasputin's three: `pul pul noi pul` against `pul noi pul pul`, which the
    unshifted reading does not fit."""
    assert F.classify_onset((PUL, PUL, NOI, PUL), (PUL, NOI, PUL, PUL)) == "phase"


def test_the_kinds_the_report_prints_are_the_kinds_it_can_produce():
    """A kind missing from ONSET_KINDS would be silently dropped from the
    census table's ordering."""
    shapes = [(TRI, NOI, TRI, PUL), (TRI, TRI, TRI, TRI), (NOI, TRI, PUL, NOI),
              (TRI, TRI, 0, 0), (SAW, PUL, NOI, TRI), (PUL, NOI, PUL, PUL)]
    produced = {F.classify_onset(a, b) for a in shapes for b in shapes}
    assert produced <= set(F.ONSET_KINDS)
