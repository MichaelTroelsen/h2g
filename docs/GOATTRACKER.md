# GoatTracker — issues found, with suggested fixes

Findings from using **GoatTracker 2.77** (`C:\Users\mit\Downloads\GoatTracker_2.77`)
as the target of a `.sid` → `.sng` converter. Every item was reproduced against
the shipped Win32 binaries and traced to a line in the distributed source.

We are not patching GoatTracker — this is a report, written so each item can be
acted on independently or sent upstream.

For where to send it, and which build to open the output in, see
[GOATTRACKER-FORKS.md](GOATTRACKER-FORKS.md): LoadTracker, GTUltra, Silver Fork
and GTMobile, with links and a comparison. Issue #1 below is present in **every
fork checked** — LoadTracker ported it to C++ unchanged — so the `--format
gts5` rule holds against all of them.

Line numbers refer to `GoatTracker_2.77/src/`. Where a claim is inference rather
than observation, it says so.

| # | Issue | Severity | Confidence |
|---|---|---|---|
| 1 | GTS2 importer overruns the pattern array | **crash / data corruption** | confirmed |
| 2 | Command-line filename overflows `char[60]` | **crash** | confirmed |
| 3 | `gt2reloc` ignores `loadsong()`'s result | silent failure | confirmed |
| 4 | Stored pattern length is discarded on load | correctness | confirmed |
| 5 | `gt2reloc` links SDL although headless | build friction | confirmed |

---

## 1. The legacy GTS2 importer overruns the pattern array

**`gsong.c:297-325`** — severity: **crash and silent cross-pattern corruption**.

```c
amount = fread8(handle);
for (c = 0; c < amount; c++)
{
    length = fread8(handle) * 4;          // length is now BYTES (rows * 4)
    fread(pattern[c], length, 1, handle);  // correct: reads `length` bytes

    for (d = 0; d < length; d++)           // BUG: d is compared against a byte
    {                                      // count but indexed as a ROW number
        switch (pattern[c][d*4+2])
        {
            case CMD_PORTAUP:
            case CMD_PORTADOWN:
            case CMD_TONEPORTA:
            pattern[c][d*4+3] = makespeedtable(pattern[c][d*4+3], MST_PORTAMENTO, 0) + 1;
            ...
```

`pattern` is `[MAX_PATT][MAX_PATTROWS*4+4]` = `[208][516]` (`gsong.c:13`).

For a 94-row pattern, `length` is 376, so the loop runs to `d = 375` and touches
`pattern[c][375*4+3]` = **`pattern[c][1503]`** — nearly three rows past the end of
a 516-byte slot. It reads there unconditionally, and *writes* there whenever the
out-of-bounds byte happens to equal `CMD_PORTAUP`/`PORTADOWN`/`TONEPORTA`/
`VIBRATO`/`FUNKTEMPO` (`$1`,`$2`,`$3`,`$4`,`$0E`), silently rewriting the
following patterns' data.

**The loop bound should be the row count, not the byte count:**

```c
for (d = 0; d < length / 4; d++)
```

**Why it matters in practice.** Any GTS2 file whose patterns use portamento
commands is affected, and portamento is not exotic — our converter emits `$1`/`$2`
on 104 rows of a single tune. Observed effect: the song **loads without complaint
and then crashes GoatTracker when played** (F1). The modern GTS3/4/5 path
(`gsong.c:189-244`) has no such conversion loop and is unaffected, which is why
the bundled `examples/` (all GTS5) never trigger it.

**Repro:** load any GTS2 `.sng` containing command `$1`, `$2` or `$3` in a pattern,
press F1.

---

## 2. Command-line filename is `strcpy`'d into a 60-byte buffer

**`goattrk2.c:355`** and **`gt2reloc.c:144`** — severity: **crash** (stack/BSS
overflow, attacker-influenced length).

```c
char songfilename[MAX_FILENAME];      // MAX_FILENAME == 60  (gfile.h:5)
...
strcpy(songfilename, argv[c]);        // goattrk2.c:355 — full path, unchecked
```

`goattrk2` *later* reduces the value to a basename (`:364`), but only after the
unchecked copy has already happened, and only if the path contains a separator.
**`gt2reloc` never reduces at all** — it copies `argv[1]` verbatim and keeps it.

This is not theoretical. It is what makes `gt2reloc` look randomly unreliable.
Running it over the 14 bundled example songs, **the outcome is decided purely by
path length**:

```
2xtest.sng         len=59  ok        sixpack.sng        len=60  ok
dojo.sng           len=57  ok        unleash.sng        len=60  ok
sanction.sng       len=61  ok        funktest.sng       len=61  ok
consultant.sng     len=63  ok        hyperspace.sng     len=63  ok
tempo2test.sng     len=63  ok
everlasting.sng    len=64  SEGFAULT  wavecmdtest.sng    len=64  SEGFAULT
cabrinigreen.sng   len=65  SEGFAULT  ghosttrackers.sng  len=66  SEGFAULT
transylvanian.sng  len=66  SEGFAULT
```

Copy the *same five crashing files* to a short path and **all 14 succeed**. The
threshold sits at 64 rather than exactly 60 because a few bytes of overflow land
in padding before something load-bearing is hit.

**Suggested fix** — bound the copy, and reduce to the basename before storing:

```c
snprintf(songfilename, sizeof songfilename, "%s", basename_of(argv[c]));
```

and reject (rather than truncate) a basename that does not fit, so a silently
wrong filename never reaches `fopen`.

**Knock-on:** anything driving these tools from a script — CI, a converter's test
suite, a build directory under a temp path — hits this immediately, because
generated paths are long. It is easy to misdiagnose as "the tool is flaky".

---

## 3. `gt2reloc` ignores `loadsong()`'s result

**`gt2reloc.c:153`** — severity: silent failure, exit code 0.

```c
if (strlen(songfilename)) {
    loadsong();                  // return value discarded
} else {
    fprintf(STDERR, "error: no song filename given.\n");
    exit (-1);
}
```

`loadsong()` reports success/failure, but the result is dropped. When a load
fails the program continues with the cleared song from `clearsong()` at `:140`,
runs `relocator()`, and **exits 0 having written no output file** — with nothing
printed on stdout or stderr.

Observed: two of our `.sng` files produce no output file and no message, while
`dojo.sng` through the identical invocation produces a 2.6 KB `.prg`. From the
caller's side the two are indistinguishable without stat-ing the output.

**Suggested fix:**

```c
if (!loadsong()) {
    fprintf(STDERR, "error: could not load '%s'\n", songfilename);
    exit(-1);
}
```

A script cannot tell success from failure today except by checking whether the
output file exists and is non-empty.

> Note: *why* those particular files fail to load is unresolved at our end —
> GoatTracker's own `sngspli2` loads the same files and reports sensible
> statistics. Worth noting that the two use different loaders. The suggestion
> here stands regardless of that cause: the failure should not be silent.

---

## 4. A pattern's stored length is discarded at load time

**`gsong.c` `countpatternlengths()`** — severity: correctness; output depends on
an unrelated user setting.

Every loader reads a pattern's length from the file to size the `fread`, then
throws it away: `countpatternlengths()` rescans the note column for `ENDPATT`
and recomputes `pattlen[c]` from that.

For a pattern that does not carry an `ENDPATT` row, the recovered length is
therefore whatever `clearpattern()` left behind:

```c
memset(pattern[p], 0, MAX_PATTROWS*4);
for (c = 0; c < defaultpatternlength; c++)  pattern[p][c*4] = REST;
for (c = defaultpatternlength; c <= MAX_PATTROWS; c++) pattern[p][c*4] = ENDPATT;
```

`defaultpatternlength` defaults to 64 but is user-configurable up to
`MAX_PATTROWS`. So **the same file loads with different pattern lengths depending
on a setting that has nothing to do with the file** — a 94-row unterminated
pattern reads back as 94 rows at the default, and as 128 rows if the user raised
`defaultpatternlength` above 94.

**Suggested fix:** trust the length stored in the file, and use the `ENDPATT`
rescan only as a fallback when the stored value is absent or out of range.

Defensible alternative: keep the rescan but have the loader write an `ENDPATT`
sentinel immediately after the loaded rows, so recovery cannot reach into
pre-fill left by a previous song.

*(This is survivable for a writer that knows about it — ours now offers explicit
`ENDPATT` termination — but it is surprising, and it makes a file's meaning
depend on editor configuration.)*

---

## 5. `gt2reloc` links all of SDL despite being headless

**`makefile.common:29-51`** — severity: build friction only.

`gt2reloc` is a console tool that opens no window and no audio device, yet its
link line pulls in `bme_gfx`, `bme_snd`, `bme_win`, `bme_mou`, `bme_kbd` and
therefore all of SDL. The makefile already acknowledges this:

```
# it would be nice not having to link things like resid, however the source is
# not ready for that
```

Consequence: building the command-line tool requires a full SDL 1.2 development
install. We got it to link by supplying 28 no-op stubs for the SDL symbols the
`bme` objects reference — **and it runs correctly**, which is direct evidence that
`gt2reloc` never calls into SDL at runtime.

**Suggested fix:** split the `bme` I/O and endian helpers that `gt2reloc` actually
needs (`bme_end`, `bme_io`) from the graphics/sound/input modules, so the
console tools link without SDL. `sngspli2`, `ins2snd2` and `mod2sng` already do
exactly this and build with a C compiler alone.

---

## Suggestions that are not bugs

- **Document the `.sng` format versions.** `GTS!`, `GTS2`, `GTS3`, `GTS4`, `GTS5`
  are all accepted, but the differences are only discoverable by reading
  `gsong.c`. For the record, GTS2 → GTS5 is: different magic; instrument bytes 5
  and 6 swap (`ptr[STBL]` and `vibdelay`); and a fourth table (the speed table)
  is stored rather than derived. A third-party writer can target GTS5 with a
  very small change — and given issue 1, it should.
- **Consider warning on GTS2 import** that the legacy path is less well tested
  than GTS3+, at least until issue 1 is fixed.
- **`MAX_FILENAME` at 60** is small for modern paths even once issue 2 is fixed;
  `MAX_PATHNAME` elsewhere in the same code is larger.

---

## What we verified, and how

Everything above was reproduced against the shipped `GoatTracker_2.77/win32`
binaries; issues 1, 3 and 4 were additionally read in the distributed source.
Issue 2's threshold was established by running all 14 bundled example songs at
both their natural path and a copy under `C:\t\` — the two columns differ for
exactly the five files whose path is ≥ 64 characters.

Issue 1 was found by bisecting a crash-on-play: the file loaded cleanly in
`sngspli2`, the orderlist restart position and instrument indices were all
in range and guarded, and `makespeedtable` is bounds-safe — which left the
import loop, where the byte-vs-row confusion is visible on inspection. Writing
the same song as GTS5 (which skips that loop) fixed the crash.
