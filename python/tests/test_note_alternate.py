"""Effect bit $08's two-note alternation.

The other half of section 7.hhhh. Bit $02 alternates the *waveform* every
frame between the record's own `+2` and a per-instrument table; bit $08 is the
same alternation applied to the **note**, a second block on the same per-voice
counter 24 bytes further on (Flash Gordon `$139A`):

    139A  LDA effect / AND #$08 / BEQ out
    13A1  LDA counter,X / AND #$01 / BEQ alt
    13A8  LDA note,X                          ; odd  -> the played note
    13AB  JMP fetch
    13AE  alt: LDA alttbl,Y                   ; even -> a per-instrument one
    13B1  fetch: ASL / TAY
    13B3  LDA freqtbl,Y / STA freqlo,X / LDA freqtbl+1,Y / STA freqhi,X

All 80 corpus records that set bit $08 also set bit $02, so the two are one
shape and not two emitters: the frame that sounds the alternate waveform is
the frame that sounds the alternate pitch.

**Bit $08 is the pulse-width accumulator in another dialect**
(`Detection.pulse_lo_base`, Master of Magic `$C20F`). The two populations are
checked here to be disjoint -- a reading of a bit is only ever a reading of
one player, the lesson bit $02 taught against Warhawk's rise.
"""
import pathlib

import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import detect
from h2g.goatwriter import (_note_alternate_note, _wave_alternate_entries)
from h2g.sidfile import find_freq_table, load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Flash Gordon's record 3: `+2` is $10-ish, the bit-$02 alternate $81, and the
# alternate note index 67. $C7 is an absolute note byte -- `$80 + n` in the
# `.sng`, which `gt2reloc` packs as `n` (`greloc.c:1339-1341` inverts bit 7)
# and the packed player reads as an absolute note.
ALT_NOTE = 0xC7


def test_the_alternate_note_rides_the_alternate_waveform():
    """One counter, one branch, one phase.

    The observed phase from the attack frame is `note note alt note alt ...`:
    frame 0 is the init path, which skips both effect blocks, so the pair runs
    from frame 1 with the record's own half first. That is the shape bit $02
    already emits -- the lead, then the pair, looping to the first of it --
    and the note byte simply travels with the waveform it belongs to.
    """
    left, right = _wave_alternate_entries(0x41, 0x81, 1, start=10,
                                          alt_note=ALT_NOTE)
    assert left == [0x41, 0x41, 0x81, 0xFF]
    assert right == [0x00, 0x00, ALT_NOTE, 11]
    # The record's own half is `$00`, not `$80`, and that is what takes the
    # alternate pitch back off: `gt2reloc` packs every non-command right byte
    # as `b ^ $80`, so a `.sng` `$00` reaches the packed player as `$80` and
    # writes `adc mt_chnnote,x / and #$7f` -- the note's own pitch. A `$80`
    # here would be packed `$00`, no write at all, and the alternate would
    # simply stay for the rest of the note.
    assert right[1] == 0x00


def test_the_branch_swaps_both_halves_together():
    """`alt_first` is the other dialect's branch, and it moves the note too.

    Ninja's per-voice spelling falls through to the alternate rather than to
    the record's own. Whichever half is the alternate is the half that carries
    the alternate pitch; the two cannot come apart, because the player reads
    one counter bit for both blocks.
    """
    left, right = _wave_alternate_entries(0x41, 0x81, 1, start=10,
                                          alt_first=True, alt_note=ALT_NOTE)
    assert left == [0x41, 0x81, 0x41, 0xFF]
    assert right == [0x00, ALT_NOTE, 0x00, 11]


@pytest.mark.parametrize("multiplier,expect_left,expect_right", [
    (1, [0x41, 0x41, 0x81, 0xFF],
        [0x00, 0x00, ALT_NOTE, 11]),
    (2, [0x41, 0x41, 0x41, 0x41, 0x81, 0x81, 0xFF],
        [0x00, 0x00, 0x00, 0x00, ALT_NOTE, ALT_NOTE, 12]),
    (3, [0x41, 0x01, 0x41, 0x01, 0x81, 0x01, 0xFF],
        [0x00, 0x80, 0x00, 0x00, ALT_NOTE, ALT_NOTE, 12]),
    (4, [0x41, 0x02, 0x41, 0x02, 0x81, 0x02, 0xFF],
        [0x00, 0x80, 0x00, 0x00, ALT_NOTE, ALT_NOTE, 12]),
])
def test_the_rate_is_divided_by_the_multiplier(multiplier, expect_left,
                                               expect_right):
    """The alternation is one of the *player's* frames, which is `multiplier`
    play calls.

    So each half holds for `multiplier` calls -- one entry plus a repeat at
    `-S2` and a delay above it -- and **the delay entry carries this half's
    own note**. A delay's right side is read on its last call
    (gplay.c:697-723), which is the last call of the frame and the one siddump
    samples: `$00` there would put the played note back one call after the
    alternate was set, and the whole alternation would measure as flat. 18 of
    the 21 files carrying the block move bytes here and 13 of them pack above
    `-S1`, so this is the common case rather than the corner.
    """
    left, right = _wave_alternate_entries(0x41, 0x81, multiplier, start=10,
                                          budget=12, alt_note=ALT_NOTE)
    assert left == expect_left
    assert right == expect_right


@pytest.mark.parametrize("multiplier", [1, 2, 3, 4])
def test_no_alternate_note_leaves_the_bit_02_shape_untouched(multiplier):
    """The pin. A record that does not set bit $08 -- which is every record in
    62 of the 83 convertible files -- must emit exactly what it did before
    this existed.
    """
    plain = _wave_alternate_entries(0x41, 0x81, multiplier, start=10,
                                    budget=12)
    explicit = _wave_alternate_entries(0x41, 0x81, multiplier, start=10,
                                       budget=12, alt_note=None)
    assert plain == explicit
    assert plain is not None
    assert set(plain[1][:-1]) <= {0x00, 0x80}, "no absolute note anywhere"


@pytest.mark.parametrize("multiplier", [1, 2])
def test_a_coincident_pair_still_alternates_the_note(multiplier):
    """`alt == wave` is a statement about the *waveform*, and bit $08 is not.

    Where a record's `+2` and its bit-$02 alternate name the same waveform,
    the waveform alternation is a no-op and the pitch alternation is the whole
    of what the player does -- one counter, one `AND #$01 / BEQ`, one half
    sounding the pattern's note and the other the record's own index into the
    frequency table. The pair used to be declined outright, so the note was
    flat where the player sounds two.
    """
    pair = _wave_alternate_entries(0x81, 0x81, multiplier, start=10,
                                   budget=12, alt_note=ALT_NOTE)
    assert pair is not None
    left, right = pair
    # One waveform throughout, and the alternation lives entirely in the right
    # column: the played note on one half, the absolute note on the other.
    assert set(left[:-1]) == {0x81}
    assert left[-1] == 0xFF, "still terminated by a jump"
    assert ALT_NOTE in right[:-1]
    assert 0x00 in right[:-1], "the record's own half re-asserts the played note"


@pytest.mark.parametrize("multiplier", [1, 2])
def test_a_coincident_pair_without_bit_08_is_still_declined(multiplier):
    """The pin on the other side. With no alternate note there is genuinely
    nothing to alternate -- the entries would be N copies of one waveform
    playing one note -- so the refusal stands exactly as it did.
    """
    assert _wave_alternate_entries(0x81, 0x81, multiplier, start=10,
                                   budget=12) is None
    assert _wave_alternate_entries(0x81, 0x81, multiplier, start=10,
                                   budget=12, alt_note=None) is None


@pytest.mark.parametrize("alt,wave", [(0x00, 0x41), (0x0F, 0x41), (0x81, 0x00)])
def test_the_other_two_refusals_are_untouched_by_bit_08(alt, wave):
    """Only the `alt == wave` clause learned about `alt_note`.

    An alternate in the delay range is not a waveform at all, and a record
    with no waveform of its own has nothing to alternate *from* -- neither is
    made emittable by the presence of a note, and **neither occurs on any
    in-use corpus record that sets bit $08** (see the census below), so there
    is no evidence to widen them on.
    """
    assert _wave_alternate_entries(wave, alt, 1, start=10, budget=12,
                                   alt_note=ALT_NOTE) is None


@needs_corpus
def test_the_coincident_pair_is_one_record_in_one_file():
    """The reach, stated as a census rather than as a byte-hash.

    Of the 69 in-use records that set bit $08 and resolve a note, 68 have a
    bit-$02 pair that emits on its own terms. The 69th is
    Dragons_Lair_Part_II's record 24 -- `+2 $81`, alternate `$81`, effect
    `$0A`, note index `$20` -- and it is the only record corpus-wide where the
    pair declines. The other eleven bit-$08 records whose pair declines all
    sit **past** `det.instr_used`: dead table cells, which is why the corpus
    byte-hash for this change names exactly one file.
    """
    emitted, declined = 0, []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, lambda _m: None)
        if det.note_alternate < 0 or det.wave_alternate < 0:
            continue
        for i in range(max(det.instr_used, 0)):
            rec = det.instr_start + i * det.instr_stride
            if not sid.data[rec + 7] & 0x08:
                continue
            if _note_alternate_note(sid, det, i) is None:
                continue
            wave = sid.data[rec + 2]
            alt = sid.data[det.wave_alternate + i * det.instr_stride]
            if alt == wave:
                declined.append((path.stem, i, wave, alt))
            else:
                emitted += 1
    assert emitted == 68
    assert declined == [("Dragons_Lair_Part_II", 24, 0x81, 0x81)]


@needs_corpus
def test_the_coincident_record_is_played():
    """It is worth emitting because a pattern reaches it.

    A record past `instr_used` is a dead cell and correcting it would buy
    nothing. This one is GT instrument 25 (`i + 2` = `$1A` in its provenance
    stamp) and three pattern rows name it, in a pattern an orderlist reaches.

    **No column of `FIDELITY.md` can adjudicate the change**: it moves a noise
    instrument's *pitch*, which `nrun` (run lengths) and `melody` (the attack
    frame) are both blind to by construction, and the record sounds only in
    subtune 7 while the report traces one subtune -- one this file is already
    known to trace wrongly (15% on the diagonal, 60% at o9). The reach and
    this census are the evidence; a listening check is `[user]` work.
    """
    import json

    import fidelity
    import songview
    from h2g.convert import convert

    doc = json.loads((REPO_ROOT / "presets.json").read_text())
    name = "Dragons_Lair_Part_II.sid"
    song = songview.parse_sng(convert(str(CORPUS / name), log=lambda _m: None,
                                      **fidelity._preset_opts(doc, name)))
    assert len(song.instruments) >= 25
    # `i + 2` in hex, the provenance stamp `_write_instruments` writes.
    assert song.instruments[24].name.startswith("1A:"), song.instruments[24].name

    reached = {int(what[1:], 16)
               for track in song.tracks
               for kind, what, _n in songview.decode_orderlist(track)
               if kind == "pattern"}
    rows = [(pn, r // 4)
            for pn, patt in enumerate(song.patterns) if pn in reached
            for r in range(0, len(patt), 4) if patt[r + 1] == 25]
    assert rows, "record 24 is a dead cell after all -- re-read the census"
    assert len(rows) == 3

    left, right = zip(*song.tables["WTBL"][song.instruments[24].wave_ptr - 1:][:8])
    stop = left.index(0xFF)
    assert set(left[:stop]) == {0x81}, "one waveform"
    assert 0xA0 in right[:stop], "and an absolute note on one half of the pair"


def test_the_fixture_has_no_such_block():
    """Commando is not in the dialect, so nothing here can reach it -- which
    is what keeps the byte-exact fixture byte-exact.
    """
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, lambda _m: None)
    assert det.note_alternate == -1
    assert all(_note_alternate_note(sid, det, i) is None
               for i in range(max(det.instr_used, 0)))


# The files whose player carries the block, anchored on the player's own
# `LDA effect_byte`. 22 files match the bare byte shape; Powerplay Hockey is
# the one this declines, because it carries two copies of the player
# (section 7.iiiii) and the copy the block belongs to is not the one detection
# settled the instrument table on.
NOTE_ALT_FILES = {
    "Bangkok_Knights", "Chain_Reaction", "Deep_Strike", "Delta",
    "Delta_Mix-E-Load_loader", "Dragons_Lair_Part_II", "Flash_Gordon",
    "Food_Feud", "Knucklebusters", "Lightforce", "Nemesis_the_Warlock",
    "Nineteen", "Ricochet", "Saboteur_II", "Sanxion", "Tarzan",
    "Thundercats", "W_A_R", "W_A_R_Preview", "Wiz", "Zoolook",
}


@needs_corpus
def test_the_corpus_population_is_exactly_these_files():
    found, records, resolved = set(), 0, 0
    pulse_lo_too = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, lambda _m: None)
        if det.note_alternate < 0:
            continue
        found.add(path.stem)
        if det.pulse_lo_base >= 0:
            pulse_lo_too.add(path.stem)
        for i in range(max(det.instr_used, 0)):
            rec = det.instr_start + i * det.instr_stride
            if sid.data[rec + 7] & 0x08:
                records += 1
                resolved += _note_alternate_note(sid, det, i) is not None
    assert found == NOTE_ALT_FILES
    assert records == 80
    # 11 records name an index past the end of the frequency table -- all of
    # them the same boilerplate sound-effect record, whose index is 99 against
    # a 96-entry table. An index that is not a note is declined rather than
    # guessed at, the rule `_fixed_attack_note` already follows.
    #
    # It was 14 against a 95-entry *run* until the grid-edge clamp landed: a
    # table's last entry saturates at $FFFF rather than rising a full semitone
    # (63520 * 2**(1/12) = 67297, which does not fit), so the validated run
    # stops one short of the table it validates. `run` is still the semitone
    # run and is what the tie-breaks rank on; `length` is now the table.
    assert resolved == 69
    # A reading of a bit is a reading of one player: the accumulate dialect
    # reads the same bit as a pulse-width step and the two never coincide.
    assert pulse_lo_too == set()


@needs_corpus
def test_the_block_names_the_frequency_table_detection_finds():
    """The second reading that makes this a reading rather than an inference.

    The block loads its index and then indexes the player's own note table
    with it; `sidfile.find_freq_table` locates that table independently. If
    the two disagreed the byte would not be a note, so detection refuses --
    which is also what excludes Powerplay Hockey's second player.
    """
    for path in sorted(CORPUS.glob("*.sid")):
        if path.stem not in NOTE_ALT_FILES:
            continue
        sid = load_sid(str(path))
        det = detect(sid, lambda _m: None)
        assert det.note_alternate >= 0
        assert find_freq_table(sid) is not None, path.stem


@needs_corpus
def test_every_emitted_note_is_an_absolute_note_byte():
    """`$80 + n` in the `.sng` and never `$80` itself.

    `$80` is "keep the frequency" and would emit an alternation that does not
    alternate; the range this produces is `$81`-`$DF`, Goattracker's absolute
    notes C#0-B-7.
    """
    seen = 0
    for path in sorted(CORPUS.glob("*.sid")):
        if path.stem not in NOTE_ALT_FILES:
            continue
        sid = load_sid(str(path))
        det = detect(sid, lambda _m: None)
        for i in range(max(det.instr_used, 0)):
            note = _note_alternate_note(sid, det, i)
            if note is None:
                continue
            seen += 1
            assert 0x81 <= note <= 0xDF, (path.stem, i, hex(note))
    assert seen == 69
