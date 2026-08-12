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
    assert left == [0x11, 0x11, 0x11, 0x11, 0x11, 0x10, 0x10, 0x10, 0xFF]
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
    assert left[:3] == [attack] * 3            # one frame -> three calls
    assert right[:3] == [0x00] * 3             # one step  -> three calls
    assert right[3:6] == [0x03] * 3
    assert left[-1] == 0xFF and right[-1] == 1 + 3


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
