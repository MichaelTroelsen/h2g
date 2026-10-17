"""`pitch_lead_tie`: a gated-firstwave note's init call sounds its own pitch.

Goattracker's new-note init writes `$D404` alone (player.s mt_newnoteinit,
`jmp mt_loadregswaveonly` at line 909), so a record whose firstwave is a gated
real waveform opens its first frame on the PREVIOUS note's frequency. Monty's
preset names every record 1-16 in `real_firstwave_instruments`, and its voice-2
drums ($08F8 / $0627) play E-5 for a frame where the original plays A-3. The
option ties the bare rest row before such a note to it (CMD_TONEPORTA $00,
player.s:410 "Speed $00 = tie note"), so the frequency is already there when
the gate opens (h2g.pitch_lead). Measured at 7e8c58d + the option, 50 s,
presets: of the 49 voice-2 drum attacks, the note siddump names on the attack
frame is the original's on 6 without the lead and 42 with it; the 7 left are
where the previous record's wavetable still writes a frequency on the tie row
(player.s:977 returns through mt_wavefreq, past the tie effect).

Own file: reads no shared fixture.
"""
import json
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.instrument_drop import _layout                      # noqa: E402
from h2g.goatwriter.appending import (_Song, _parse_song,  # noqa: E402
                                     _write_song)
from h2g.goatwriter.constants import HEADER_LEN               # noqa: E402
from h2g.patterns import MAX_PATTERNS                         # noqa: E402
from h2g.pitch_lead import (_last_row, _plays, _successions,  # noqa: E402
                            gated_firstwave_records, lead_ties, tie_row)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"
MONTY = "Auf_Wiedersehen_Monty.sid"
DRUM_ADSR = (0x08F8, 0x0627)
SECONDS = 50

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def _monty_opts() -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, MONTY)


def test_off_by_default_changes_no_byte():
    assert _quiet(COMMANDO, pitch_lead_tie=False) == _quiet(COMMANDO)


def test_inert_where_no_record_opens_gated():
    """Commando's records all open on the testbit `$09`: nothing to lead,
    so the fixture's bytes are untouched with the option on."""
    plain = _quiet(COMMANDO)
    instr_at = _layout(plain)[0]
    assert not gated_firstwave_records(plain, instr_at)
    assert _quiet(COMMANDO, pitch_lead_tie=True) == plain


def _played(song) -> list:
    """Per track: the (pattern, transpose) sequence its orderlist plays,
    once through and once more from the `RST` target (pitch_lead._plays)."""
    out = []
    for t in song.tracks:
        seq = []
        for _at, p, trans, times in _plays(t):
            seq.extend([(p, trans)] * times)
        out.append(seq)
    return out


def _check_leads(plain: bytes, got: bytes) -> dict:
    """Every invariant of a led file against its unled build: the same
    patterns play in the same order under the same transposes (a copy counts
    as its source); a changed row is only ever a command-free rest turned
    into a tie to the note after it, keeping its instrument byte; and every
    row-0 tie is the byte EVERY succession out of that copy asks for."""
    ps, gs = _parse_song(plain), _parse_song(got)
    gated = gated_firstwave_records(got, _layout(got)[0])
    n = len(ps.patterns)
    assert len(gs.patterns) <= MAX_PATTERNS
    source = {}
    for k, pat in enumerate(gs.patterns):
        if k < n:
            source[k] = k
            continue
        # A copy: a plain pattern whose every changed row was a tie row
        # turned into a tie, its last row among them.
        def copy_of(pq):
            diff = [r for r in range(0, len(pq), 4)
                    if pq[r:r + 4] != pat[r:r + 4]]
            return (len(pq) == len(pat) and diff
                    and all(tie_row(pq[r:r + 4]) and pat[r + 2] == 0x03
                            for r in diff)
                    and diff[-1] == 4 * _last_row(pq, 0, len(pq) // 4))
        hits = [q for q, pq in enumerate(ps.patterns) if copy_of(pq)]
        assert len(hits) == 1, f"pattern {k} copies {hits}"
        source[k] = hits[0]
    assert [[(source[p], t) for p, t in seq] for seq in _played(gs)]         == _played(ps)
    stats = {"in": 0, "across": 0, "copies": len(gs.patterns) - n}
    for k, pat in enumerate(gs.patterns):
        base = ps.patterns[source[k]]
        rows = len(pat) // 4
        for r in range(rows):
            old, cur = base[r * 4:r * 4 + 4], pat[r * 4:r * 4 + 4]
            if old == cur:
                continue
            assert tie_row(old) and r >= 1, (k, r, old)
            assert cur[1:] == bytes((old[1], 0x03, 0x00)), (k, r, cur)
            if r + 1 < rows and pat[(r + 1) * 4] != 0xFF:
                assert cur[0] == pat[(r + 1) * 4]
                stats["in"] += k < n      # a copy repeats its source's
                continue
            stats["across"] += 1
            outs = [(tq, p, tp) for q, tq, p, tp in _successions(got, len(gs.patterns))
                    if q == k]
            assert outs, f"pattern {k}'s end tie leads nothing"
            for tq, p, tp in outs:
                assert cur[0] + tq == gs.patterns[p][0] + tp, (k, p)
    return stats


@needs_corpus
def test_every_changed_row_is_a_tie_to_the_note_it_leads():
    opts = _monty_opts()
    plain = _quiet(CORPUS / MONTY, **opts)
    got = _quiet(CORPUS / MONTY, **dict(opts, pitch_lead_tie=True))
    assert lead_ties(plain)[0] == got
    stats = _check_leads(plain, got)
    assert stats["in"] > 0 and stats["across"] > 0 and stats["copies"] > 0
    # Each tie counted once: a copy's in-pattern ties are its source's.
    assert stats["in"] + stats["across"] == lead_ties(plain)[1]


def _unled_row0(blob: bytes) -> list:
    """Successions into a gated row-0 note the tie could have led and did
    not: the pattern before ends on a command-free rest."""
    song = _parse_song(blob)
    gated = gated_firstwave_records(blob, _layout(blob)[0])
    out = []
    for q, tq, p, tp in _successions(blob, len(song.patterns)):
        pq, pp = song.patterns[q], song.patterns[p]
        last = _last_row(pq, 0, len(pq) // 4)
        named = [i for i in pq[1:(last + 1) * 4:4] if i]
        ins = pp[1] or (named[-1] if named else None)
        if 0x60 <= pp[0] < 0xBD and ins in gated and pp[2] != 0x03                 and last >= 1 and tie_row(pq[last * 4:last * 4 + 4])                 and 0x60 <= pp[0] + tp - tq < 0xBD:
            out.append((q, tq, p, tp))
    return out


@needs_corpus
def test_monty_every_row0_drum_is_led():
    """Monty's residue after the in-place row-0 lead was 26 patterns followed
    by different row-0 notes and a repeat (voice 2, `$D7 02`: pattern 2 eight
    times, ending `BD 17 00 00`) into its own row-0 drum (the 0:38 hit). The
    copies and the split lead every one, within MAX_PATTERNS."""
    opts = _monty_opts()
    plain = _quiet(CORPUS / MONTY, **opts)
    got = _quiet(CORPUS / MONTY, **dict(opts, pitch_lead_tie=True))
    assert len(_unled_row0(plain)) > 100
    assert _unled_row0(got) == []
    assert _layout(got)[2] and got[_layout(got)[2]] <= MAX_PATTERNS


def _song(tracks, patterns) -> bytes:
    """A one-subtune GTS5 song with one record opening on gated triangle."""
    rec = bytearray(25)
    rec[8] = 0x11                     # firstwave: triangle, gate set
    return _write_song(_Song(b"GTS5", b"GTS5" + bytes(HEADER_LEN - 4),
                             [bytes(t) for t in tracks], [rec],
                             [[], [], [], []],
                             [bytearray(sum(p, [])) for p in patterns]))


END = [0xFF, 0, 0, 0]
REST = [0xBD, 0, 0, 0]


def test_copies_lead_each_successor_with_its_own_byte():
    """Pattern 0 is followed by pattern 1 (row 0 $74) and pattern 2 ($77):
    one shared last row cannot tie to both, so a copy takes one. Patterns 1
    and 2 are each followed by pattern 0 (voice 1) and by themselves (the
    loops of voices 2 and 3), so each needs a copy too: three in all."""
    pats = [[[0x70, 1, 0, 0], REST, END], [[0x74, 1, 0, 0], REST, END],
            [[0x77, 1, 0, 0], REST, END]]
    plain = _song([[0, 1, 0, 2, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]], pats)
    got, led = lead_ties(plain)
    stats = _check_leads(plain, got)
    assert stats["copies"] == 3 and led == 6
    assert _unled_row0(got) == []


def test_a_repeat_into_itself_is_split_before_its_exit():
    """`$D2 00 01`: pattern 0 three times, then pattern 1. Its plays into
    itself want $70, its exit $74; the split `$D1 00 00` gives the last play
    an entry of its own, and the `RST` target moves past the inserted byte."""
    pats = [[[0x70, 1, 0, 0], REST, END], [[0x74, 1, 0, 0], REST, END]]
    plain = _song([[0xD2, 0, 1, 0xFF, 2], [1, 0xFF, 0], [1, 0xFF, 0]], pats)
    got, _led = lead_ties(plain)
    _check_leads(plain, got)
    assert _unled_row0(got) == []
    track = _parse_song(got).tracks[0]
    assert track[0] == 0xD1 and len(track) == 6 and track[-1] == 3


def test_no_pattern_number_left_declines_and_keeps_the_original_bare():
    pats = [[[0x70, 1, 0, 0], REST, END], [[0x74, 1, 0, 0], REST, END],
            [[0x77, 1, 0, 0], REST, END]]
    plain = _song([[0, 1, 0, 2, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]], pats)
    got, _led = lead_ties(plain, max_patterns=3)
    _check_leads(plain, got)
    song = _parse_song(got)
    assert len(song.patterns) == 3
    assert bytes(song.patterns[0][4:8]) == bytes(REST)


def _drum_attacks(trace) -> list[tuple[int, str]]:
    """(frame, note siddump names) for each voice-2 attack on a drum ADSR."""
    v = trace[1]
    n = SECONDS * 50
    adsr = fidelity.register_timeline(v.adsr_events, n)
    return [(f, name) for f, name in zip(v.attack_frames, v.attacks)
            if 0 < f < n and adsr[f] in DRUM_ADSR]


def _ours(sng: bytes, tmp: pathlib.Path):
    sng, _ = fidelity.legalise_restarts(sng)
    packed = fidelity.pack_sid(sng, tmp, fidelity.GT2RELOC, 1)
    assert packed is not None, "gt2reloc wrote no .sid"
    return _drum_attacks(fidelity.run_siddump(packed, SECONDS, 0,
                                              fidelity.SIDDUMP))


@needs_corpus
@needs_tools
def test_monty_voice2_drums_open_on_their_own_pitch(tmp_path):
    opts = _monty_opts()
    sid = CORPUS / MONTY
    sub = fidelity.resolve_pair(sid, "auto")[0]
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = _drum_attacks(fidelity.run_siddump(local, SECONDS, sub,
                                              fidelity.SIDDUMP, cal))
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    plain = _ours(_quiet(sid, **opts), tmp_path / "a")
    led = _ours(_quiet(sid, **dict(opts, pitch_lead_tie=True)), tmp_path / "b")
    # Same strikes on the same frames: the tie moves no gate edge.
    assert [f for f, _ in plain] == [f for f, _ in led]
    assert len(orig) >= 30
    k = min(len(orig), len(led))
    want = [name for _, name in orig[:k]]
    right_plain = sum(a == b for a, (_, b) in zip(want, plain[:k]))
    right_led = sum(a == b for a, (_, b) in zip(want, led[:k]))
    # The note siddump names on the attack frame is the original's drum note
    # on 42 of 49 strikes with the lead and on 6 without it (measured).
    assert right_plain <= 10, (right_plain, k)
    assert right_led >= 40, (right_led, k)


@needs_corpus
@needs_tools
def test_monty_038_drum_opens_on_its_own_pitch(tmp_path):
    """The hit the user flagged: voice index 2 at 0:38, the original's frame
    1937 (E-2). Under the in-place row-0 lead it still opened on the hit
    before's D-3: it is the row-0 drum of a play of pattern 2 inside
    `$D7 02`, whose last row `BD 17 00 00` names an instrument. With the
    repeat split and the instrument-keeping tie row it opens on E-2."""
    opts = _monty_opts()
    sid = CORPUS / MONTY
    sub = fidelity.resolve_pair(sid, "auto")[0]
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = fidelity.run_siddump(local, 40, sub, fidelity.SIDDUMP, cal)
    want = dict(zip(orig[2].attack_frames, orig[2].attacks))[1937]
    names = []
    for k, extra in enumerate(({}, {"pitch_lead_tie": True})):
        sng, _ = fidelity.legalise_restarts(_quiet(sid, **dict(opts, **extra)))
        (tmp_path / str(k)).mkdir()
        packed = fidelity.pack_sid(sng, tmp_path / str(k), fidelity.GT2RELOC, 1)
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = fidelity.run_siddump(packed, 40, 0, fidelity.SIDDUMP)
        lag = fidelity.startup_lag(orig, ours)[0]
        got = dict(zip(ours[2].attack_frames, ours[2].attacks))
        names.append(next(got[f] for f in (1937 + lag, 1938 + lag,
                                           1936 + lag) if f in got))
    assert want == "E-2"
    assert names == ["D-3", "E-2"], names
