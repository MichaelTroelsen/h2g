"""A waveform-$00 record under `gate_off_firstwave` parks its voice at `$00`.

`gate_off_firstwave` gives a record that selects no waveform the free-running
`$01` (FIRSTWAVE_FREERUN). The plain wavetable block then writes no waveform
(entry 0 is `$00`, "no change"), so the voice HOLDS `$01` -- gate ON, nothing
selected -- where the original writes `$00`. Nemesis_the_Warlock voice 0
(record 15, all zero, the subtune's starting instrument) is parked for 1130
frames: 61% of its `gate` misses were ours-`$01` over the original's `$00`
(C:/t/corpus-gate-column-sub99-mechanisms/plan.md M7).

`goatwriter.instruments.park_free_running` rewrites that block's entry 0 to
`$E0` (Goattracker's silent waveform `$00`). What is pinned:

- the rewrite lands on Nemesis' record, and only under the adopter list;
- it is exactly the plain five-entry block, nothing else;
- the firstwave stays `$01` (the oscillator keeps running through the init
  call; the test bit would freeze it -- Sanxion's gain).

Corpus reach at the change (-t 180 byte-hash, presets, 89 converted, 0
refused): 5 moved -- Dragons_Lair_Part_II, Geoff_Capes_Strongman_Challenge,
Nemesis_the_Warlock, Radio_ACE, Sanxion. Historical; re-run the byte-hash.
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
from h2g.goatwriter import FIRSTWAVE_FREERUN, instruments    # noqa: E402
from h2g.goatwriter.constants import WAVE_SILENT_BASE        # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
PLAIN = [(0x00, 0x00), (0x01, 0x00), (0x01, 0x00), (0xFF, 0x00), (0xFF, 0x00)]


def _quiet(_m):
    pass


def _opts(name: str, adopt: bool) -> dict:
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = fidelity._preset_opts(doc, name)
    if not adopt:
        opts.pop("gate_off_firstwave_instruments", None)
    elif not opts.get("gate_off_firstwave_instruments"):
        pytest.skip(f"{name} does not carry gate_off_firstwave")
    return opts


def _zero_records(sng: bytes) -> list:
    """(wave block, firstwave) of every record with AD = SR = 0 and firstwave
    $01 -- Nemesis' record 15."""
    song = songview.parse_sng(sng)
    out = []
    for ins in song.instruments:
        if ins.firstwave == FIRSTWAVE_FREERUN and ins.ad == 0 and ins.sr == 0:
            at = ins.wave_ptr - 1
            out.append((song.tables["WTBL"][at:at + 5], ins.firstwave))
    return out


@needs_corpus
def test_nemesis_zero_record_writes_silent_wave_zero_under_the_adopter_list():
    sng = convert(str(CORPUS / "Nemesis_the_Warlock.sid"), log=_quiet,
                  **_opts("Nemesis_the_Warlock.sid", adopt=True))
    got = _zero_records(sng)
    assert got, "no free-running zero record found"
    for block, firstwave in got:
        assert block == [(WAVE_SILENT_BASE, 0x00)] + PLAIN[1:], block
        assert firstwave == FIRSTWAVE_FREERUN


@needs_corpus
def test_without_the_adopter_list_the_block_is_the_plain_one():
    sng = convert(str(CORPUS / "Nemesis_the_Warlock.sid"), log=_quiet,
                  **_opts("Nemesis_the_Warlock.sid", adopt=False))
    song = songview.parse_sng(sng)
    zero = [i for i in song.instruments if i.ad == 0 and i.sr == 0
            and i.wave_ptr]
    assert zero
    blocks = [song.tables["WTBL"][i.wave_ptr - 1:i.wave_ptr + 4] for i in zero]
    assert PLAIN in blocks, blocks


def test_only_the_plain_block_is_rewritten():
    class Sid:
        data = bytes(64)

    class Det:
        instr_start = 0
        instr_stride = 8
        effect_bit80 = False

    entries = [(0x09, 0x00)] + PLAIN
    starts = [1, 2]                      # lead instrument 0, record at entry 2
    # the plain block is rewritten ...
    done = instruments.park_free_running(Sid, Det, 2, list(entries), starts,
                                         1, (2,))
    assert done == [2]
    # ... a record the adopter list does not name is not ...
    e = list(entries)
    assert instruments.park_free_running(Sid, Det, 2, e, starts, 1,
                                         (3,)) == []
    assert e == entries
    # ... nor is one whose block is not the plain shape ...
    e = list(entries)
    e[2] = (0x41, 0x00)
    assert instruments.park_free_running(Sid, Det, 2, e, starts, 1,
                                         (2,)) == []
    # ... nor a record whose firstwave is written instead of the test bit
    e = list(entries)
    assert instruments.park_free_running(
        Sid, Det, 2, e, starts, 1, (2,), no_test_restart=True) == []
    assert e == entries


SCALED = [(0x00, 0x00), (0x00, 0x00), (0x01, 0x00), (0xFF, 0x00), (0xFF, 0x00)]


def test_the_multiplier_scaled_plain_block_is_rewritten_too():
    """Lightforce (-S2) instrument 22: the two middle delays are scaled, so the
    block is not the -S1 spelling, yet it is the same plain block and the voice
    held `$01` over the original's `$00` (gate .9393)."""
    class Sid:
        data = bytes(64)

    class Det:
        instr_start = 0
        instr_stride = 8
        effect_bit80 = False

    entries = [(0x09, 0x00)] + SCALED
    e = list(entries)
    assert instruments.park_free_running(Sid, Det, 2, e, [1, 2], 1,
                                         (2,)) == [2]
    assert e[1] == (WAVE_SILENT_BASE, 0x00) and e[2:] == SCALED[1:]
    # a block with a real waveform byte in a middle slot is not plain
    e = list(entries)
    e[3] = (0x41, 0x00)
    assert instruments.park_free_running(Sid, Det, 2, e, [1, 2], 1,
                                         (2,)) == []
    # nor one whose middle entry carries a right-hand byte
    e = list(entries)
    e[3] = (0x01, 0x05)
    assert instruments.park_free_running(Sid, Det, 2, e, [1, 2], 1,
                                         (2,)) == []
