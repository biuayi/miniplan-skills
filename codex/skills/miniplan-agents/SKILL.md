---
name: miniplan-agents
description: Base layer of miniplan, loaded via $miniplan-agents. Defines the agent roles, model routing, the per-request subagent budget and how an approved run may raise it, read-only fan-out, and the Task Contract / Compact Result formats used by $miniplan-brainstorming, $miniplan-plans, and $miniplan-working. Consult before delegating; not for trivial atomic work.
---

# Agents (miniplan base layer)

Installed as a Codex plugin, these skills are listed as `miniplan:<name>` (for example `miniplan:miniplan-agents`); a reference such as `$miniplan-agents` means that skill.

`<miniplan-agents>` below is the absolute directory of the `miniplan-agents` skill as listed among your skills (`~/.codex/skills/miniplan-agents` for a script install); expand it before running a command.

The main conversation owns decomposition, assignments, user communication,
integration, and the final answer. Preserve the user's main
model, authorization boundaries, and decision ownership. Children never delegate
and never talk to the user. `$miniplan-brainstorming`, `$miniplan-plans`, and
`$miniplan-working` reference this file for roles, budget, and contracts.

## Delegate Only When It Pays

Delegate when at least one holds:

- Two or more independent read-only workstreams can run at once.
- Exploration, long commands, or raw output would crowd the main context.
- An implementation needs an independent gate that the risk or the user demands.
- The user explicitly asks for agents or parallel work.

Otherwise do it in the main thread. Never spawn to fill a slot.

Read-only fan-out trigger: material spanning more than one directory or
module, or more than about five files or 20 KB. Send one `scout` per module,
at most three concurrent, read-only, each returning a compact evidence map;
read only the maps and never `cat` a source tree into the main context.


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
## Suggested Budgets

Children have no built-in stopping point; a contract without a budget lets one
run take 40+ minutes. Put a `BUDGET:` line in every contract. Defaults:

| Role | Tool calls | Wall minutes | Other |
| --- | --- | --- | --- |
| `scout` | 15 | 10 | evidence map only |
| `runner` | 10 | the command's own runtime | no interpretation |
| `builder` | 40 | 25 | targeted checks only, never full suites |
| `reviewer` | 30 | 15 | the diff, not the repo |
| `verifier` | the CHECK's commands | their runtime | each full suite at most once |
| `critic` | 30 | 10 | must-read list first |
| `designer` | 40 | 20 | at most 8 screenshots for self-checks |

A budget is advisory; no hook enforces it. On reaching it the child stops and
returns `partial`, saying what is left. Raise it in the contract when the task
needs more, never by silence.

## Prompt mode budget: 5 Children per User Request

The hook counts spawns per user prompt and denies the sixth. Harness-injected
turns (a subagent's completion notice, an auto-continue nudge) do not reset
the counter; only a real user prompt does. Spend it so:

- Fill a wave with `scout`/`runner` first.
- Parallel builders get disjoint write scopes and one git worktree each; a lone
  builder may work in the main working copy.
- One gate by default: `verifier` when there are tests or a reproduction to run,
  `reviewer` when the risk is logic or security. Both only for high-risk changes
  with budget left.
- `critic` once per design draft in brainstorming; `judge` and a second repair
  round only when the user asks.
- Main does design, triage, integration, and the final report itself.

Prompt mode on Codex: at most three child threads active at once.

Raising the prompt-mode budget on Codex: there is no per-session grant. Export
`CODEX_AGENT_GUARD_BUDGET=<N>` before launching `codex` for a run the user
approved at manual time; otherwise split the work across user prompts of 5.

Script mode uses the manual's `并发` task slots (default 6), separate
`测试并发` verifier semaphore (default 3), and whole-manual `预算`.
Interactive thread limits and request counters do not cap these CLI processes.
Consumption persists across resumes; raising the approved manual budget is
required to authorize further launches after exhaustion.

Typical shapes: investigation = 2-3 `scout` in one wave; implementation =
(1-2 `scout` in parallel) -> main designs -> 1 `builder` -> 1 gate; command
collection = 1 `runner`, interpret in main. When the budget is exhausted, finish
in the main thread; the next user prompt resets the counter.

## Ready Set and Waves

Before the first spawn, fix each task's role, dependencies, write scope, and
acceptance criteria. A task is ready when its dependencies are complete and its
inputs will not change concurrently. Dispatch every ready independent task in
the same assistant turn before waiting; `spawn -> wait -> spawn` is wrong when
both were ready. Refill a freed slot with newly ready work. Join all required
results at a phase boundary and synthesize once.

Keep tasks sequential when one consumes another's result, when two may touch the
same file, interface, schema, lockfile, or generated output, or when a gate
would inspect a diff still being edited. When independence is uncertain, add
the dependency.

Parallel writers get explicit non-overlapping ownership, unique temp paths,
and each its own git worktree (every command starts with `cd <worktree> && `,
because a child's `cd` does not persist between Bash calls);
no repository-wide formatters, generators, or dependency updates alongside
another writer. A failed node blocks only its dependents. Retry at most once,
only with changed inputs; never on unchanged input.

## Task Contract (send)

```text
OBJECTIVE: one measurable outcome
SCOPE: allowed files, systems, or questions
CONTEXT: only relevant facts and references
CONSTRAINTS: permissions, compatibility, explicit non-goals
ACCEPTANCE: observable completion criteria
OWNERSHIP: files it may edit, or "read-only"
BUDGET: tool calls / wall minutes / screenshots (see Suggested Budgets)
RETURN: required evidence and result format
```

Do not forward the conversation. Never give concurrent builders overlapping
ownership. When a role's default framing does not fit the artifact (a
`reviewer` asked to read a design, a `critic` asked to read a diff), the
OBJECTIVE and RETURN must say so explicitly; the role file's default wins
otherwise.

Process vocabulary never enters an artifact. Use task ids (`T1`, `P2`), phase
and round numbers, and pointers to plan or design sections in contracts,
results, and the ledger only -- never in code, comments, test names, filenames,
or commit messages. There, write the fact the id stands for: `// T2: same orderNo relock`
becomes `// a repeated lock on the same orderNo returns the same ICCID`.
Identifiers a reader can still resolve months later -- issue numbers,
specification clauses, RFCs -- are exempt. Every contract sent to a `builder`
carries this in CONSTRAINTS.

## Compact Result (receive)

```text
STATUS: complete | partial | blocked
SUMMARY / EVIDENCE / CHANGES / VALIDATION / RISKS / NEXT
```

Raw logs stay out of the main conversation: the child stores them in a temp
artifact and returns the path plus the decisive excerpts.

Delegation grants no new authority. Destructive, external, credentialed, or
production-affecting actions keep the main conversation's approval requirements.
