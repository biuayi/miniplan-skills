---
name: agents
description: Base layer of miniplan, auto-loaded at session start. Defines the agent roles, model routing, the per-request subagent budget and how an approved run may raise it, read-only fan-out, and the Task Contract / Compact Result formats used by miniplan:brainstorming, miniplan:plans, and miniplan:working. Consult before delegating; not for trivial atomic work.
---

# Agents (miniplan base layer)

The main conversation owns decomposition, assignments, user communication,
integration, and the final answer. Preserve the user's main
model, authorization boundaries, and decision ownership. Children never delegate
and never talk to the user. `miniplan:brainstorming`, `miniplan:plans`, and
`miniplan:working` reference this file for roles, budget, and contracts.

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

## Routing (Qwen Code)

Select the role by `subagent_type` only, spelled as the bare role name (for
example `scout`; Qwen Code addresses extension agents by bare name). Never use
`general-purpose`, `fork`, or an agent outside this table. The extension's
PreToolUse hook denies these and any call over budget.

| Role (`subagent_type: <role>`) | Responsibility |
| --- | --- |
| `scout` | Locate facts, files, APIs, execution paths. Read-only. |
| `runner` | Run a bounded command or collection plan, return raw evidence. |
| `builder` | Implement one approved, bounded change. |
| `reviewer` | Correctness, security, regression, test-coverage findings on a diff. Read-only. |
| `verifier` | Independently run acceptance checks, report evidence. Read-only. |
| `critic` | Falsify a design draft or plan with cited evidence before work starts. Read-only. |
| `designer` | Isolated design pass; only to offload context. |
| `judge` | Resolve conflicting evidence. Only on user request or a two-gate conflict. |

Every role runs on the main conversation's model; the read-only roles cannot
write or edit files. A user-level `~/.qwen/agents/<role>.md` with the same name
replaces the extension's role, which is how a role gets its own `model:`.

Escalate by choosing a different role (`critic` or `judge`), never by
re-running the same role on another model.

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

Concurrency. Qwen Code bounds how many Agent calls run at once.
Agents started by a Workflow run are not bound by it; their concurrency is the
`并发` header of the manual (`测试并发` for verifiers).

Two budget modes:

- Workflow mode: the manual header `预算` is the cap for the whole manual. The
  run script counts every agent it starts and stops dispatching at the cap; the
  per-request counter and `grant` below do not apply.
- Prompt mode: the per-request counter above applies to every Agent call.

Raising the budget in prompt mode: when a `miniplan:plans` manual needs
more spawns per user prompt than 5 and the user agreed at approval time, the main
thread runs once, from its own Bash tool:

```bash
bash "$HOME/.qwen/extensions/miniplan/hooks/agent-guard.sh" grant <N>    # this session only
bash "$HOME/.qwen/extensions/miniplan/hooks/agent-guard.sh" status       # used / budget
bash "$HOME/.qwen/extensions/miniplan/hooks/agent-guard.sh" revoke       # at the end of the run
```

The grant is keyed to the current session. Grant only on approval recorded in
the manual header, and never skip a gate under it.

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
