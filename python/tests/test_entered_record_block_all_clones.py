"""`_entered_record_block` serves every phase clone, not only `GatePhase` ones.

A fixed-arp (int residue) or pitch-seq (tuple residue) clone whose block is
the record's own played from a later entry gets that entry instead of a block
of its own (`_wavetable_layout`, the `phase_clones` loop). Tie blocks keep
the old gate-only rule: `test_tie_phase_blocks` pins their no-room spelling.
Measured at 0421071 under presets: exactly one corpus file moves,
Hunter_Patrol, 23474 -> 23466 bytes; Commando does not.

Hunter_Patrol is 23532 (+66 bytes) since its skydive's carried programs went
over the rows of its duplicate instrument blocks
(tests/test_skydive_reclaim.py): the length pinned here moved with that
change, not with the entered block.
"""
import json
import pathlib
import sys
import warnings

from corpus import CORPUS, needs_corpus

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from h2g.convert import convert  # noqa: E402


@needs_corpus
def test_hunter_patrol_enters_the_records_block_instead_of_cloning_it(
        monkeypatch):
    # The size this pin was taken at is the table before the dead blocks went
    # (`goatwriter.dead_blocks`; the room they free lets 3 more skydive
    # programs in, +112 bytes -- test_dead_blocks.py pins that arm).
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = F._preset_opts(doc, "Hunter_Patrol.sid")
    # ... and before v0.5.588's `drum_gate_off` in its preset, whose gate-off
    # drum tick shares one more table row (23460 with it).
    opts["drum_gate_off"] = False
    blob =convert(str(CORPUS / "Hunter_Patrol.sid"), log=lambda s: None, **opts)
    # 23532 before the drop of the pulse and filter rows only a dropped record
    # reaches (instrument_drop._drop_dead_blocks) took 68 bytes (23532 - 23464) of table rows.
    assert len(blob) == 23464
