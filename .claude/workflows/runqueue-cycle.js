export const meta = {
  name: 'runqueue-cycle',
  description: 'h2g runqueue cycle: delegable subtasks, each in its own worktree',
  phases: [{ title: 'Delegate', detail: 'one worktree agent per task' }],
}
const SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' },
    outcome: { type: 'string', enum: ['done', 'partial', 'failed', 'inconclusive'] },
    evidence: { type: 'string' },
    verify_output: { type: 'string' },
    notes: { type: 'string' },
    opened: { type: 'array', items: { type: 'string' }, maxItems: 1 },
    patch: { type: 'string' },
  },
  required: ['id', 'outcome', 'evidence', 'verify_output'],
}
const RULES = `RULES (non-negotiable):
1. Run the verify and report its REAL output (commands and their printed results). Do not merely say that it passed. Return EVIDENCE, not a summary. Name your scratch path C:/t/<task-id> and the commands you ran in both evidence and verify_output.
2. Stay inside the declared touches. The OPTIMISTIC MERGE note in the verify allows the source and test edits it names. Reading any path is allowed. If the task turns out to need a write the verify does not allow, STOP and report that.
3. Confirm your footprint: run \`git diff --stat\` (after \`git add -A -N .\`) and fold into verify_output a statement that only allowed paths changed.
4. NEVER run a command that discards working-tree changes: git checkout <path>, git restore, git reset --hard, git clean, git stash, or anything of that shape. (The one detach checkout in the FIRST STEP, on the fresh worktree, is the only exception.) To undo your own change, re-edit the file or work on a copy under your scratch path.
5. Never commit, merge, push, branch or open a PR. Never write .claude/tasks/serial.lock, runs.jsonl, whattask.json, SURVEY.md, presets.json, FIDELITY.md or QUEUE.md, and never run graphify update.
6. If you change tracked files, write the diff against the base with \`git diff --output=C:/t/<task-id>/final.patch <base> -- .\` (after \`git add -A -N .\`), and put that path in the \`patch\` field.
7. The returned \`id\` must be exactly the task id given below. \`opened\` holds AT MOST ONE new follow-up task (user, 2026-10-17: the queue must shrink, not grow), tagged [subagent]/[main]/[user], and ONLY if it names a MEASURED loss or gain on a scored column of a named file (e.g. 'Tarzan aud .896 -> .888 under X: find why'). Never open a census, an audit, a 'check whether', a doc tidy-up, a re-take of figures, or a merge/regenerate chore -- put those observations in \`notes\` instead. When in doubt, open nothing.
8. Mega_Apocalypse is the subject of two sibling tasks this cycle; if you edit a shared goatwriter module, keep the change narrow so the orchestrator can merge both.
graphify-out/graph.json is available for relationship questions (\`graphify query "<question>"\`, \`graphify path "<A>" "<B>"\`). Its matcher is fuzzy, so confirm a returned node's source_file is the path you mean before trusting it.
PROGRESS (optional, display only). If the tool \`mcp__mit-setup__step\` is available, call it right after reading this brief with \`total\` = your plan in 3-8 steps and \`done: 0\`, then again with the new \`done\` and a few-word \`note\` as each step finishes. If it is not available or a call fails, carry on without it. It never replaces the evidence you return. If the tool is listed only as deferred, load it first with ToolSearch query \`select:mcp__mit-setup__step\`, and treat it as absent only when that load returns nothing.`
phase('Delegate')
const results = await parallel(args.tasks.map(t => () => {
  const prompt = `Task: ${t.id}

You are running one task from the h2g plan in an isolated git worktree.

FIRST STEP, before reading or editing anything: the worktree is created from origin/master, which is behind local master. Run \`git checkout --detach ${args.base}\` in the fresh worktree (it holds no changes yet, so this discards nothing), then confirm with \`git rev-parse --short HEAD\` that it prints ${args.base}. If it does not, stop and report.

YOUR TASK RECORD: read the object whose "id" is "${t.id}" from the plan file C:/Users/mit/claude/h2g/.claude/tasks/whattask.json (the MAIN checkout's copy, by that absolute path -- your worktree's copy is stale; parse it as JSON, the records are under "tasks"). Its "title" is the task, its "verify" string is the DEFINITION OF DONE (follow it verbatim), its "touches" are the only paths you may write outside your worktree, and a non-null "decision" is a settled human answer you must follow, not re-derive. Earlier attempts of the same id, if any, are lines in C:/Users/mit/claude/h2g/.claude/tasks/runs.jsonl -- read them first.

${RULES}`
  const opts = { label: t.id, phase: 'Delegate', schema: SCHEMA, isolation: 'worktree', model: t.model }
  if (t.effort) opts.effort = t.effort
  return agent(prompt, opts)
}))
return results.map((r, i) => r ? Object.assign({ dispatched: args.tasks[i].id }, r) : { dispatched: args.tasks[i].id, missing: true })
