"""Dragons_Lair_Part_II packs at the clock of the song its init starts.

Its init sends PSID 0 (the header's startSong) to song 9, whose row is 2
frames x 4/3 = 8/3; the table entry for index 0 reads 5/2.  `pack_subtune`
used to take index 0, so the file was packed at -S2 (row 5/2) and the tune
everyone hears ran 6.25% fast (`--pace`: drift -62.50 per 1000).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import tempo as T  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402


@needs_corpus
def test_dragons_lair_start_subtune_packs_at_song_9s_clock():
    sid = load_sid(CORPUS / "Dragons_Lair_Part_II.sid")
    sp = T.find_song_speeds(sid)
    assert sp.song_of[0] == 9 and sp.song_of[1] == 7
    assert (sp.frames_for(9), sp.skip_for(9)) == (2, 3)
    assert T.pack_subtune(sp, sid.start_song) == 9
    assert T.file_multiplier(sid, sp, skip_gate=True) == 3


@needs_corpus
def test_players_whose_init_passes_the_subtune_through_are_untouched():
    for name in ("Bangkok_Knights", "Kings_of_the_Beach_ingame", "Rasputin"):
        sid = load_sid(CORPUS / f"{name}.sid")
        sp = T.find_song_speeds(sid)
        assert sp.song_of == (), name
        assert T.pack_subtune(sp, sid.start_song) == max(0, sid.start_song - 1)
