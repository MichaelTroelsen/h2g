"""`hold` must not read a TEST-bit frame as a sounding waveform.

Trans-Atlantic_Balloon_Challenge: original `11 11 11 11 11 0 0 ...`, ours
`11 11 11 11 11 18 18 ...`; `$18` is triangle + TEST, which is silent.
"""
import fidelity


def _voices(release_byte, n=6, slot=12, held=5):
    wf, at = [], []
    for i in range(n + 1):
        a = i * slot
        at.append(a)
        wf += [(a, 0x11), (a + held, release_byte)]
    return [fidelity.Voice(wf_events=wf, adsr_events=[(0, 0x0AF8)],
                           attack_frames=at),
            fidelity.Voice(), fidelity.Voice()]


def _hold(orig_release, our_release):
    return fidelity.sound_run_agreement(
        _voices(orig_release), _voices(our_release), 200)


def test_a_test_bit_frame_is_not_a_sounding_waveform():
    assert fidelity._selects_waveform(0x11)
    assert not fidelity._selects_waveform(0x18)
    assert not fidelity._selects_waveform(0x58)
    got = _hold(0x00, 0x18)          # original silent, ours triangle+TEST
    assert got["sound_run_instruments"] == 1
    assert got["sound_run_agreement"] == 1.0


def test_a_real_waveform_after_the_held_frames_still_differs():
    got = _hold(0x00, 0x10)          # ours keeps sounding triangle
    assert got["sound_run_agreement"] == 0.0


def test_a_gate_set_test_frame_still_counts():
    """`$89` (noise + TEST + gate) is ours' note-opening frame on Go_Go_Dash
    and Pacific_Coast; excluding it dropped both from hold 1.000."""
    assert fidelity._selects_waveform(0x89)
    assert fidelity._selects_waveform(0xFF)
    got = _hold(0x81, 0x89)
    assert got["sound_run_agreement"] == 1.0
