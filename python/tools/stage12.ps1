# Stage the whole corpus with per-voice renders, twelve shards.
#
# One process per core: the box has 12, and sidplayfp is single-threaded, so
# six shards left half the machine idle. Each shard writes its own
# LISTENING.part<I>.md, which `listen.py --merge-notes` folds afterwards.
$repo = "C:\Users\mit\claude\h2g"
$corpus = "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob"
$shards = 12

foreach ($i in 0..($shards - 1)) {
    Start-Process -FilePath "python" `
        -ArgumentList @("listen.py", $corpus, "--all", "--voices",
                        "-t", "120", "--presets", "../presets.json",
                        "--shard", "$i/$shards") `
        -WorkingDirectory "$repo\python" `
        -RedirectStandardOutput "$repo\build\v12_shard$i.log" `
        -RedirectStandardError "$repo\build\v12_shard$i.err" `
        -WindowStyle Hidden
}
"launched $shards shards"
