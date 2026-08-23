# TODO

Hand-written, unlike `whats-next.md` (a session handoff) and
`.claude/tasks/whattask.json` (generated, and rewritten whole by `/whattask`).
`/whattask` reads this file as one of its sources, so an item here survives a
replan and reaches the next plan on its own.

Keep items actionable: what to run, and what makes it done.

## Open

- **Rebuild `build/instrmap`.** The dumps on disk are stale against HEAD:
  `build/instrmap/*.md` has mtime `2026-08-23 14:03`, while `428ca07` — which
  enables `--rest-envelope-silence` for ACE_II, Thundercats, Shockway_Rider,
  BMX_Kidz and Auf_Wiedersehen_Monty — landed at `15:38`. So every dump
  predates the conversion change for those five files.

  This matters because the instrument maps are the input to every read-only
  diagnosis in the current plan, and to the vibrato-depth measurements recorded
  in CLAUDE.md. A sibling agent regenerated ACE_II's map fresh and found its
  figures matched the stale ones to within rounding (voice 1 78.9%/97.5% against
  79%/98%), so nothing measured so far is known to be wrong — but that is one
  file checked, not a guarantee, and the next diagnosis should not have to
  re-establish it.

  ```sh
  cd python
  python abpage.py --instrmap "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
  ```

  That regenerates `build/instrmap/` **and** rebuilds the listening pages,
  copying each report beside them. Done when every `build/instrmap/*.md` is
  newer than the most recent commit that changed conversion output.

  `[main]` — it rebuilds `build/instrmap` and `build/listen`, both of which the
  plan lists as hazards, so it must not run beside anything reading them.
