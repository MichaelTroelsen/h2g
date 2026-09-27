"""A record setting effect bits $04 and $10 gets *both*, in one wavetable block.

The two are sequential, independent tests on the same effect byte -- not
exclusive branches. Read off Trans-Atlantic's player, which copies the record's
+7 to the scratch cell `$0EFB` once and then tests it five times running: `$08`
at $0B44, `$04` at $0B9C, `$10` at $0BB8, `$20` at $0BEB and `$40` (as
`BIT`/`BVC`) at $0C05. `$04`'s block writes the voice's *waveform* cell
(`STA $0D5E,X`) and falls through; `$10`'s writes its *frequency* pair. Nothing
between them can skip the second.

So Trans-Atlantic's record 3 (`0AF8`, effect `$14`) plays five frames of its
attack waveform *with* the arpeggio stepping through them, and the arpeggio
keeps running after the waveform goes to `$00`. Before this composition the
two-stage path owned such a record and emitted no arpeggio at all: 0 pitch
reversals in a 60 s trace against the original's 411.

These tests pin the shape, the per-record gating and the one rule that was
found by checking a *second* file -- see `test_the_attack_frame_sounds_the_
pattern_note`.
"""
import pathlib
import sys

from corpus import CORPUS as _CORPUS  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import goatwriter as G
from h2g.convert import _detect_tables
from h2g.sidfile import load_sid

CORPUS = _CORPUS

TWO_STAGE = 0x04
PITCH_SEQ = 0x10


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def _block(name, i, multiplier=1, **opts):
    sid, det = _det(name)
    kw = dict(two_stage=True, pitch_seq=True)
    kw.update(opts)
    return G._wavetable_entries(sid, det, i, True, G.FORMAT_GTS5, [(0, 0)] * 16,
                                multiplier, start=1, budget=200, **kw)


def test_the_composed_block_carries_both_mechanisms():
    """Trans-Atlantic record 3: attack waveform *and* arpeggio, then a loop."""
    if not CORPUS.is_dir():
        return
    sid, det = _det("Trans-Atlantic_Balloon_Challenge")
    base = det.instr_start + 3 * det.instr_stride
    assert sid.data[base + 7] == 0x14          # both bits, and only these two
    assert sid.data[base + 2] == 0x00          # no waveform of its own
    attack = sid.data[det.two_stage_wave + 3 * det.instr_stride]
    frames = sid.data[det.two_stage_frames + 3 * det.instr_stride]
    assert (attack, frames) == (0x11, 5)

    left, right = _block("Trans-Atlantic_Balloon_Challenge", 3)
    # Five frames of the attack waveform, one entry each because a delay entry
    # cannot carry a note that changes on the frames it covers, then the
    # sustain stage, then a jump back to the sustain stage's first entry.
    # The sustain stage is `$18` -- the test bit -- because this record's `+2`
    # selects no waveform at all and the original goes silent there; see
    # test_two_stage.py's `..._goes_silent` and goatwriter._wave_byte.
    assert left == [0x11, 0x11, 0x11, 0x11, 0x11, 0x18, 0x18, 0x18, 0xFF]
    assert right == [0x00, 0x00, 0x18, 0x00, 0x00, 0x18, 0x00, 0x00, 0x06]
    # `+24` is the record's own step: the note, two octaves up.
    assert right[2] == 0x18
    # The jump targets the sustain stage (start 1 + 5 attack calls), not the
    # block -- the attack runs once per note.
    assert right[-1] == 1 + 5


def test_the_arpeggio_phase_is_continuous_across_the_jump():
    """The player's counter free-runs; the loop must not restart the cycle."""
    if not CORPUS.is_dir():
        return
    left, right = _block("Trans-Atlantic_Balloon_Challenge", 3)
    calls, steps = 5, 3
    body = right[:-1]
    for k in range(len(body)):
        assert body[k] == body[k % steps], k
    # ...and re-entering at `calls` lands on the phase the block left off on.
    assert (right[-1] - 1) % steps == calls % steps


def test_the_attack_frame_sounds_the_pattern_note():
    """Entry 0 is a relative +0 wherever the cycle has a zero step.

    Found on Thundercats, not on Trans-Atlantic. Its records 3/4/5/9 (`$34`)
    have a sequence opening `+3`, and emitting it as rotated named all 148 of
    their notes three semitones sharp: reversals came out *exact* (1308 against
    the original's 1308) while melody fell 77.3% -> 65.7% on unchanged note
    counts. Entry 0 is applied on the note's first call, which is where the
    note's identity is read from, so the cycle opens on a zero step.
    """
    if not CORPUS.is_dir():
        return
    for name, recs, mult in (("Trans-Atlantic_Balloon_Challenge", (3,), 1),
                             ("Thundercats", (3, 4, 5, 9), 3),
                             ("Bangkok_Knights", (3, 15), 1),
                             ("W_A_R_Preview", (1,), 1)):
        sid, det = _det(name)
        for i in recs:
            eff = sid.data[det.instr_start + i * det.instr_stride + 7]
            assert eff & TWO_STAGE and eff & PITCH_SEQ, (name, i)
            left, right = _block(name, i, mult)
            # Not a vacuous pass: the composed branch really fired, so the
            # block is not the plain two-stage shape (which also opens on +0).
            assert (left, right) != _block(name, i, mult, pitch_seq=False)
            assert right[0] == G.WAVE_NOTE_BASE, (name, i, right)


def test_the_rate_is_scaled_to_play_calls():
    """Each arpeggio step holds `multiplier` entries, as the attack does.

    The player's phase counter advances once per frame of a single-speed
    original; a Goattracker wavetable steps once per play call. Thundercats
    packs at -S3, so each of its two steps occupies three entries and its
    one-frame attack occupies three.

    This pins the encoding, not a measurement: siddump samples the registers
    once per frame whatever the call rate, so scaled and unscaled score the
    identical 1308 reversals on that file and no trace in the repo can tell
    them apart. See H2G-CONVERSION-METHOD.md section 7.vvv.
    """
    if not CORPUS.is_dir():
        return
    left, right = _block("Thundercats", 3, 3)
    sid, det = _det("Thundercats")
    frames = sid.data[det.two_stage_frames + 3 * det.instr_stride]
    assert frames == 1
    attack = sid.data[det.two_stage_wave + 3 * det.instr_stride]
    # Entry 0 is the note's own first frame -- the record's `+2`, three calls of
    # it (v0.5.217, `_first_frame_entry`) -- and the attack follows.
    own = sid.data[det.instr_start + 3 * det.instr_stride + 2]
    assert own & 0xF0
    assert left[:3] == [own] * 3
    assert left[3:6] == [attack] * 3           # one frame -> three calls
    assert right[:6] == [0x00] * 6             # one step  -> three calls
    assert right[6:9] == [0x03] * 3
    # ...and the loop skips both the lead and the attack, so the arpeggio's
    # phase re-enters where it left.
    assert left[-1] == 0xFF and right[-1] == 1 + 3 + 3


def test_gating_is_per_record_not_per_file():
    """A record without $10 keeps the plain two-stage shape, in the same file.

    `det.pitch_seq` says only that the *player* reads the bit. Gating on the
    file alone is what reached Thundercats' drum in v0.5.206 -- 99 noise frames
    at a pitch its original never sounds.
    """
    if not CORPUS.is_dir():
        return
    sid, det = _det("Trans-Atlantic_Balloon_Challenge")
    assert det.pitch_seq is not None and det.effect_two_stage
    base = det.instr_start + 4 * det.instr_stride
    assert sid.data[base + 7] == 0x24          # $04 and $20, but not $10
    with_ps = _block("Trans-Atlantic_Balloon_Challenge", 4)
    without = _block("Trans-Atlantic_Balloon_Challenge", 4, pitch_seq=False)
    assert with_ps == without


def test_the_standalone_paths_are_untouched():
    """Neither mechanism alone changes, so the eight shipped files cannot move.

    Record 0 sets $10 only and record 2 sets $08 only; both must emit exactly
    what they did before the composition existed.
    """
    if not CORPUS.is_dir():
        return
    sid, det = _det("Trans-Atlantic_Balloon_Challenge")
    assert sid.data[det.instr_start + 0 * det.instr_stride + 7] == 0x10
    # A record with $10 and no $04 never enters the composed branch, so turning
    # two_stage off cannot change it.
    assert (_block("Trans-Atlantic_Balloon_Challenge", 0)
            == _block("Trans-Atlantic_Balloon_Challenge", 0, two_stage=False))


def test_a_block_that_will_not_fit_falls_back():
    """Budget refusal returns the plain two-stage shape, never a truncation."""
    if not CORPUS.is_dir():
        return
    sid, det = _det("Trans-Atlantic_Balloon_Challenge")
    attack = sid.data[det.two_stage_wave + 3 * det.instr_stride]
    frames = sid.data[det.two_stage_frames + 3 * det.instr_stride]
    notes = G._pitch_seq_notes(sid, det, 3)
    assert notes is not None
    assert G._two_stage_pitch_seq_entries(0x00, attack, frames, notes, 1,
                                          1, budget=8) is None
    assert G._two_stage_pitch_seq_entries(0x00, attack, frames, notes, 1,
                                          1, budget=9) is not None
    # ...and the caller then emits the shape it always did.
    left, right = _block("Trans-Atlantic_Balloon_Challenge", 3)
    tight = G._wavetable_entries(sid, det, 3, True, G.FORMAT_GTS5,
                                 [(0, 0)] * 16, 1, start=1, budget=5,
                                 two_stage=True, pitch_seq=True)
    assert tight == G._two_stage_entries(0x00, attack, frames, 1)


def test_a_budget_refusal_logs_which_record_and_why():
    """A synthetic record whose composed block exceeds its share is named.

    `_two_stage_pitch_seq_entries` used to fall back silently -- the record
    lost its arpeggio and nothing said so. A divider makes the block
    `frames_per_step` times longer (34 entries on Food_Feud), so a file with
    more instruments than Food_Feud can push a record's share below what its
    own block needs; the fallback must then log the record, the block length
    it needed and the share it was given, not just fall back quietly.
    """
    notes = [0x00, 124]
    # frames_per_step=4, 2 notes -> loop = 2*4 = 8 entries; frames=2 -> attack
    # 2 entries; lead 1 (0x11 sets a real waveform, so _first_frame_entry is
    # true); +1 for the trailing jump. Needed = 1 + 2 + 8 + 1 = 12.
    logged = []
    got = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, notes, 1, 1,
                                         budget=11, frames_per_step=4,
                                         log=logged.append, record=0x2A)
    assert got is None
    assert len(logged) == 1
    msg = logged[0]
    assert "$2A" in msg
    assert "NEEDS 12" in msg
    assert "ONLY 11" in msg
    # One more entry of budget and the same block fits -- and logs nothing.
    logged.clear()
    fits = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, notes, 1, 1,
                                          budget=12, frames_per_step=4,
                                          log=logged.append, record=0x2A)
    assert fits is not None
    assert logged == []
    # With no `record`, the message still names the block length vs share.
    logged.clear()
    G._two_stage_pitch_seq_entries(0x11, 0x41, 2, notes, 1, 1,
                                   budget=11, frames_per_step=4,
                                   log=logged.append)
    assert logged and "NEEDS 12" in logged[0] and "ONLY 11" in logged[0]


def test_no_corpus_record_falls_back_at_this_head():
    """Corpus-wide, with pitch_seq and two_stage forced on, count how many
    records reach `_two_stage_pitch_seq_entries` and lose their arpeggio to a
    budget refusal. Food_Feud's own composed block (34 entries,
    `frames_per_step=4`) fits comfortably in that file's real wavetable share
    because it has few instruments -- the corpus check is what tells us
    whether some *other* file's instrument count pushes a record's share
    below what its own block needs. Expect 0: state the number rather than
    assume it, per CLAUDE.md's probe discipline."""
    if not CORPUS.is_dir():
        return
    from h2g.convert import convert
    hits = []

    def log(msg):
        if "PITCH-SEQ ARPEGGIO ON INSTRUMENT" in msg and "DROPPED" in msg:
            hits.append(msg)

    converted = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            convert(path, log=log, two_stage=True, pitch_seq=True)
            converted += 1
        except Exception:
            continue
    assert converted > 50, converted   # sanity: most of the corpus converts
    assert hits == [], (len(hits), hits[:3])


def test_the_divider_lengthens_the_step_and_not_the_attack():
    """`frames_per_step` scales the arpeggio's hold; the attack keeps `frames`.

    Bit $04's counter is a per-voice cell and the divider gates only the
    global phase, so on Food_Feud's record 2 (`$34`: attack `$41` for two
    frames, notes [124, 0], divider 4) at -S3 the attack is still six calls
    and each step is twelve. The loop is two full steps, so the entry after
    its last names the step its first names and the phase stays continuous
    across the jump whatever the attack's length modulo the step.
    """
    notes = [0x00, 124]
    # 34 entries: past the five-entry default, inside Food_Feud's real share
    # of the 255-entry table (the A/B's bytes moved, so the block fits there).
    one = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, notes, 1, 3,
                                         budget=200)
    four = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, notes, 1, 3,
                                          budget=200, frames_per_step=4)
    assert one is not None and four is not None
    l1, r1 = one
    l4, r4 = four
    assert l1[:3] == l4[:3] == [0x11] * 3                  # the first frame
    assert l1[3:9] == l4[3:9] == [0x41] * 6                # two frames of attack
    assert l1[-1] == l4[-1] == 0xFF and r1[-1] == r4[-1] == 1 + 3 + 6
    assert len(l1) == 3 + 6 + 2 * 3 + 1
    assert len(l4) == 3 + 6 + 2 * 12 + 1
    body = r4[3:-1]
    assert body == [0] * 12 + [124] * 12 + [0] * 6
    # continuity: the jump lands on body[6], step 0, which is also what the
    # entry after the body's last would name (30 // 12 % 2 == 0)
    assert body[6] == notes[(len(body) // 12) % 2] == 0
    if CORPUS.is_dir():
        sid, det = _det("Food_Feud")
        assert det.pitch_seq.frames_per_step == 4
        assert _block("Food_Feud", 2, 3) == four


# --- the arpeggio carried in the original's phase (`frame_notes`) ------------

# Food_Feud record 2's cycle from residue 0: the cell reads 1 1 0 0 0 0 1 1
# on calls 0..7 (tests/test_pitch_seq_shapes.py), so frame j sounds the pair
# step 124 where that reads 1 and the note where it reads 0.
_FF_R0 = [124, 124, 0, 0, 0, 0, 124, 124]


def test_frame_notes_follow_the_frame_each_call_falls_in():
    """-S3, the record's own first frame (3 calls), a 2-frame attack.

    Call `lead + c` is in frame `(lead + c) // 3`, so body entry c names
    `_FF_R0[(1 + c // 3) % 8]`: frame 1 is 124, frames 2-5 the note, 6-9
    124, 10 the note -- NOT the rotation, which opens on four frames of the
    note (residue 1, where no Food_Feud attack lands)."""
    got = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, [0x00, 124], 1, 3,
                                         budget=200, frames_per_step=4,
                                         frame_notes=_FF_R0)
    assert got is not None
    left, right = got
    assert left[:3] == [0x11] * 3 and right[:3] == [0] * 3    # frame 0
    assert left[3:9] == [0x41] * 6                            # the attack
    body = right[3:-1]
    assert body == [124] * 3 + [0] * 12 + [124] * 12 + [0] * 3
    assert left[-1] == 0xFF and right[-1] == 1 + 3 + 6
    # continuity: the entry after the last (c = 30, frame 11) names what the
    # jump target (c = 6, frame 3) names
    assert _FF_R0[11 % 8] == body[6] == 0
    # the waveform column is the unphased block's, entry for entry
    plain = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, [0x00, 124], 1, 3,
                                           budget=200, frames_per_step=4)
    assert left == plain[0] and right != plain[1]


def test_frame_zero_is_the_pattern_note_whatever_the_phase_says():
    """No first-frame entry (`+2` $00): entry 0 is frame 0 and stays the
    note even where the residue's frame 0 reads the pair step."""
    left, right = G._two_stage_pitch_seq_entries(0x00, 0x41, 2, [0x00, 124],
                                                 1, 3, budget=200,
                                                 frames_per_step=4,
                                                 frame_notes=_FF_R0)
    assert _FF_R0[0] == 124
    assert right[:3] == [0, 0, 0]                            # frame 0
    assert right[3:6] == [124] * 3                           # frame 1


def test_frame_notes_of_the_wrong_length_fall_back_to_the_rotation():
    """A cycle that is not one loop long cannot keep the jump continuous;
    the block is then exactly the unphased one."""
    plain = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, [0x00, 124], 1, 3,
                                           budget=200, frames_per_step=4)
    short = G._two_stage_pitch_seq_entries(0x11, 0x41, 2, [0x00, 124], 1, 3,
                                           budget=200, frames_per_step=4,
                                           frame_notes=_FF_R0[:4])
    assert short == plain


def test_build_sng_hands_each_34_record_its_majority_residue(monkeypatch):
    """Preset + pitch_seq on Food_Feud: records 2 and 3 (GT 3 and 4) are
    phased at residues 0 and 6 (`pitch_seq_phases`), nothing else is asked,
    and with pitch_seq off nothing is asked at all."""
    if not CORPUS.is_dir():
        return
    import json
    import fidelity
    from h2g.convert import convert
    presets = json.loads((pathlib.Path(__file__).resolve().parents[2]
                          / "presets.json").read_text())
    opts = dict(fidelity._preset_opts(presets, "Food_Feud.sid"))
    asked = []
    real = G.pitch_seq_frame_notes

    def spy(sid, det, i, residue):
        asked.append((i, residue))
        return real(sid, det, i, residue)

    monkeypatch.setattr(G, "pitch_seq_frame_notes", spy)
    convert(CORPUS / "Food_Feud.sid", log=lambda *a, **k: None,
            **{**opts, "pitch_seq": True})
    assert sorted(asked) == [(2, 0), (3, 6)]
    asked.clear()
    convert(CORPUS / "Food_Feud.sid", log=lambda *a, **k: None,
            **{**opts, "pitch_seq": False})
    assert asked == []
