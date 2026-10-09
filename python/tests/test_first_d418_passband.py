"""The passband the classic filter runs under is not the drum's one-frame write.

Seven files (I_Ball, IK_plus, Nineteen, Pandora, Star_Paws, Thundercats,
Trans-Atlantic) read their passband from the first `LDA #imm / STA $D418` in
the file. In all seven that write is a voice-3 drum's: `LDA #$60 / STA $D416 /
LDA #$2F / STA $D418` for one frame, restored to `$1F` by the same block's
`LDY #$1F / STY $D418` on the next frame (disassembly at
`detect.FILTER_EFFECT_CUTOFF_SHAPE`). The subtune init writes `$1F` as well.
On those seven originals 83-88% of the routed frames are lowpass (-t 180,
v0.5.516), and the conversion filtered every one of them in bandpass.

`detect._filter_mode_write` passes over a mode write that comes with its own
immediate cutoff, and it keeps the first match where every match is one. The
held After_8 and Rikky are such files; neither enables a record, so neither
moves a byte.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import _detect_tables, convert
from h2g.detect import (FILTER_EFFECT_CUTOFF_SHAPE, FILTER_MODE_SHAPE,
                        _filter_mode_write)
from h2g.goatwriter import FILT_SET_PARAMS, FILT_STOP
from h2g.search import match_at, search_file
from h2g.sidfile import load_sid

REPO = Path(__file__).resolve().parents[2]

SEVEN = ["I_Ball", "IK_plus", "Nineteen", "Pandora", "Star_Paws",
         "Thundercats", "Trans-Atlantic_Balloon_Challenge"]

# `LDY #imm / STY $D418`: the drum block's restore, on every frame after its
# first. It is read here only as a second, independent witness.
RESTORE_SHAPE = "A0 ?? 8C 18 D4"


def _read(stem):
    return _detect_tables(load_sid(str(CORPUS / f"{stem}.sid")), lambda m: None)


# --- synthetic: the rule itself ---------------------------------------------

DRUM = "A9 60 8D 16 D4 A9 2F 8D 18 D4"
INIT = "A9 1F 8D 18 D4"


def _blob(*parts):
    return bytes.fromhex(" ".join(("EA",) * 3 + parts + ("60",)))


def test_a_drum_write_is_passed_over_for_the_next():
    """SABOTAGE TARGET: drop the skip in `_filter_mode_write` and the drum's
    $2F is what it returns."""
    data = _blob(DRUM, "EA EA", INIT)
    j = _filter_mode_write(data)
    assert data[j + 1] == 0x1F, hex(data[j + 1])


def test_two_drum_writes_are_both_passed_over():
    data = _blob(DRUM, DRUM, "EA", INIT)
    assert data[_filter_mode_write(data) + 1] == 0x1F


def test_a_file_with_only_the_drum_keeps_it():
    """SABOTAGE TARGET: return -1 instead of the first match and a file
    whose only mode write is the drum's loses the passband it reads today."""
    data = _blob(DRUM)
    assert _filter_mode_write(data) == search_file(data, FILTER_MODE_SHAPE)


def test_a_cutoff_from_memory_is_not_an_effects():
    """SABOTAGE TARGET: wildcard the immediate load (`?? ?? ?? 8D 16 D4`)
    and the sweep's own `LDA cutoff,X / STA $D416` in front of a mode write
    would be passed over too. Only a FIXED cutoff marks the effect."""
    data = _blob("BD 7B C4 8D 16 D4 A9 2F 8D 18 D4", "EA", INIT)
    assert data[_filter_mode_write(data) + 1] == 0x2F


def test_the_first_match_unchanged_when_it_is_not_the_drums():
    data = _blob(INIT, "EA", DRUM)
    assert _filter_mode_write(data) == search_file(data, FILTER_MODE_SHAPE)


# --- the corpus --------------------------------------------------------------

@needs_corpus
def test_the_rule_reaches_exactly_these_files():
    """Which files have the drum write as their first mode write, and which of
    those the rule moves to another write. The two held files have no other
    `LDA #imm / STA $D418` to move to."""
    first_is_drum, moved = set(), set()
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _read(p.stem)
        except Exception:                                   # noqa: BLE001
            continue
        if det.filter is None:
            continue
        j = search_file(sid.data, FILTER_MODE_SHAPE)
        if match_at(sid.data, j - 5, FILTER_EFFECT_CUTOFF_SHAPE):
            first_is_drum.add(p.stem)
        if _filter_mode_write(sid.data) != j:
            moved.add(p.stem)
    assert moved == set(SEVEN), moved
    assert first_is_drum == set(SEVEN) | {"After_8", "Rikky"}, first_is_drum


@needs_corpus
@pytest.mark.parametrize("stem", SEVEN)
def test_the_seven_read_lowpass(stem):
    """SABOTAGE TARGET: the reading itself. The drum's restore, searched for
    behind the drum write, names the same passband as the chosen write. That
    is the player saying which passband it returns to."""
    sid, det = _read(stem)
    f = det.filter
    assert f is not None and f.passband == 0x10, f
    d = sid.data
    drum = search_file(d, FILTER_MODE_SHAPE)
    assert d[drum + 1] & 0x70 == 0x20
    window = d[max(0, drum - 48):drum]
    # search_file never tests offset 0, so pad by one: the match's offset in
    # the padded buffer is the LDY's + 1, which is the immediate's offset.
    r = search_file(b"\0" + window, RESTORE_SHAPE)
    assert r > -1, stem
    assert window[r] & 0x70 == f.passband


@needs_corpus
@pytest.mark.parametrize("stem", ["After_8", "Rikky"])
def test_the_held_drum_only_files_keep_their_reading(stem):
    _sid, det = _read(stem)
    assert det.filter is not None and det.filter.passband == 0x20


@needs_corpus
@pytest.mark.parametrize("stem", SEVEN)
def test_the_conversion_sets_lowpass(stem):
    """At the seam: under the shipped presets every routed SET_PARAMS row of
    the converted FTBL selects lowpass, and none selects bandpass."""
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                   **F._preset_opts(doc, f"{stem}.sid"))
    ftbl = parse_sng(blob).tables["FTBL"]
    params = [left for left, right in ftbl
              if FILT_SET_PARAMS <= left < FILT_STOP and right & 0x07]
    assert params, ftbl
    assert all(left & 0x70 == 0x10 for left in params), ftbl


def test_commando_is_untouched():
    ref = (REPO / "Commando.sng").read_bytes()
    assert convert(str(REPO / "Commando.sid"), log=lambda m: None,
                   filters=True) == ref
