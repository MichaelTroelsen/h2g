"""Effect bit $40 with no $04: the fixed attack pitch the wavetable now emits.

The `$40` handler (`BIT effect / BVC / LDA counter,X / BEQ / DEC counter,X /
LDA idx,Y`) tests the per-voice counter bit $04's attack waveform shares. A
record that sets only `$40` still gets the counter loaded from the frame-count
array at the note's first call, so the original plays the pattern's note on
frame 0 and then the fixed pitch for `frames` frames -- not halved, because no
`$04` handler decrements beside it. Lightforce record 6 (`$40`, frames 4, note
index `$26` = `$09C4`), measured on the original with siddump-rt at -m1:

    frame 897  04E2   the played note
    898-901    09C4   the fixed pitch, 4 frames
    902 ...    04D1 04E2 04F3 0504   the vibrato, from the played note
                                      (even onset; the odd onsets, 953 and
                                      1065 ..., open 0504 04F3 04E2 04D1)

`_two_stage_entries` emitted that pitch only inside the `$04` block, so a
`$40`-only record fell to the plain shape and never sounded it. 16 onsets of
the record in Lightforce's first 180 s: 0 of 64 pitch frames agreed with the
original before, 64 of 64 after.
"""
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import goatwriter as G                              # noqa: E402
from h2g.convert import _detect_tables                       # noqa: E402
from h2g.detect import (_effect_byte_address, TWO_STAGE_SHAPE,   # noqa: E402
                        TWO_STAGE_SHAPE_ILV, TWO_STAGE_SHAPE_ZP, detect)
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

RT = pathlib.Path(fidelity.SIDDUMP_RT)
needs_rt = pytest.mark.skipif(
    not RT.exists(), reason="tools/siddump-rt not built (see its README)")


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def _block(name, i, multiplier=1, **opts):
    sid, det = _det(name)
    kw = dict(two_stage=True)
    kw.update(opts)
    return G._wavetable_entries(sid, det, i, True, G.FORMAT_GTS5,
                                [(0, 0)] * 16, multiplier, start=1,
                                budget=200, **kw)


# Lightforce record 6: effect $40, frame byte 4, note index $26 -> absolute
# note $A6 (GT note 38 of the player's own table).
NOTE = 0xA6


@needs_corpus
def test_lightforce_record_6_reads_note_a6_for_4_frames():
    sid, det = _det("Lightforce")
    assert G.fixed_attack_only(sid, det, 6) == (NOTE, 4)


@needs_corpus
def test_a_44_record_is_not_a_40_only_record():
    """Record 0 is `$44`: `_two_stage_entries` owns it, with its halved
    frames. Reading "has $40" here would give it a second, unhalved block."""
    sid, det = _det("Lightforce")
    assert sid.data[det.instr_start + 7] == 0x44
    assert G.fixed_attack_only(sid, det, 0) is None
    # ... nor is a `$04`-only or a `$10`-only record.
    assert G.fixed_attack_only(sid, det, 5) is None
    assert G.fixed_attack_only(sid, det, 9) is None


@needs_corpus
def test_block_at_minus_s1_is_lead_then_four_frames_of_the_fixed_note():
    """Frame 0 plays the played note (right `$00`), frames 1-4 the fixed note,
    then the record's own waveform at the played note and a stop. Four, not
    two: a halving here would be `_two_stage_frames`' `$04`+`$40` rule applied
    to a record that has no `$04`."""
    left, right = _block("Lightforce", 6, 1)
    assert left == [0x41] * 6 + [0xFF]
    assert right == [0x00] + [NOTE] * 4 + [0x00, 0x00]


@needs_corpus
def test_block_at_minus_s2_spells_each_call_of_the_frame_count():
    """One frame is `multiplier` calls: a lead frame of 2, 8 calls of the
    fixed note (4 frames), the tail."""
    left, right = _block("Lightforce", 6, 2)
    assert left == [0x41] * 11 + [0xFF]
    assert right == [0x00] * 2 + [NOTE] * 8 + [0x00, 0x00]


@needs_corpus
def test_written_firstwave_drops_the_lead_frame():
    left, right = _block("Lightforce", 6, 2, no_test_restart=True)
    assert left == [0x41] * 9 + [0xFF]
    assert right == [NOTE] * 8 + [0x00, 0x00]


@needs_corpus
def test_block_is_only_emitted_under_the_two_stage_option():
    """Everything else about the `$04` family is behind `two_stage`; the new
    shape is too, so a default conversion keeps its bytes."""
    plain = _block("Lightforce", 6, 1, two_stage=False)
    assert plain == ([0x41, 0x41, 0x41, 0xFF, 0xFF], [0] * 5)


@needs_corpus
def test_a_record_no_pattern_names_keeps_the_plain_shape():
    """Sun_Never_Shines' instrument count runs past its table into data:
    record 17 reads `$40`, frames 128, note index 0. Called directly (no
    `min_notes`) it emits as the record says; with `min_notes` omitting it --
    an instrument no reachable pattern plays -- it keeps the five-entry shape
    instead of laying out 128 frames for a record no music reaches (252
    bytes of wavetable at the corpus byte-hash before this guard)."""
    sid, det = _det("Sun_Never_Shines")
    assert G.fixed_attack_only(sid, det, 17) is not None
    open_ = _block("Sun_Never_Shines", 17, 1)
    assert len(open_[0]) > 100
    # GT number = record + lead (1) + 1 = 19
    assert _block("Sun_Never_Shines", 17, 1, min_notes={19: 0}) == open_
    unnamed = _block("Sun_Never_Shines", 17, 1, min_notes={})
    assert len(unnamed[0]) == 5


@needs_corpus
def test_a_flagged_note_on_such_a_record_keeps_the_full_start():
    """`free_note_record_has_attack` follows the emission: the record now
    plays an attack its full start owns, and a flagged note skips (the counter
    is not reloaded), so a pulse-only variant would keep the fixed pitch. The
    row declines instead; no corpus row reaches it."""
    from h2g.goatwriter import note_passes as NP
    sid, det = _det("Lightforce")
    assert NP.free_note_record_has_attack(sid, det, 6) is True
    assert NP.free_note_wave_start(sid, det, 6, [(0x41, 0)] * 12, 1) == 0


@needs_corpus
def test_the_handler_counter_is_the_two_stage_counter_in_every_file():
    """`fixed_attack_only` reads the frame count from the array that feeds
    bit $04's counter. That is the handler's counter in all 43 corpus files
    that carry both blocks -- re-derived here, not assumed."""
    checked = 0
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None, engine=0)
        except Exception:
            continue
        if not det.effect_bit40 or not det.effect_two_stage:
            continue
        addr, zp = _effect_byte_address(sid, det)
        d = sid.data
        head = (bytes((0x24, addr)) if zp
                else bytes((0x2C, addr & 0xFF, addr >> 8)))
        handler = set()
        i = d.find(head)
        while i >= 0:
            j = i + len(head) + 2
            if d[j - 2] in (0x50, 0x70) and d[j] == 0xBD and d[j + 3] == 0xF0 \
                    and d[j + 5] == 0xDE:
                handler.add(bytes(d[j + 1:j + 3]))
            # The zero-page countdown (Mega_Apocalypse `$4E24 B5 E0 F0 08
            # D6 E0`), read by `_find_fixed_pitch_index` since its spelling.
            if d[j - 2] in (0x50, 0x70) and d[j] == 0xB5 and d[j + 2] == 0xF0                     and d[j + 4] == 0xD6 and d[j + 1] == d[j + 5]:
                handler.add(bytes(d[j + 1:j + 2]))
            i = d.find(head, i + 1)
        load = (f"A5 {addr:02X}" if zp
                else f"AD {addr & 0xFF:02X} {addr >> 8:02X}")
        stage = None
        for shape in (TWO_STAGE_SHAPE, TWO_STAGE_SHAPE_ZP, TWO_STAGE_SHAPE_ILV):
            k = search_file(d, shape.format(load=load))
            if k > -1:
                q = k + len(load.split())
                stage = bytes(d[q + 5:q + (6 if shape is TWO_STAGE_SHAPE_ZP
                                           else 7)])
                break
        assert stage in handler, p.name
        checked += 1
    # 43 -> 44: Mega_Apocalypse's zero-page `BIT $EC` handler, whose
    # countdown `$E0,X` is its two-stage counter too.
    assert checked == 44


@needs_corpus
@needs_rt
def test_the_original_plays_the_fixed_pitch_for_the_frame_count():
    """The measurement the emission rests on: Lightforce's first record-6
    note (voice 3, frame 897) is the played note, then `$09C4` for exactly
    the record's 4 frames, then the vibrato from the played note (the even
    onset; the odd onsets open differently, see the module docstring)."""
    out = subprocess.run([str(RT), str(CORPUS / "Lightforce.sid"), "-a0",
                          "-t20"], capture_output=True, text=True).stdout
    freq, cur = {}, "0000"
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 6 or not parts[1].strip().isdigit():
            continue
        f = parts[4].split()
        if f and f[0] != "....":
            cur = f[0]
        freq[int(parts[1])] = cur
    # 902 is the even onset's vibrato; the odd onset (953) opens 0504 at 958.
    assert [freq[n] for n in range(897, 903)] == [
        "04E2", "09C4", "09C4", "09C4", "09C4", "04D1"]
