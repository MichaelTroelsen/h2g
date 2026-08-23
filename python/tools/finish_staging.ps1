# Wait for the render shards, then fold the notes, take the traces, rebuild.
#
# Order matters. The traces pass goes through the same staging loop, so it
# writes LISTENING.md too -- but with no renderer chosen, so its header would
# describe a pass that rendered nothing. That is precisely the drift v0.5.317
# fixed in merge_notes, and it would be silly to reintroduce it here, so the
# merged notes are set aside and put back afterwards.
$ErrorActionPreference = "Stop"
$repo = "C:\Users\mit\claude\h2g"
$listen = "$repo\build\listen"
$corpus = "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob"

# 1. wait for every --voices shard to exit
while ($true) {
    $n = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
           Where-Object { $_.CommandLine -like '*--voices*' }).Count
    if ($n -eq 0) { break }
    Start-Sleep -Seconds 20
}
$wavs = @(Get-ChildItem "$listen\*.v?.*.wav" -EA SilentlyContinue).Count
"staging finished: $wavs per-voice WAVs"

Set-Location "$repo\python"

# 2. fold the twelve shards' notes into LISTENING.md
python listen.py --merge-notes
Copy-Item "$listen\LISTENING.md" "$listen\LISTENING.keep.md" -Force

# 3. the traces the panel and the tracker read
python listen.py $corpus --all --traces-only -t 120 --presets ../presets.json
$traces = @(Get-ChildItem "$listen\*.trace.json" -EA SilentlyContinue).Count
"traces written: $traces"

# 4. put the render run's notes back, then rebuild the pages
Move-Item "$listen\LISTENING.keep.md" "$listen\LISTENING.md" -Force
python abpage.py

"done"
