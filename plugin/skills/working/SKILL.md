---
name: working
description: Use when an approved task manual from miniplan:plans exists and the user says to start, continue, or resume it (开工/继续/接着跑). Dispatches each task's agents with the manual's prompts, gates every task on independent evidence, keeps a progress ledger so work survives context compaction, repairs once, and reports per run. Not for planning or designing — if the manual is missing or unapproved, stop and use miniplan:plans.
---

# Working

Input: the path of an approved task manual. Roles, budget, contracts, and the
budget grant command come from `miniplan:agents`. The main conversation
dispatches, collects, gates, and reports.

## Setup

1. Read the manual, then the Acceptance section of the design file its
   header names (the A<i> ids that REALIZES and the report refer to).
   The manual header must say 已批准; if not, stop and use `miniplan:plans`.
   Never start on an unapproved manual regardless of urgency.
2. Read `## Progress`. A task with a `T<n>: complete` line is done: do not
   re-dispatch it. A task whose last line is `T<n>: repair 1` is mid-loop:
   resume at the re-gate. Resume at the first task without a line.
3. Run `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py lint <plan>`. Exit
   0 is required before any dispatch; a defect list means the manual goes back
   to `miniplan:plans`.
4. Pre-flight: read the manual critically once. A CHECK with no command, a
   path that does not exist, an interface no task defines, a 箭线图 arrow that
   contradicts DEPENDS — rule on it and ledger the ruling, or stop if every
   path forward is a guess. A CHECK whose test body the task itself writes is
   not a defect; it runs at the gate after the builder's step.

## Execution modes

<!-- host:claude-code -->
Use workflow mode when the Workflow tool is available and the manual has
task blocks. A manual in the old format (P0/C1 numbering, no task blocks) and a
session without the Workflow tool use prompt mode.

### Workflow mode

The script `run-manual.js` schedules the whole manual: readiness, worktrees,
gates, one repair, serial merges, spawn counting. The header `预算` is the run
size the user approved; the budget grant does not apply.

1. **Prepare.** Setup above, then quote the manual's `预算` line to the user as
   the approved run size. Note `git rev-parse HEAD` as the run start.
2. **Root main tasks first.** Run
   `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py ready <plan>`. Do each
   `main` task whose dependencies are complete, run its CHECK, and ledger it
   (see Ledger).
3. **Start the run.** Call
   `Workflow({scriptPath: "<absolute path of ~/.claude/skills/miniplan/workflows/run-manual.js>", args: {plan: "<absolute manual path>"}})`;
   expand `~` yourself (`echo ~`), the tool takes the path literally.
   Pass only the plan path; the PreToolUse hook validates the manual and fills
   in the rest of `args`. If the script returns `{error: 'args-not-expanded'}`,
   run `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py args <plan> --small`
   and call again with its JSON output as `args` (the hook compares it in full).
   While the run is in the background, spawn no agents, edit nothing in the
   integration copy, and wait for the completion notice. A builder dispatched by
   hand needs `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py release <plan>`
   first; that ends workflow mode for this manual.
4. **Run returned.** The result is
   `{spawned, budget, tasks: [{id, status, reason, ...}], ledger: [...]}`.
   - Write every `ledger` line in one call:
     `printf '%s\n' "<line>" ... | python3 -I ~/.claude/skills/miniplan/bin/miniplan.py ledger <plan>`.
   - Read `git log --oneline <run start>..HEAD`, spot-check a few merge diffs,
     and read the gate evidence of the tasks you spot-checked.
5. **Stops.** `status` is one of complete, done-before, failed, skipped,
   waiting-main, blocked.
   - `waiting-main`: do the task yourself and run its CHECK, or hand the action
     to the user.
   - `blocked`: act on `reason`. `budget`: the user raises `预算` in the header.
     `infra` and `not-verifiable`: carry the evidence to the user. `builder`:
     answer its `next` from the design or manual, otherwise ask the user.
     `scope`, `stray-edit`, `empty`, `merge`: inspect the task branch and
     worktree, then report. Any other reason (`error`, `agent-null`, `reader`,
     `merge-check`): carry `reason` and the evidence to the user.
   - `failed`: carry the gate findings to the user. `skipped` names its failed
     upstream.
   - If nothing needs the user, go back to step 3; the script skips tasks that
     already have a complete line. If something does, write the report and wait.
6. **Finish.** Set the manual status to 已完成 with the date, then
   `git branch -d` the merged `mp/<topic>/*` branches, `git worktree prune`, and
   run `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py check <plan>`; it
   removes the run marker. The Stop hook blocks finishing while the ledger and
   the 箭线图 or merged branches disagree; `check` lists the problems and the fix
   is to ledger the missing lines. Worktrees of failed tasks stay until prune.

<!-- /host -->
<!-- host:codex
### Script mode

Use the Codex script adapter for an approved task-block manual. Read
[Codex workflow](references/codex-workflow.md) before its first run. It uses
`codex exec` with the named role's configuration and shares the dependency,
gate, repair, and merge scheduler with the Claude workflow.

1. Validate with
   `node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs <plan> --dry-run`.
2. Run the same command without `--dry-run`, adding
   `--request-id <token>` identifying this user request; retain the same
   token for every resume within the request so earlier launches still count.
   A new user request can use a new token. While it runs, do not dispatch
   other agents or edit the integration copy. The script counts all role
   launches and limits live Codex processes to three.
3. Read `result.json` and the gate evidence in the reported output directory.
   The script applies its returned ledger itself. Exit zero means every task
   is complete or was already completed; blocked, failed, and waiting-main
   outcomes return nonzero and preserve evidence and unfinished worktrees.
4. Handle main tasks and reported blockers, then resume only after accounting
   for the request's remaining agent budget. Do not reset the budget by
   rerunning the script. When complete, check the merged diff, mark the manual
   complete, and commit/push using the user's existing authorization.

Use prompt mode when the CLI/runtime is unavailable or the manual cannot be
run by the script. Do not use that fallback to bypass a failed preflight.
-->
### Prompt mode

Used for old-format manuals and wherever a scripted run is unavailable.

- **Ready set.** On every completion notice, first run
  `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py ready <plan>`. In the
  same message dispatch every newly ready task's agents, then make one
  `miniplan.py ledger` call recording the complete lines and a
  `T<n>: dispatched` line per new task. Keep sequential what the manual marked
  sequential.
<!-- host:claude-code -->
- **Concurrency.** The Agent tool's concurrency setting
  (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`) bounds how many run at once; the
  manual's `并发` header applies to workflow mode only. Refill freed slots with
  newly ready work.
<!-- /host -->
<!-- host:codex
- **Concurrency.** Up to 3 child threads at once. Refill freed slots with newly
  ready work.
-->
- **Parallel builders use worktrees.** Create the task's worktree with
  `git -C <repo> worktree add -b mp/<topic>/t<n> <repo>/.claude/worktrees/mp-<topic>-t<n> <integration>`,
  run the manual's `工作树准备` there, and build the contract from
  `miniplan.py prompt <plan> <T> <role>`. A child's `cd` does not persist between
  Bash calls, so the contract states that every command starts with
  `cd <worktree absolute path> && export MINIPLAN_SLOT=<s> && <槽位环境> && `
  and that Edit/Write use absolute paths under the worktree. A lone builder may
  work in the integration copy.
- **Merge serially, yourself.** Per finished task, after its gate passes:
  `miniplan.py merge-check <plan> <T> <branch>` (non-zero exit: do not merge),
  then `git merge --no-ff -m "<task title>" <branch>` in the integration copy,
  then `git worktree remove <path>`. On a conflict, `git merge --abort` and send
  the task's builder to merge the integration branch inside its own worktree;
  that is the task's one repair, followed by a re-gate.
- Send the manual's PROMPT verbatim with `subagent_type: miniplan:<role>`
  (the AGENTS field names the role bare). Add only facts that came into
  existence after planning (a path a previous task created). Never forward
  the conversation.
- `main` tasks: do the edit yourself, then run the CHECK like any other task.
- Continuous execution: no "shall I continue" between tasks.
  Stop only for an irreversible or destructive operation (rm of
  user data, a schema drop, a device reflash), a credentialed or external
  side effect (a git push or merge to a shared branch, a message to an
  external service, a deploy), a security-sensitive action, or a manual
  defect that makes every path forward a guess. Everything else you
  rule on and ledger as `Ruling: <decision> — <why> — <cost if wrong>`.
- Budget: if `预算` exceeds the default and the user agreed to it,
<!-- host:claude-code -->
  run once, now, from your own Bash tool:
  `bash ~/.claude/skills/miniplan/hooks/agent-guard.sh grant <N>` (details in
  `miniplan:agents`; `status` shows used/budget, `revoke` ends the grant).
<!-- /host -->
<!-- host:codex
  tell the user to relaunch codex with `CODEX_AGENT_GUARD_BUDGET=<N>` exported
  (no per-session grant on Codex), or split the work across user prompts.
-->
  Otherwise the default applies and each user prompt is a checkpoint.

## Collect and gate (prompt mode)

- The task's CHECK is run by the gate named in AGENTS, or by you for a one-line
  command. The gate receives the CHECK text and the design's A<i>, not the
  builder's summary. Verdict per CHECK: pass / fail /
  not verifiable.
- Ledger on the gate's evidence. After merging, spot-check the merge diff. If
  you and the gate disagree, the report says so; do not pick one silently.
- Fail: one repair round, with the gate's findings as the changed input, then
  re-gate the fix only. A second fail goes to the user.
  `judge` only when the user asks.
- A child returning `blocked` or `partial` with a question: answer from the
  design or manual and respawn once with the answer; otherwise carry it to the
  user.

## Test selection and full suites

- When the project provides a command that selects tests from the change set
  (for example `npm run test:affected`), builders and per-task gates run that
  command and nothing broader. Never rerun every test because one page changed.
- A full suite runs once per manual: at the final pre-merge gate, on the final
  commit, run by the verifier. Main reads the verifier's raw output and failure
  list instead of running it again.
- After a repair, rerun the failed tests and the selection command only, unless
  the repair touches a file the project marks as a full-suite trigger.
- A test that passed only on retry is named in the ledger.

## Ledger

Ledger lines go through
`python3 -I ~/.claude/skills/miniplan/bin/miniplan.py ledger <plan>`, which reads
lines from stdin, appends them to `## Progress`, and sets each task's arrow in
`## 箭线图` to the matching glyph. Batch the lines of one step into one call.
Never hand-edit the diagram glyphs; `miniplan.py diagram --write <plan>` rebuilds
the diagram from DEPENDS and the ledger.

Lines: `T<n>: complete — <evidence pointer>`, `T<n>: repair 1 — <finding>`,
`T<n>: failed — <why>`, `T<n>: dispatched`, `Ruling: ...`. Glyphs: `✅完成`,
`🔁返工`, `❌失败`; `T<n>: dispatched` sets `🔄进行中` in the diagram and adds no
line to `## Progress`. On resume the `## Progress` lines are authoritative;
`miniplan.py check <plan>` lists any disagreement with the diagram.

## Report (user's language)

```text
PROGRESS: <a>/<b> 任务完成；第 <k> 次运行；最长链还剩 <z> 个任务；派发 <spawned>/<budget>
ACCEPTANCE: A1 pass (evidence) / A2 fail (why) / A3 not verified (why)
CHANGES: files, systems, commands run
RULINGS: decisions made without asking
LEFT OUT: skipped or descoped, and why
NEXT: what needs the user (approvals, follow-ups, next run)
```

<!-- host:claude-code -->
In workflow mode a run is one Workflow call.
<!-- /host -->
In prompt mode a run is one stretch of work between user prompts.
The user's reply starts the next run and resets the spawn count. On the
final run: revoke the budget grant if one was made, set the manual status
to 已完成 with the date, and list anything still not verified. Nothing is
reported as done without a pass line with evidence.

## Anti-patterns

- Reporting the builder's VALIDATION as verification.
- Fixing the gate's findings in the main thread and skipping the re-gate.
- Re-dispatching a task that has a complete line.
- Ending a run on an unverified builder.
- Ledgering a task complete while its arrow in the 箭线图 still reads ⏳.
- Raising the budget without the approval recorded in the manual header.
- Running a full suite in a builder, or again after the final gate ran it.
<!-- host:claude-code -->
- Dispatching builders by hand during a workflow run without `release`.
- Hand-assembling `args` for the Workflow call when the hook can fill them.
- Editing the integration copy while a run is in the background.
<!-- /host -->
