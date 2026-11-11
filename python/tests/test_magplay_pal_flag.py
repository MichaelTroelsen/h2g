"""magplay-rt must trace as a PAL machine: $02A6 = 1 before init.

A bare emulated C64 has no KERNAL to set the PAL/NTSC flag, so $02A6 reads 0
(NTSC), and Phantoms_of_the_Asteroid and Las_Vegas_Video_Poker branch on it
(one frame in six skipped; a reload of 2 where PAL picks 4). heard.py then
scored an NTSC original against a PAL conversion: gate rises every 9.6 frames
against 8 (Phantoms), instr 17.4% and 6.4%. siddump-rt traces with -v1."""
import json
import re
import subprocess
from pathlib import Path

import pytest

import heard as H

PROGRAM = Path(__file__).resolve().parents[1] / "tools" / "magplay-rt" / "Program.cs"
CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")


def test_program_sets_the_pal_flag_before_running():
    src = PROGRAM.read_text(encoding="utf-8")
    assert re.search(r"Ram\[0x02A6\]\s*=", src), "magplay-rt never sets $02A6"
    assert src.index("Ram[0x02A6]") < src.index("tune.Run("), "flag set after the tune ran"


@pytest.mark.skipif(not H.MAGPLAY_RT.exists() or not (CORPUS / "Phantoms_of_the_Asteroid.sid").exists(),
                    reason="needs the GPL magplay-rt build and the corpus")
def test_phantoms_voice_2_regates_every_8_frames_as_pal(tmp_path):
    tr = H.trace(CORPUS / "Phantoms_of_the_Asteroid.sid", 30, 0, tmp_path / "t.json")
    st, rose = H.frames(tr, 1)
    r = [i for i, x in enumerate(rose) if x[2]]
    gaps = [b - a for a, b in zip(r, r[1:])]
    assert gaps[:20] == [8] * 20, gaps[:20]
