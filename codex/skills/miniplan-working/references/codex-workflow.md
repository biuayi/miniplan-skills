# Codex script execution

Requires Node.js 18 or later, Python 3.11 or later, Git, and a configured Codex
CLI with `exec`, JSON events, output schemas, and standalone profiles. The
adapter uses existing Codex authentication and provider settings. It does not
ask for a new API key or change the main conversation's model.

## Commands

```bash
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md --dry-run
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md
```

`--output-dir` chooses where evidence is retained; otherwise it lives under
the repository's Git metadata. `--codex-bin` selects the installed CLI
executable, including a fake executable for deterministic tests.

Only the plan path is accepted as scheduling input. The adapter invokes
`miniplan.py args <plan> --host codex` to check approval, lint, integration
branch, and tracked changes. It never trusts caller-supplied expanded tasks.
Dry-run validates the manual and role files without launching Codex or creating
worktrees. It may add `.codex/worktrees/` to Git's local exclude file.

## Role and resource boundaries

Each launch reads the role from `CODEX_HOME/agents/<role>.toml`, defaulting to
`~/.codex/agents/`. A private temporary profile carries the role-owned settings
into `codex exec --profile <name>`; it is removed after the process exits.
Missing or invalid roles stop the run. No generic fallback role is selected.
The child process cannot delegate further. Its sandbox is retained and the
noninteractive approval policy rejects operations requiring new approval.

The approved manual controls scheduling. `并发` defaults to 6 active tasks;
`测试并发` defaults to 3 concurrent verifier calls. These are separate
semaphores. Parallel readers or gates in one task can make the number of live
role processes exceed the task-slot count. The interactive Agent tool's
three-thread limit, per-request five-child budget, and
`CODEX_AGENT_GUARD_BUDGET` do not apply to this script mode.

`预算` must be an explicit nonnegative integer and caps total role launches
for this manual, including readers, builders, gates, repairs and merge runners.
The adapter persists consumption in Git common metadata under the plan lock.
Rerunning, changing user request, or changing a legacy `--request-id` token
cannot reset consumption. An approved increase of the manual budget raises
the available allowance. A zero or exhausted budget returns blocked outcomes
without launching another role. Other manual lint errors still block preflight;
the estimated graph dispatch count does not prevent reporting exhaustion.
Do not rename a running manual or remove its accounting file to renew budget.

The manual's setup and slot environment commands remain explicit inputs.
Project rules take priority over template examples: keep the project's page
port, test selection command, author identity, comment rules, and standing
commit/push authorization. Parallel worktrees do not authorize extra page
ports or broader tests.

## Results and recovery

The adapter validates each structured result and retains JSON events,
stderr, role information, and final outcomes in a private evidence directory.
Malformed responses, failed Codex turns, exhausted budgets, and failed gates
produce nonzero status. A builder's self-report never substitutes for a gate.
Only passing gates allow the serialized merge stage to integrate a change.

Codex protects `.git` in the workspace sandbox. The host script therefore
creates registered task worktrees, stages only checked ownership paths,
commits with the existing author, and merges after an independent runner
preflight and a second deterministic merge check. Builders only edit files
and run their checks; they return an empty commit field. No role sandbox is
expanded. The host records Git operation exit codes and verifies integration
HEAD and task-branch ancestry before recording completion. Conflicts are
aborted in the integration copy; one reverse merge and builder repair may run
in the task worktree, followed by the independent gates again. Conflicts
outside the builder's ownership block execution.

Successful ledger lines are applied through `miniplan.py ledger`. The adapter
keeps a per-plan lock so two script runs cannot mutate the same plan
simultaneously. If a process is interrupted, inspect the result, ledger,
worktrees, and lock before resuming; never delete an unverified active lock.

Root `main` tasks still belong to the main conversation. Execute their checks
and ledger them before resuming downstream tasks. Tasks with a completed
ledger entry are skipped. Unfinished branches and worktrees remain available
for inspection and repair.

## Official references

- [Non-interactive Codex](https://developers.openai.com/codex/noninteractive/):
  scripts, JSON events, structured outputs, and existing CLI authentication
- [Codex SDK](https://developers.openai.com/codex/sdk/): programmatic threads
- [Configuration profiles](https://developers.openai.com/codex/config-advanced/):
  named standalone configuration layers
- [Custom agents](https://developers.openai.com/codex/subagents/): role-owned
  model, effort, instructions, and sandbox settings

## Implementation boundary

This is an adapter over the official noninteractive `codex exec` interface,
not an invocation of Claude Code's native `Workflow` tool. It reuses the
miniplan JavaScript scheduler. Claude's `Workflow`/`Stop` hook enforcement is
not installed on Codex; the script provides its own plan lock and exit status.
Commands that the named role's sandbox cannot execute remain blocked, and
manual `main` tasks still require the main conversation.

When upgrading from the earlier adapter, same-plan archived call evidence is
imported once under the plan lock. Legacy request counters are not reused
because they may mix manuals. Missing or damaged associated evidence blocks
migration instead of silently granting fresh budget.
