# Codex script execution

Requires Node.js 18 or later, Python 3.11 or later, Git, and a configured Codex
CLI with `exec`, JSON events, output schemas, and standalone profiles. The
adapter uses existing Codex authentication and provider settings. It does not
ask for a new API key or change the main conversation's model.

## Commands

```bash
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md --dry-run
node ~/.codex/skills/miniplan-agents/scripts/codex-run.mjs /absolute/path/to/plan.md --request-id <request-token>
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

The scheduler limits live Codex processes to three, including parallel
readers, gates, and merge runners. It caps total launches by the manual's
approved budget and `CODEX_AGENT_GUARD_BUDGET`, defaulting to five. An increased
budget must be authorized before launching Codex. Earlier agents in the same
user request also consume that budget; finish within the remainder or wait
for the next user request. Never use another invocation as a budget reset.
Pass the same `--request-id` token on every invocation in one user request.
Its consumed launch count is persisted under Git metadata; a new user request
can use a new token. Account for interactive agents already used by setting
the initial script allowance to the remaining authorized count.

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
Only passing gates allow the serialized merge runner to integrate a change.

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
