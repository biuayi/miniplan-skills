# Codex Adapter

Use the named personal agents under `~/.codex/agents/`. The fixed roles bind to
the custom `llm` provider; `designer` omits model settings so it inherits the
main conversation.

## Routing

| Agent | Provider | Model | Effort |
| --- | --- | --- | --- |
| `designer` | inherit | inherit | inherit |
| `builder` | `llm` | `gpt-6.1-sol` | `high` |
| `reviewer` | `llm` | `gpt-6.1-sol` | `high` |
| `scout` | `llm` | `gpt-6-luna` | `medium` |
| `verifier` | `llm` | `gpt-6-luna` | `medium` |
| `critic` | `llm` | `gpt-6.1-sol` | `high` |
| `runner` | `llm` | `gpt-6-luna` | `low` |
| `judge` | `llm` | `gpt-6.1-sol` | `xhigh` |

## Prompt mode invariants

- Keep fixed role routing on the models listed above; do not select Grok automatically.
- Keep the main conversation on the model selected by the user, including a manual
  `/model` selection of Grok; `designer` inherits that selection.
- Spawn the named custom role instead of `default`, `worker`, `explorer`, or an unrouted agent.
- Do not pass `model`, `reasoning_effort`, or `model_reasoning_effort` in a spawn call.
- Do not configure `agents.default_subagent_model` or `agents.default_subagent_reasoning_effort`.
- Keep at most three child threads active and wait for required results.
- Use minimal context inheritance where the host supports it; pass the task contract explicitly.
- A live parent permission or sandbox override can supersede an agent-file default. Preserve the role's read/write boundary in the assignment as well.
- Inspect `/agent` when the selected custom role needs confirmation.

Agent instructions prohibit nested delegation. Do not work around that boundary
with a generic spawn.

## Prompt mode budget: 5 Children per User Request

The `PreToolUse(Agent)` hook runs `agent-guard.sh` before every spawn: from
`~/.codex/hooks.json` for a script install, or from the plugin's
`hooks/hooks.json` once it is trusted in `/hooks`. The guard keys its atomic
counter by Codex `session_id` and `turn_id`, then denies unrouted roles,
per-call model or effort overrides, and the sixth spawn in one user request.
Do not work around a denial.

- Up to 3 children may run concurrently; dispatch the ready wave before waiting.
- Use 1 Builder by default. Use 2 only for a large change with disjoint write ownership.
- Use 1 gate by default: Verifier for executable acceptance checks, Reviewer for logic or security risk.
- Use both gates only for high-risk work when budget remains.
- Use Judge and a second repair round only when the user asks.
- When the budget is exhausted, finish in the main thread. The next user prompt has a new `turn_id` and therefore a fresh budget.

The budget limits total spawns, not simultaneous threads. A completed child does
not refund a spawn.

## Scripted workflow execution

`node <miniplan-agents>/scripts/codex-run.mjs <plan>` runs the
shared scheduler through `codex exec`. The adapter loads each named role's
TOML file into an ephemeral configuration profile, preserving its provider,
model, effort, sandbox, and developer instructions. It does not set a default
subagent model or supply per-call model/effort flags. Nested delegation is
disabled in these processes.

Script mode follows the approved manual: `并发` is the number of active tasks
(default 6), `测试并发` limits verifier calls separately (default 3), and
`预算` caps launches across the whole manual. Readers and gates may launch
multiple roles within a task slot; task slots are not a global process cap.
The interactive three-thread/five-child limits and `CODEX_AGENT_GUARD_BUDGET`
apply to prompt mode only. The adapter persists whole-manual consumption
across resumes and does not reset it for a new user request. Read the working
skill's Codex workflow reference for preflight, evidence, locking, and resume.

## Parallel Dispatch

- Build the ready set and task contracts before calling `spawn_agent`.
- For every ready wave, call `spawn_agent` for all selected named roles before the first `wait_agent` or equivalent wait.
- Disable parent-context inheritance by default with `fork_turns="none"` or `fork_context=false`, whichever the active tool schema exposes, and pass the bounded task contract explicitly. Inherit prior turns only when the task cannot be explained compactly.
- Record returned thread IDs. When one finishes, process its compact result and dispatch newly unblocked work while other threads continue.
- At a phase barrier, wait for every required thread and synthesize once; do not repeatedly paste partial results into the main context.
- A series shaped like `spawn_agent -> wait_agent -> spawn_agent` is incorrect when both tasks were ready at the same time.
