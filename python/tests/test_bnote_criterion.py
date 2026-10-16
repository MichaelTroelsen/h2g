"""`fidelity_better`'s bnote term and the search's band-pass pass.

`sfx_drum_bandpass` restores the sfx drum's one frame of band-pass. On the five
files it moves (I_Ball, Nineteen, Pandora, Thundercats, Trans-Atlantic) it
LOSES on `band` (`passband_agree`, lag-aligned: 0.818 -> 0.734 on I_Ball) and
WINS on `bnote` (`passband_note_relative`, counted from each side's own last
attack: 0.000 -> 0.950 on I_Ball), so it was kept out of the search until a
term could read the second column.

What these tests pin is the shape of that term and of the pass that uses it:
guarded by `keeps_notes`, acceptance only (never a veto), silent where the
dimension is unmeasurable, and the pass asking only where `sfx_drum` won and
the flag moves bytes.
"""
import shutil

import pytest

import fidelity as F
import presets as P


def _state(melody=0.9, seq=0.9, attacks=100, noise=(0, 0, 0, 0), osc=1.0,
           onset=0.5, hold=0.5, gate=0.4, orig_attacks=100, pphase=1.0,
           bnote=None):
    return (melody, seq, attacks, noise, osc, onset, hold, gate,
            orig_attacks, pphase, bnote)


def test_a_better_bnote_wins_on_its_own():
    """I_Ball's figures: nothing else moves, the blips arrive."""
    assert P.fidelity_better(_state(bnote=0.95), _state(bnote=0.0))


def test_a_worse_or_equal_bnote_does_not():
    assert not P.fidelity_better(_state(bnote=0.30), _state(bnote=0.60))
    assert not P.fidelity_better(_state(bnote=0.60), _state(bnote=0.60))


def test_a_gain_inside_the_margin_does_not():
    assert not P.fidelity_better(_state(bnote=0.01), _state(bnote=0.0))


def test_unmeasurable_recommends_nothing():
    """None is "neither side has a band-pass frame": no blip to score."""
    assert not P.fidelity_better(_state(bnote=None), _state(bnote=None))
    assert not P.fidelity_better(_state(bnote=0.95), _state(bnote=None))
    assert not P.fidelity_better(_state(bnote=None), _state(bnote=0.0))


def test_a_state_from_before_the_term_recommends_nothing():
    old = _state()[:10]
    assert len(old) == 10
    assert not P.fidelity_better(_state(bnote=0.95), old)
    assert not P.fidelity_better(old, _state(bnote=0.0))


def test_it_is_guarded_by_the_attack_count():
    ref = _state(attacks=100, bnote=0.0)
    assert not P.fidelity_better(_state(attacks=80, bnote=0.95), ref)


def test_it_is_guarded_by_melody_and_sequence():
    ref = _state(bnote=0.0)
    assert not P.fidelity_better(_state(melody=0.5, bnote=0.95), ref)
    assert not P.fidelity_better(_state(seq=0.5, bnote=0.95), ref)


def test_it_is_acceptance_only_never_a_veto():
    """Another term's win is not cancelled by a lower bnote."""
    ref = _state(gate=0.40, bnote=0.9)
    cand = _state(gate=0.85, bnote=0.2)
    assert P.fidelity_better(cand, ref)


# ---------------------------------------------------------------------------
# The pass in tune_by_fidelity, driven by stubs (no emulation).

class _Run:
    """Stubs for one `tune_by_fidelity` call over a fake converter.

    The converter's bytes name the options that took effect, so two settings
    that "convert identically" really do hash alike, and the scorer reads the
    blob the packer was last given.
    """

    def __init__(self, tmp_path, monkeypatch, *, bp_moves_bytes=True,
                 drum_wins=True, bnote_on=0.95, bp_needs_drum=True):
        self.calls = []
        self.last = [b""]
        self.bnote_on = bnote_on

        def fake_convert(path, log=None, **opts):
            self.calls.append(dict(opts))
            drum = bool(opts.get("sfx_drum"))
            blob = b"base" + (b"+drum" if drum else b"")
            if (opts.get("sfx_drum_bandpass") and bp_moves_bytes
                    and (drum or not bp_needs_drum)):
                blob += b"+bp"
            return blob

        def fake_pack(blob, *a, **k):
            self.last[0] = blob
            return tmp_path / "p.sid"

        def noise(*a, **k):
            blob = self.last[0]
            return {"our_noise_frames": 500 if (b"+drum" in blob and
                                                drum_wins) else 0,
                    "orig_noise_frames": 1000}

        voices = [F.Voice(), F.Voice(), F.Voice()]
        stubs = {
            "make_workdir": lambda *a, **k: (tmp_path, False),
            "resolve_pair": lambda *a, **k: (0, 0, True),
            "calibration": lambda d: 0,
            "run_siddump": lambda *a, **k: voices,
            "pack_sid": fake_pack,
            "legalise_restarts": lambda b: (b, 0),
            "compare": lambda a, b: {"melody": 0.9, "sequence": 0.9},
            "wave_compare": noise,
            "startup_lag": lambda a, b: (0, 0),
            "pitch_motion_compare": lambda *a, **k: {"reversal_ratio": 1.0},
            "onset_agreement": lambda *a, **k: {"onset_frame_agreement": 0.5},
            "sound_run_agreement": lambda *a, **k: {
                "sound_run_agreement": 0.5},
            "gate_compare": lambda *a, **k: {"gate": 0.5},
            "pulse_compare": lambda *a, **k: {"pulse_phase": 1.0},
            "passband_note_relative": self._bnote,
        }
        for k, v in stubs.items():
            monkeypatch.setattr(F, k, v)
        monkeypatch.setattr(P, "convert", fake_convert)
        monkeypatch.setattr(P, "find_freq_table", lambda s: None)
        monkeypatch.setattr(P, "load_sid", lambda s: None)
        monkeypatch.setattr(P, "_noise_pitch", lambda *a, **k: 100)
        monkeypatch.setattr(shutil, "copyfile", lambda a, b: None)
        monkeypatch.setattr(P, "FIDELITY_TOGGLES", ("sfx_drum",))
        self.tmp = tmp_path

    def _bnote(self, *a, **k):
        return {"passband_note": self.bnote_on
                if b"+bp" in self.last[0] else 0.0}

    def go(self):
        return P.tune_by_fidelity(self.tmp / "x.sid", {}, 1, "siddump",
                                  "gt2reloc", 10, log=lambda m: None)


def test_the_pass_adopts_the_flag_where_it_moves_bytes_and_bnote(
        tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch)
    got = run.go()
    assert got.get("sfx_drum") is True
    assert got.get("sfx_drum_bandpass") is True


def test_the_pass_declines_where_bnote_does_not_improve(tmp_path, monkeypatch):
    run = _Run(tmp_path, monkeypatch, bnote_on=0.0)
    got = run.go()
    assert got.get("sfx_drum") is True
    assert "sfx_drum_bandpass" not in got


def test_the_pass_skips_a_flag_that_moves_no_byte(tmp_path, monkeypatch):
    """Identical bytes score identically: it must not be recorded."""
    run = _Run(tmp_path, monkeypatch, bp_moves_bytes=False)
    assert "sfx_drum_bandpass" not in run.go()


def test_the_pass_is_not_asked_without_sfx_drum(tmp_path, monkeypatch):
    """The flag needs the drum record; with no drum it is never converted.

    The fake converter is made to honour the flag even without a drum, so the
    byte-identity skip cannot be what keeps the search from asking.
    """
    run = _Run(tmp_path, monkeypatch, drum_wins=False, bp_needs_drum=False)
    got = run.go()
    assert "sfx_drum" not in got
    assert "sfx_drum_bandpass" not in got
    assert not any(c.get("sfx_drum_bandpass") for c in run.calls)


def test_everything_the_search_can_emit_is_re_derived_not_carried(
        tmp_path, monkeypatch):
    """`main` must not carry from the old artefact a key the search decides.

    A carried True would survive a search that said no. The keys the search can
    emit are the toggles plus the passes that follow the walk.
    """
    run = _Run(tmp_path, monkeypatch)
    got = run.go()
    assert set(got) <= set(P.FIDELITY_TOGGLES) | set(P.SEARCHED_AFTER_THE_WALK)
    for key in ("hard_restart_frames", "sfx_drum_bandpass"):
        assert key in P.SEARCHED_AFTER_THE_WALK
        assert key not in P.FIDELITY_TOGGLES
    # ...and it is still a per-song option the artefact may carry.
    assert "sfx_drum_bandpass" in P.CARRIED_PER_SONG


def test_the_flag_is_not_a_toggle():
    """Making it one doubles the walk to decide five songs."""
    assert "sfx_drum_bandpass" not in P.FIDELITY_TOGGLES
