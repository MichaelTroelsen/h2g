import json, sys, pathlib, pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import fidelity

def test_pace_forcing_regrid_flag(monkeypatch, tmp_path):
    cmdo_sid = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
    if not cmdo_sid.exists():
        pytest.skip("Commando.sid not found")
    
    presets = {"always": {}}
    presets_file = tmp_path / "presets.json"
    presets_file.write_text(json.dumps(presets))
    
    recorded_opts = []
    def spy_pace_report(sid, workdir, opts, args, mult):
        recorded_opts.append(opts)
        return ""
    
    monkeypatch.setattr(fidelity, "pace_report", spy_pace_report)
    
    fidelity.main([str(cmdo_sid), "--pace", "--regrid", "--presets", str(presets_file), "--gt2reloc", __file__])
    
    assert recorded_opts[0]["regrid"] is True

@pytest.mark.parametrize("flag, key", [
    ("--slides", "slides"),
    ("--effects", "effects"),
    ("--fold-transpose", "fold_transpose"),
    ("--regrid", "regrid")
])
def test_pace_forcing_flags(monkeypatch, tmp_path, flag, key):
    cmdo_sid = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
    if not cmdo_sid.exists():
        pytest.skip("Commando.sid not found")
    
    presets = {"always": {}}
    presets_file = tmp_path / "presets.json"
    presets_file.write_text(json.dumps(presets))
    
    recorded_opts = []
    def spy_pace_report(sid, workdir, opts, args, mult):
        recorded_opts.append(opts)
        return ""
    
    monkeypatch.setattr(fidelity, "pace_report", spy_pace_report)
    
    fidelity.main([str(cmdo_sid), "--pace", flag, "--presets", str(presets_file), "--gt2reloc", __file__])
    
    assert recorded_opts[0][key] is True

def test_pace_forcing_no_flags(monkeypatch, tmp_path):
    cmdo_sid = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"
    if not cmdo_sid.exists():
        pytest.skip("Commando.sid not found")
    
    presets = {"always": {}}
    presets_file = tmp_path / "presets.json"
    presets_file.write_text(json.dumps(presets))
    
    recorded_opts = []
    def spy_pace_report(sid, workdir, opts, args, mult):
        recorded_opts.append(opts)
        return ""
    
    monkeypatch.setattr(fidelity, "pace_report", spy_pace_report)
    
    fidelity.main([str(cmdo_sid), "--pace", "--presets", str(presets_file), "--gt2reloc", __file__])
    
    assert recorded_opts[0].get("regrid") is not True
