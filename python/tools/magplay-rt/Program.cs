// magplay-rt: every SID write of a tune, call by call, as JSON for python/heard.py.
//
//   magplay-rt <sid> <seconds> <song, 1-based; 0 = start song> <out.json> [--score <score.json>]
//
// --score also writes MagPlaySID's transcription of the tune (the notes, instruments and
// patterns it hears, in the order each voice plays them) for python/abpage.py's "original as a
// tracker" card. The instruments are *heard* ones, numbered by the transcriber, not the
// player's own records.
//
// Links MagPlaySID's MagPlay.Transcribe (GPL-2.0-or-later); see README.md.
using System.Text.Json;
using MagPlay.Transcribe;
using MagPlay.Score;
using MagSid.Playback;

string? scorePath = null;
var rest = new List<string>();
for (int i = 0; i < args.Length; i++)
{
    if (args[i] == "--score" && i + 1 < args.Length) scorePath = args[++i];
    else rest.Add(args[i]);
}
args = rest.ToArray();
var sid = SidFile.Parse(File.ReadAllBytes(args[0]));
double secs = double.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
int song = int.Parse(args[2]);
if (song == 0) song = sid.StartSong;
var sw = System.Diagnostics.Stopwatch.StartNew();
var rec = Recording.Record(sid, song, secs);
var (score, rep) = Transcriber.Transcribe(rec, Music.Of(rec));
var gaps = Enumerable.Range(1, Math.Max(0, rec.Calls.Count - 1))
    .Select(i => rec.Calls[i] - rec.Calls[i - 1]).Order().ToList();
var outp = new {
    file = Path.GetFileName(args[0]), song, machine = rec.Machine.ToString(),
    calls = rec.Calls.Count, period_median = gaps.Count > 0 ? gaps[gaps.Count / 2] : 0,
    even_calls = rep.EvenCalls, music = rep.Music,
    // per call, flattened [cycle offset in the call, register, value, ...]
    writes = Enumerable.Range(0, rec.Calls.Count).Select(c => rec.CallWrites[c]
        .SelectMany(w => new[] { (int)(w.Cycle - rec.Calls[c]), w.Register, w.Value }).ToArray()).ToList(),
};
File.WriteAllText(args[3], JsonSerializer.Serialize(outp));
if (scorePath != null)
    File.WriteAllText(scorePath, JsonSerializer.Serialize(ScoreJson(score, rec, rep.Music)));
Console.WriteLine($"{outp.file} calls={outp.calls} period={outp.period_median} {sw.Elapsed.TotalSeconds:F1}s");

// The transcription as plain data. Rows are listed in the order each voice plays them, each
// with the time it starts at: seconds from the first play call, on the recording's own cycles.
static object ScoreJson(MagPlay.Score.Score score, Recording rec, double music)
{
    double clock = Machines.ClockHz(rec.Machine);
    int n = rec.Calls.Count;
    var patterns = score.Patterns.ToDictionary(p => p.Number);
    var timeline = n > 0 ? ScoreTimeline.Of(score, n) : null;
    var voices = Enumerable.Range(0, score.Voices.Length).Select(v =>
        (timeline == null ? Array.Empty<PlayedRow>() : timeline.Rows[v].ToArray()).Select(pr =>
        {
            var row = patterns.TryGetValue(pr.Pattern, out var p) && pr.Row >= 0 && pr.Row < p.Rows.Count
                ? p.Rows[pr.Row] : Row.Hold;
            string note = row.Note.Kind switch
            {
                RowNoteKind.Note => NoteTables.Name(row.Note.Note + pr.Transpose),
                RowNoteKind.GateOff => "---",
                RowNoteKind.GateOn => "+++",
                _ => "...",
            };
            return new {
                t = Math.Round((rec.Calls[Math.Min(pr.Call, n - 1)] - rec.Calls[0]) / clock, 4),
                call = pr.Call, pattern = pr.Pattern, row = pr.Row, note,
                instr = row.Instrument, fx = row.Effects.Select(e => e.Label).ToArray(),
            };
        }).ToArray()).ToArray();
    return new {
        machine = rec.Machine.ToString(), clock_hz = clock, calls = n,
        cycles_per_call = score.CyclesPerCall, tempo = score.Tempo, funk_tempo = score.FunkTempo,
        music_share = music,
        instruments = score.Instruments.Select(i => new {
            number = i.Number, ad = i.AttackDecay, sr = i.SustainRelease,
            wave_program = i.WaveProgram, pulse_program = i.PulseProgram,
            filter_program = i.FilterProgram }).ToArray(),
        patterns = score.Patterns.Select(p => new {
            number = p.Number, rows = p.Rows.Count }).ToArray(),
        voices,
    };
}
