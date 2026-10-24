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
3. Run `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" lint <plan>`. Exit
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
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" ready <plan>`. Do each
   `main` task whose dependencies are complete, run its CHECK, and ledger it
   (see Ledger).
3. **Start the run.** Call
   `Workflow({scriptPath: "${CLAUDE_PLUGIN_ROOT}/workflows/run-manual.js", args: {plan: "<absolute manual path>"}})`;
   the tool takes the path literally, so expand `~` or `$HOME` in it yourself.
   Pass only the plan path; the PreToolUse hook validates the manual and fills
   in the rest of `args`. If the script returns `{error: 'args-not-expanded'}`,
   run `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" args <plan> --small`
   and call again with its JSON output as `args` (the hook compares it in full).
   While the run is in the background, spawn no agents, edit nothing in the
   integration copy, and wait for the completion notice. A builder dispatched by
   hand needs `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" release <plan>`
   first; that ends workflow mode for this manual.
4. **Run returned.** The result is
   `{spawned, budget, tasks: [{id, status, reason, ...}], ledger: [...]}`.
   - Write every `ledger` line in one call:
     `printf '%s\n' "<line>" ... | python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" ledger <plan>`.
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
6. **Finish.** Do the `## Retrospective` below, then set the manual status to
   已完成 with the date, then
   `git branch -d` the merged `mp/<topic>/*` branches, `git worktree prune`, and
   run `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" check <plan>`; it
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
   `node <miniplan-agents>/scripts/codex-run.mjs <plan> --dry-run`.
2. Run the same command without `--dry-run`. While it runs, do not dispatch
   other agents or edit the integration copy. The script follows the manual's
   task concurrency and separate verifier concurrency, and counts every role
   launch against the whole-manual budget across resumes.
3. Read `result.json` and the gate evidence in the reported output directory.
   The script applies its returned ledger itself. Exit zero means every task
   is complete or was already completed; blocked, failed, and waiting-main
   outcomes return nonzero and preserve evidence and unfinished worktrees.
4. Handle main tasks and reported blockers, then resume within the
   manual's remaining budget. Do not reset the budget by
   rerunning the script. When complete, check the merged diff, do the
   `## Retrospective` below, mark the manual complete, run
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" check <plan>`, and
   commit/push using the user's existing authorization.

Use prompt mode when the CLI/runtime is unavailable or the manual cannot be
run by the script. Do not use that fallback to bypass a failed preflight.
-->
### Prompt mode

Used for old-format manuals and wherever a scripted run is unavailable.

- **Ready set.** On every completion notice, first run
  `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" ready <plan>`. In the
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
  the task's builder to merge the integration branch inside its own worktree, then re-gate. A conflict is handled once even after a repair; one handled before any repair uses up the repair.
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
  When the user corrects a practice mid-run, ledger
  `Ruling: 用户纠正 — <原话摘要>`. While a workflow runs in the background,
  keep it in the session and write it with the returned ledger lines.
- Budget: if `预算` exceeds the default and the user agreed to it,
<!-- host:claude-code -->
  run once, now, from your own Bash tool:
  `bash "${CLAUDE_PLUGIN_ROOT}/hooks/agent-guard.sh" grant <N>` (details in
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
- For a task with a builder, the gate also checks that tests were not weakened:
  a test body given in the CHECK is compared with the worktree, and in the
  task's diff against the integration branch a removed or loosened assertion or
  a new skip marker is a fail that quotes the removed line, unless the
  contract's GOAL or ACCEPTANCE asks for it.
- Ledger on the gate's evidence. After merging, spot-check the merge diff. If
  you and the gate disagree, the report says so; do not pick one silently.
- Fail: one repair round. Its contract carries the failing command and its output, and the builder states a one-line root-cause hypothesis before editing, quoting the line of failing output it rests on (from the gate's log when one is named, otherwise the gate's finding verbatim), and changes only code tied to the gate's findings. Re-gate the fix only. A second fail goes to the user. `judge` only when the user asks.
- A child returning `blocked` or `partial` with a question: answer from the
  design or manual and respawn once with the answer; otherwise carry it to the
  user.

## Test selection and full suites

<!-- host:claude-code -->
- Every test, build, type-check, or lint command runs as
  `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" test -- <command>`: at
  most 2 such runs at once on the machine across all sessions, each capped at
  4 GB of memory, the rest queue. This holds for main's own runs too. Every
  contract states it, with a Bash timeout of 600000 for these calls; several
  commands share one slot as `test -- bash -c '<cmd1> && <cmd2>'`. A
  PreToolUse hook denies a command carrying the `MINIPLAN_SLOT` prefix that
  runs tests without it.
- Gates run CHECK commands as `test --log -- <command>`: the full output goes
  to a log file whose path is printed; the gate puts that path in its evidence,
  and the ledger line points to it.
<!-- /host -->
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
`python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" ledger <plan>`, which reads
lines from stdin, appends them to `## Progress`, and sets each task's arrow in
`## 箭线图` to the matching glyph. Batch the lines of one step into one call.
Never hand-edit the diagram glyphs; `miniplan.py diagram --write <plan>` rebuilds
the diagram from DEPENDS and the ledger.

Lines: `T<n>: complete — <evidence pointer>`, `T<n>: repair 1 — <finding>`,
`T<n>: failed — <why>`, `T<n>: dispatched`, `Ruling: ...`. Glyphs: `✅完成`,
`🔁返工`, `❌失败`; `T<n>: dispatched` sets `🔄进行中` in the diagram and adds no
line to `## Progress`. On resume the `## Progress` lines are authoritative;
`miniplan.py check <plan>` lists any disagreement with the diagram.

## Retrospective

Do it after the final full gate passes and before the status is set to 已完成.
When the falsification is deferred, the next run resumes at step 3.

1. **Collect.** The repair, failed, and Ruling lines in `## Progress`; the gate
   logs the ledger lines name; the diffs of the repair commits; the design's
   `## 引用经验`.
2. **Write `## 复盘`** at the end of the manual:
   - One judgement line per repair, failed task, ruling, user correction, and
     cited lesson: `<对象> | <改动或做法> | <观察到的差异与出处> | <判定>`.
     Verdicts: 有效, 有害, 无可见效果, 无法归因, 用户纠正. 有效 needs all of:
     the same acceptance command failed before the change (quote the failing
     line) and passed after it; the change targets one cause; nothing passed
     on retry. A change that broke something is 有害. A practice the user
     explicitly corrected during the run is 用户纠正. Anything uncertain is
     无法归因.
   - At most one candidate lesson, or `经验：无`. A lesson must hold for this
     repository's code, tests, commands, interfaces, or data; a practice that
     holds in any unrelated repository is a process lesson and is not kept.
   - Process observations and suggestions to turn a practice into a test, lint
     rule, or hook: list them here and in the report only. Do not implement
     them and do not write them to any long-term file.
3. **Falsify.** When there is a candidate or two lessons are merged, dispatch
   one `critic` with [lesson-falsify](references/lesson-falsify.md). Rule on
   each objection in a table in `## 复盘`; an accepted objection that removes
   the candidate's support turns the conclusion into `经验：无`. This dispatch
   is not counted in `预算`; the per-request dispatch limit applies, and at the
   limit stop here: do not set 已完成, say so in the report, and resume the
   retrospective at step 3 in the next run. Ledger
   `Ruling: 经验反证 — <文件> — <入库 | 不入库，原因>`.
4. **Write the lessons** per [lesson-template](references/lesson-template.md).
   The main thread, without a critic, also appends citation records to cited
   lessons, deletes lessons judged 有害, repairs stale paths, and, before
   adding a new lesson when the library holds 30, evicts one (first a lesson
   whose paths all no longer exist, then the one cited longest ago, uncited
   ones by source date). Record these actions in `## 复盘` and in the `LESSONS:`
   line of the report. Run
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" lessons` and commit only
   when it exits 0. The commit touches only `docs/lessons/` and the manual, and
   its message states the lesson. When the project tests `docs/`, run its test
   selection command after the commit.
5. **Conclude.** The last line of `## 复盘` is `经验：docs/lessons/<文件>.md`
   or `经验：无`. Setting 已完成 and running `check` stay in the finish step of
   the mode in use.

## Report (user's language)

```text
PROGRESS: <a>/<b> 任务完成；第 <k> 次运行；最长链还剩 <z> 个任务；派发 <spawned>/<budget>
ACCEPTANCE: A1 pass / A2 fail (why) / A3 not verified (why)
RULINGS: decisions made without asking
LESSONS: <docs/lessons/<文件>.md | 无>；库维护：<引用记录、删除、淘汰、路径修复 | 无>；流程观察：<...>；可固化建议：<...>
NEXT: what needs the user (approvals, follow-ups, next run), and anything skipped or descoped with why
```

<!-- host:claude-code -->
In workflow mode a run is one Workflow call.
<!-- /host -->
In prompt mode a run is one stretch of work between user prompts.
The user's reply starts the next run and resets the spawn count. On the
final run: revoke the budget grant if one was made, do the `## Retrospective`,
set the manual status to 已完成 with the date, run
`python3 -I "${CLAUDE_PLUGIN_ROOT}/bin/miniplan.py" check <plan>`, and list
anything still not verified. Nothing is
reported as done without a pass line with evidence.

## Anti-patterns

- Reporting the builder's VALIDATION as verification.
- Fixing the gate's findings in the main thread and skipping the re-gate.
