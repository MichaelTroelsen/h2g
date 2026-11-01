"""`listen.forced_pal_flags`: an NTSC-flagged PSID is rendered at the PAL clock.

Kings_of_the_Beach_ingame (PSID v2, flags 0x0018) was rendered by sidplayfp at
60 Hz and our packed .sid, which says PAL, at 50: `aud` 0.734, the corpus
minimum, with the original's WAV silent from 5.98 s and ours sounding to 7.2 s
-- the clock mismatch, not a timbre difference (forced to the PAL clock the
same pair reads 0.926).
"""
import hashlib
import types

import listen as L
import sound


def _hdr(magic=b"PSID", version=2, flags=0x0014):
    h = bytearray(0x7C)
    h[0:4] = magic
    h[4:6] = version.to_bytes(2, "big")
    h[0x76:0x78] = flags.to_bytes(2, "big")
    return bytes(h) + b"\0\0\x60\x00"


def test_only_a_psid_that_says_ntsc_only_is_forced(tmp_path):
    """SABOTAGE TARGET: widen the test to `clock != 1` and the RSID / both-
    clocks cases fail; drop it and the NTSC case fails."""
    def flags_of(**kw):
        p = tmp_path / "t.sid"
        p.write_bytes(_hdr(**kw))
        return L.forced_pal_flags(p)
    assert flags_of(flags=0x0018) == ["-vpf"]                  # NTSC
    assert flags_of(flags=0x0014) == []                        # PAL
    assert flags_of(flags=0x001C) == []                        # both
    assert flags_of(flags=0x0010) == []                        # unknown
    assert flags_of(magic=b"RSID", flags=0x0018) == []         # own interrupt
    assert flags_of(version=1, flags=0x0018) == []             # v1 has no flags
    (tmp_path / "short.sid").write_bytes(b"PSID")
    assert L.forced_pal_flags(tmp_path / "short.sid") == []
    assert L.forced_pal_flags(tmp_path / "missing.sid") == []


def test_render_command_line_carries_the_clock_pin(monkeypatch, tmp_path):
    seen = []

    def fake_run(argv, **kw):
        seen.append(list(argv))
        (tmp_path / "out.wav").write_bytes(b"\0" * (L.EMPTY_WAV + 1))
        return types.SimpleNamespace(returncode=0)
    monkeypatch.setattr(L.subprocess, "run", fake_run)
    for name, flags, want in (("ntsc", 0x0018, True), ("pal", 0x0014, False)):
        sid = tmp_path / f"{name}.sid"
        sid.write_bytes(_hdr(flags=flags))
        assert L.render_sidplayfp(sid, tmp_path / "out.wav", 3, 0,
                                  exe="sidplayfp.exe")
        assert ("-vpf" in seen[-1]) is want, seen[-1]


def test_cache_key_changes_only_for_the_pinned_files(tmp_path):
    """A pinned render must not be served from a key made before the pin; an
    unpinned file's key must be exactly what it was."""
    def old_key(path):
        h = hashlib.sha1(path.read_bytes())
        h.update(b"\0sidplayfp-delay=%d" % L.SIDPLAYFP_POWER_ON_DELAY)
        return h.hexdigest()[:12]
    ntsc, pal = tmp_path / "n.sid", tmp_path / "p.sid"
    ntsc.write_bytes(_hdr(flags=0x0018))
    pal.write_bytes(_hdr(flags=0x0014))
    assert sound.content_key(pal) == old_key(pal)
    assert sound.content_key(ntsc) != old_key(ntsc)
