// magplay-rt: every SID write of a tune, call by call, as JSON for python/heard.py.
//
//   magplay-rt <sid> <seconds> <song, 1-based; 0 = start song> <out.json>
//
// Links MagPlaySID's MagPlay.Transcribe (GPL-2.0-or-later); see README.md.
using System.Text.Json;
using MagPlay.Transcribe;
using MagSid.Playback;

var sid = SidFile.Parse(File.ReadAllBytes(args[0]));
double secs = double.Parse(args[1], System.Globalization.CultureInfo.InvariantCulture);
int song = int.Parse(args[2]);
if (song == 0) song = sid.StartSong;
var sw = System.Diagnostics.Stopwatch.StartNew();
var rec = Recording.Record(sid, song, secs);
var (_, rep) = Transcriber.Transcribe(rec, Music.Of(rec));
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
Console.WriteLine($"{outp.file} calls={outp.calls} period={outp.period_median} {sw.Elapsed.TotalSeconds:F1}s");
