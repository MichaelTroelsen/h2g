"""`gate_off_firstwave_instruments`: the record's own waveform with the gate
CLEARED as a GT instrument's firstwave, instead of the testbit `$09`.

`player.s` mt_newnoteinit writes only `$D404` on the note-init call, and
`$09`'s gate bit opens every note one frame before the original
(tests/test_firstwave_gate_edge.py). The option changes that one byte per
named instrument and nothing else: the wavetable keeps the testbit's
lead-entry layout. What these tests pin:

- the byte (`gate_off_firstwave`), including the two record waveforms that
  cannot carry it and keep `$09`;
- off by default, and an empty list is byte-inert (Commando);
- naming instruments moves exactly their firstwave bytes, each to the
  real-firstwave byte with bit 0 cleared;
- forced on every instrument, the bytes that move are firstwave bytes only,
  and a legato tie clone keeps its gated byte (a gate-off frame on a held
  note is a drop the original never makes);
- `real_firstwave_instruments` / `no_test_restart` win where both apply;
- the preset and CLI readers forward it.

Corpus reach, measured when the option was added (6e467ff + this change,
-t 180, presets, every instrument 1..63 named): 89 converted, 6 refused,
77 moved -- the same 77 the env-toggled mirror moved at 3b1c66d
(corpus-firstwave-class-zero-frame). Historical; re-run the byte-hash.
"""
import json
import pathlib
import sys
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import FIRSTWAVE_TESTBIT                 # noqa: E402
from h2g.goatwriter.instruments import gate_off_firstwave    # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
EVERY = tuple(range(1, 64))


def _quiet(_m):
    pass


def _opts(name: str) -> dict:
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fidelity._preset_opts(doc, name)


def _firstwave_offsets(sng: bytes) -> list[int]:
    """Byte offsets of every instrument record's firstwave (+8 of 25)."""
    pos = songview.HEADER_LEN
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += sng[pos] + 2
    count = sng[pos]
    return [pos + 1 + k * 25 + 8 for k in range(count)]


def _diff(a: bytes, b: bytes) -> list[int]:
    assert len(a) == len(b), (len(a), len(b))
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


@pytest.mark.parametrize("waveform, want", [
    (0x41, 0x40), (0x81, 0x80), (0x11, 0x10), (0x15, 0x14), (0x43, 0x42),
    (0x40, 0x40), (0x89, 0x88),
    # No waveform selected: $00 would read as "no firstwave" (gplay.c:357)
    # and $08 is a different, test-bit byte -- both keep the testbit.
    (0x00, FIRSTWAVE_TESTBIT), (0x01, FIRSTWAVE_TESTBIT),
    (0x09, FIRSTWAVE_TESTBIT),
    # $FE is Goattracker's gate COMMAND, which writes no waveform.
    (0xFE, FIRSTWAVE_TESTBIT), (0xFF, FIRSTWAVE_TESTBIT),
])
def test_the_byte_is_the_waveform_with_the_gate_cleared(waveform, want):
    assert gate_off_firstwave(waveform) == want


def test_every_byte_it_returns_is_a_gate_clear_waveform_or_the_testbit():
    for w in range(256):
        fw = gate_off_firstwave(w)
        assert fw == FIRSTWAVE_TESTBIT or (
            fw == w & 0xFE and fw & 0xF0 and fw < 0xFE), (hex(w), hex(fw))


def test_off_by_default_and_an_empty_list_is_byte_inert_on_commando():
    sid = str(REPO_ROOT / "Commando.sid")
    ref = (REPO_ROOT / "Commando.sng").read_bytes()
    assert convert(sid, log=_quiet) == ref
    assert convert(sid, log=_quiet, gate_off_firstwave_instruments=()) == ref


@needs_corpus
def test_naming_two_instruments_moves_exactly_their_firstwave_bytes():
    """Confuzion's noise records, GT 2 and 4 under its preset."""
    opts = _opts("Confuzion.sid")
    sid = str(CORPUS / "Confuzion.sid")
    off = convert(sid, log=_quiet, **opts)
    on = convert(sid, log=_quiet,
                 **dict(opts, gate_off_firstwave_instruments=(2, 4)))
    real = convert(sid, log=_quiet,
                   **dict(opts, real_firstwave_instruments=(2, 4)))
    offs = _firstwave_offsets(off)
    assert offs == _firstwave_offsets(on) == _firstwave_offsets(real)
    moved = _diff(off, on)
    # GT numbers are 1-based and this preset writes no lead instrument
    # (`lead` 0), so GT 2 and 4 are records 1 and 3 -- and the preset's
    # drop_unnamed_instruments leaves numbers below them in place.
    assert moved == [offs[1], offs[3]], (moved, offs[:5])
    for o in moved:
        assert off[o] == FIRSTWAVE_TESTBIT
        assert on[o] == real[o] & 0xFE and real[o] & 0x01, (
            hex(on[o]), hex(real[o]))


@needs_corpus
@pytest.mark.parametrize("name", ["Action_Biker.sid", "Monty_on_the_Run.sid",
                                  "Delta.sid", "Star_Paws.sid"])
def test_forced_on_every_instrument_moves_only_firstwave_bytes(name):
    opts = _opts(name)
    sid = str(CORPUS / name)
    off = convert(sid, log=_quiet, **opts)
    on = convert(sid, log=_quiet,
                 **dict(opts, gate_off_firstwave_instruments=EVERY))
    offs = _firstwave_offsets(off)
    moved = _diff(off, on)
    assert moved, f"{name}: forcing the option moved nothing"
    assert set(moved) <= set(offs), sorted(set(moved) - set(offs))[:10]
    for o in moved:
        assert off[o] == FIRSTWAVE_TESTBIT and not on[o] & 0x01, (
            name, o, hex(off[o]), hex(on[o]))


@needs_corpus
@pytest.mark.parametrize("name", ["Delta.sid", "Star_Paws.sid",
                                  "Knucklebusters.sid"])
def test_a_legato_tie_clone_keeps_its_gated_firstwave(name):
    """A legato clone's byte is the record's waveform WITH the gate wherever
    its source would carry the testbit or a gate-off byte. The only legato
    record allowed to move is one whose byte was the testbit to begin with:
    the slip decoy, a copy of a held record that no note ever plays
    (note_passes.legato_slip_decoy)."""
    opts = _opts(name)
    sid = str(CORPUS / name)
    off = songview.parse_sng(convert(sid, log=_quiet, **opts)).instruments
    on = songview.parse_sng(convert(
        sid, log=_quiet,
        **dict(opts, gate_off_firstwave_instruments=EVERY))).instruments
    assert len(off) == len(on)
    clones = [(a, b) for a, b in zip(off, on)
              if a.gatetimer & 0x40 and a.firstwave != FIRSTWAVE_TESTBIT]
    assert clones, f"{name}: no legato clone to check"
    for a, b in clones:
        assert b.firstwave == a.firstwave and b.firstwave & 0x01, (
            name, hex(a.firstwave), hex(b.firstwave))


@needs_corpus
def test_the_real_firstwave_byte_wins_where_both_name_an_instrument():
    opts = _opts("Confuzion.sid")
    sid = str(CORPUS / "Confuzion.sid")
    real = convert(sid, log=_quiet,
                   **dict(opts, real_firstwave_instruments=(2, 4)))
    both = convert(sid, log=_quiet,
                   **dict(opts, real_firstwave_instruments=(2, 4),
                          gate_off_firstwave_instruments=(2, 4)))
    assert both == real


@needs_corpus
def test_no_test_restart_subsumes_it():
    """Tarzan's preset carries no_test_restart: every record already writes
    its gated waveform, so the gate-off list has nothing left to change."""
    opts = _opts("Tarzan.sid")
    assert opts["no_test_restart"] is True
    sid = str(CORPUS / "Tarzan.sid")
    assert convert(sid, log=_quiet, **opts) == convert(
        sid, log=_quiet, **dict(opts, gate_off_firstwave_instruments=EVERY))


def test_preset_opts_forwards_the_per_song_list_as_a_tuple():
    doc = {"always": {}, "songs": {
        "a.sid": {"gate_off_firstwave_instruments": [2, 4]}, "b.sid": {}}}
    assert fidelity._preset_opts(doc, "a.sid")[
        "gate_off_firstwave_instruments"] == (2, 4)
    assert fidelity._preset_opts(doc, "b.sid")[
        "gate_off_firstwave_instruments"] == ()


def _cli_kwargs(monkeypatch, tmp_path, argv):
    import h2g.cli as cli
    seen = {}

    def fake_convert(sid_path, log=None, **opts):
        seen.update(opts)
        return b"x"

    monkeypatch.setattr(cli, "convert", fake_convert)
    assert cli.main(argv + ["-q", "-o", str(tmp_path / "out.sng")]) == 0
    return seen


def test_the_cli_reads_the_preset_entry_and_its_flag_beats_it(monkeypatch,
                                                              tmp_path):
    doc = {"always": {}, "songs": {
        "a.sid": {"gate_off_firstwave_instruments": [2, 4]}}}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    sid = str(tmp_path / "a.sid")
    got = _cli_kwargs(monkeypatch, tmp_path, [sid, "--presets", str(path)])
    assert got["gate_off_firstwave_instruments"] == (2, 4)
    got = _cli_kwargs(monkeypatch, tmp_path,
                      [sid, "--presets", str(path), "--gate-off-firstwave=3"])
    assert got["gate_off_firstwave_instruments"] == (3,)
    got = _cli_kwargs(monkeypatch, tmp_path, [sid, "--gate-off-firstwave",
                                              "1,5,7"])
    assert got["gate_off_firstwave_instruments"] == (1, 5, 7)
    got = _cli_kwargs(monkeypatch, tmp_path, [sid])
    assert got["gate_off_firstwave_instruments"] == ()


@pytest.mark.parametrize("bad", ["0", "64", "x", ","])
def test_the_cli_refuses_a_bad_instrument_list(bad, tmp_path):
    import h2g.cli as cli
    with pytest.raises(SystemExit):
        cli.main([str(tmp_path / "a.sid"), "--gate-off-firstwave", bad])
