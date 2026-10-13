# Qwen Code Adapter

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
