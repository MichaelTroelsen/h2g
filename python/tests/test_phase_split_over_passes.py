"""`phase_split_over_passes`: bit $10's per-note phase clones where a pass would stand down.

Task arpeggio-step-phase-i-ball-shockway. `pitch_seq_phase_split_plan` gives each
bit-$10 record whose notes attack in more than one state of the global phase
counter a clone per minority state. On the outer-gated flat clocks it is
declined wherever the entry-instrument split or the free-note respell has work
(`build._phase_split_displaces_passes`), because both stand down beside any
phase split -- so I_Ball and Shockway_Rider kept one phase per record and their
octave steps sat 1-2 frames off the original's on every minority-phase note.

The option lets the split run anyway. The entry-instrument split then does not
run (Star_Paws); the free-note respell DOES, beside the split, on the phase
clones (task shockway-rider-pulse-phase-1-625-our: without it Shockway_Rider's
`pulse_phase` fell 1 -> .625, Saboteur_II's 1 -> .692, Pandora's 1 -> .533).
It is off by default and in `presets.json`: it is a trade the user adopts.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.convert import convert

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPLIT = "pitch phase split: "
STOOD_DOWN = SPLIT + "not splitting"


def _run(name, **extra):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    opts = F._preset_opts(doc, name)
    # The arms state the option themselves: presets.json carries it on
    # Shockway_Rider and Lightforce since v0.5.670, and "off" here means off.
    opts.pop("phase_split_over_passes", None)
    opts.update(extra)
    blob = convert(str(CORPUS / name), log=lines.append, **opts)
    return blob, lines


def _clones(lines):
    return [ln for ln in lines
            if ln.startswith(SPLIT) and "clone(s) [" in ln]


@needs_corpus
@pytest.mark.parametrize("name", ["I_Ball.sid", "Shockway_Rider.sid"])
def test_the_option_runs_the_split_the_free_note_respell_stood_down_for(name):
    off, off_log = _run(name)
    on, on_log = _run(name, phase_split_over_passes=True)
    assert any(ln.startswith(STOOD_DOWN) for ln in off_log), off_log
    assert not _clones(off_log), off_log
    assert any(ln.startswith("Free note (bit 7)") for ln in off_log), off_log
    assert not any(ln.startswith(STOOD_DOWN) for ln in on_log), on_log
    assert len(_clones(on_log)) == 1, on_log
    assert on != off


@needs_corpus
@pytest.mark.parametrize("name", ["I_Ball.sid", "Shockway_Rider.sid",
                                  "Star_Paws.sid"])
def test_the_option_off_is_the_default_byte_for_byte(name):
    default, _ = _run(name)
    explicit, _ = _run(name, phase_split_over_passes=False)
    assert default == explicit


@needs_corpus
@pytest.mark.parametrize("name", ["Trans-Atlantic_Balloon_Challenge.sid",
                                  "Flash_Gordon.sid", "W_A_R.sid",
                                  "Food_Feud.sid"])
def test_a_file_the_split_already_reaches_or_has_nothing_to_split_is_unmoved(
        name):
    """Trans-Atlantic splits with no pass in the way; Flash_Gordon and W_A_R
    stand down in the log but their notes attack in one state, so the plan is
    empty either way; Food_Feud's divided clock is not room-aware."""
    off, _ = _run(name)
    on, _ = _run(name, phase_split_over_passes=True)
    assert on == off


@needs_corpus
def test_the_option_reaches_the_planner_as_no_displacement_check(monkeypatch):
    """The seam: `displaces` is the check that declines the plan; the option
    is the only thing that removes it."""
    seen = []
    real = G.arpeggio.pitch_seq_phase_split_plan

    def spy(*args, **kw):
        seen.append(kw.get("displaces"))
        return real(*args, **kw)

    monkeypatch.setattr(G.arpeggio, "pitch_seq_phase_split_plan", spy)
    _run("I_Ball.sid")
    assert seen and all(callable(d) for d in seen), seen
    seen.clear()
    _run("I_Ball.sid", phase_split_over_passes=True)
    assert seen and all(d is None for d in seen), seen


def test_the_option_is_declared_per_song_and_never_a_default():
    import presets
    assert "phase_split_over_passes" in presets.EXCLUDED_FROM_ALWAYS
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert "phase_split_over_passes" not in doc["always"]


def _free_note(lines):
    return [ln for ln in lines if ln.startswith("Free note (bit 7)")]


@needs_corpus
@pytest.mark.parametrize("name", ["Shockway_Rider.sid", "Saboteur_II.sid",
                                  "Pandora.sid", "I_Ball.sid"])
def test_the_free_note_respell_runs_beside_the_phase_split(name):
    """The respell takes exactly the rows, variants and declines it takes with
    the split off: the phase clones are records of their own, so each is handed
    the start its record is. With the respell standing down the split's
    clones played the attack and the pulse reseed a flagged note skips, and
    the file's distinct pulse-open phases fell."""
    off, off_log = _run(name)
    on, on_log = _run(name, phase_split_over_passes=True)
    assert _free_note(off_log), off_log
    assert _clones(on_log), on_log
    assert _free_note(on_log) == _free_note(off_log), (off_log, on_log)


@needs_corpus
def test_the_instrument_table_holds_the_clones_and_the_variants():
    """Shockway_Rider: the split's 9 clones are appended to the table beside
    the respell's variants (a file with the respell standing down held the
    clones alone, 20 -> 29 records' worth of difference less the variants)."""
    import songview
    on, on_log = _run("Shockway_Rider.sid", phase_split_over_passes=True)
    off, _ = _run("Shockway_Rider.sid")
    clones = next(ln for ln in on_log if "clone(s) [" in ln)
    n = int(clones[len(SPLIT):].split(" ", 1)[0])
    assert n == 9, clones
    assert (len(songview.parse_sng(on).instruments)
            >= len(songview.parse_sng(off).instruments) + n)


@needs_corpus
def test_the_shipped_nineteen_conversion_runs_the_split():
    """User, 2026-11-19: Nineteen takes the option too (heard instr 95.6 ->
    97.8, pitch_cents .821 -> .848, tie_agreement .587 -> .608 against
    tie_ratio 1.103 -> 1.108 and loud_ratio 1.045 -> 1.049)."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    for name in ("Nineteen.sid", "Shockway_Rider.sid", "Lightforce.sid"):
        assert doc["songs"][name].get("phase_split_over_passes") is True, name
    import fidelity as F
    lines = []
    convert(str(CORPUS / "Nineteen.sid"), log=lines.append,
            **F._preset_opts(doc, "Nineteen.sid"))
    assert not any(ln.startswith(STOOD_DOWN) for ln in lines), lines
    assert _clones(lines), lines
