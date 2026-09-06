---
name: listen
description: Stage a listening pass — render the tunes a question is about, build the A/B pages, serve them. Knows what makes a verdict worthless and refuses to stage that.
disable-model-invocation: true
---

# listen

A listening verdict is the most expensive evidence this project collects and
the only instrument that reads several things at all. It is also the easiest to
spend on the wrong audio. This is the sequence, with the judgements.

## Before anything: is the material even current?

**A verdict on stale audio describes a build that no longer exists.** This has
cost the project real work — CLAUDE.md records a half-speed audition of Last_V8
that reversed a measurement, which a `vsid` re-test then reversed back.

`abpage.py` enforces this itself: `--allow-stale-audio` is **off by default**
and it WITHHELDS the H2G render of any tune whose audio predates the current
converter. On one recent build that was **55 of 89 tunes**. So the page is
honest — but staging the right tunes is still yours.

Check before you start:

```bash
ls build/listen/*.h2g.wav | head          # what is staged at all
```

A tune the open questions name but `build/listen/` does not hold has never been
rendered. Six interleaved-classic files were in that state for weeks while
their tasks read as "blocked on a listening verdict" — they were blocked on a
staging run nobody had done, which is agent work, not the human's.

## 1. Stage — with `--files`, essentially always

```bash
cd python
python listen.py <sid_dir> --from-json ../build/fidelity.json -t 180 \
    --files Tune_One.sid Tune_Two.sid ...
```

**`--all` stages every converting tune: ~1.7 GB and a couple of hours.**
`--files` is the documented way to stage "the handful a question is about", and
the questions are always about a handful — scope it to the tunes the open tasks
actually name.

**Match `-t` to the window the numbers were measured in.** The artefact is
180 s; staging at 120 and quoting 180 s figures beside it invites a comparison
between two different spans. Check `build/fidelity.json`'s `seconds`.

`--from-json` is what lets the page state the numbers beside the audio, so the
listener knows what the tool already thinks.

## 2. Build the pages

```bash
python abpage.py --instrmap <sid_dir>
```

`--instrmap` costs two emulations per staged tune and is opt-in for that
reason — but it is scoped to what is STAGED, not the corpus, which is what
makes it affordable. Include it when the question is "which instrument is at
fault" (ACE II's withheld gains, Monty's firstwave trade); skip it when the
question is about the whole tune.

Without it the pages reuse whatever `build/instrmap.json` already holds and
omit the card where there is none.

## 3. Serve

```bash
python abpage.py --serve 8730 --no-build
```

`--serve` alone REBUILDS every staged page first (~3.4 s a tune) before binding
the port, so pass `--no-build` when step 2 has just run. Python buffers stdout,
so the log can look empty while the server is fine — test the port rather than
the log:

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8730/
```

`file://` will not work: the envelope drawing and the automatic sync both read
the WAVs with `fetch()`, which no browser allows over `file://`.

## 4. When a verdict comes back

Record it with `/runhuman`, not in prose. `whattask.json` is a snapshot the
next regeneration rewrites whole, so an answer stored only there is destroyed
and the human gets asked the same question twice. `decisions.jsonl` is the
durable record.

**If the verdict is about SPEED, run `--pace` before believing it.** CLAUDE.md:
"Use `--pace` before saying anything about speed, tempo or `-S`." 49 of 89
songs pack above `-S1`, and a bare GoatTracker launch plays those at
1/multiplier — a listener reporting "too slow" may be hearing the editor rather
than the conversion. `--pace` distinguishes them in one line: a ratio of
exactly 2.000 with a zero-width IQR is a wrong constant, not a mechanism.
