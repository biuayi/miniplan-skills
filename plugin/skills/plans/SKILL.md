---
name: plans
description: Use after a design has been approved through miniplan:brainstorming, or when the user hands over an approved design file, to turn it into a task manual — tasks with dependencies, deliverables, executable acceptance checks, per-agent prompts, agent assignments, and a spawn budget. Stops for approval of the manual, then hands off to miniplan:working. Not for designing (miniplan:brainstorming) or executing (miniplan:working).
---

# Plans

Input: an approved design file. Output: a task manual the `working` skill can
execute without re-deriving anything, saved as
`docs/miniplan/YYYY-MM-DD-<topic>-plan.md` from `references/plan-template.md`.
The main conversation writes the manual; children only gather facts. Roles,
budget, and the Task Contract come from `miniplan:agents`.

## Before writing

- Read the design. Every acceptance item A<i> must end up covered by a CHECK.
- Read the code the tasks will touch: exact paths, signatures, existing test
  commands, build steps; past the base layer's fan-out trigger, send `scout`s.
  CHECKs and PROMPTs are built from names you read, never from names you
  expect.
- Scope check: a design spanning independent subsystems gets one manual per
  subsystem, sequenced, not one manual with forty tasks.

## Header

Beyond title, design file, and `状态：草稿`, the header carries:

```text
集成分支：<branch>       the run starts with the main working copy on this branch
并发：6                  tasks in flight at once; default 6
测试并发：3              verifiers in flight at once; default 3
预算：<N>                total agents for the manual = base spawns + repair margin
工作树准备：<shell>       optional; first command in a new worktree, e.g. npm ci --prefer-offline
槽位环境：<shell>         optional; per-slot ports etc., keyed on MINIPLAN_SLOT, e.g.
                         export EIM_WEBUI_PORT=$((4300+10*MINIPLAN_SLOT)) EIM_MOCK_WORKERS=2
```

`miniplan.py lint` prints the base spawns and the repair margin; set `预算` to
base plus a margin for one repair per builder task.

## Task block

```text
T<n> <title>
DEPENDS  T<k>, T<j>@<resource> ... | none
USES     <resource>, ...          (optional)
REALIZES A<i>, ... | internal   (which design acceptance items this task delivers)
GOAL     one measurable outcome
DELIVER  files or systems changed; interfaces Consumes: ... Produces: ...
CHECK    command + expected result (exit code, output fragment, test name)
AGENTS   role + OWNS for each; "main" when the main thread does it
PROMPT   one filled Task Contract per agent (ACCEPTANCE = CHECK verbatim)
```

- No `ROUND` field; an old manual's `ROUND` lines are ignored.
- `DEPENDS T2, T3@e2e-live`: a plain id is a data edge (the task consumes the
  other's result); `@<resource>` is a resource edge (order only, no data). Every
  resource named after `@` appears in some task's `USES`, and two tasks that
  `USES` the same resource must be ordered by a chain of DEPENDS.
- `OWNS` is comma-separated, relative to the repo root: path prefixes (a
  directory ends with `/`) or globs (`*`, `**`).
- Roles in AGENTS: readers `scout`, `runner`; `builder`, at most one per task;
  gates `verifier`, `reviewer`, `critic`; `main`. `designer` and `judge` never
  appear in a manual. Every listed role has its own PROMPT segment, and every
  builder has OWNS.
- `main` tasks are for three cases only: an action that needs user approval, a
  step that needs the user in the loop, a trivial edit. A `main` task is a stop
  point of the run, so put it at a root or at the sink; the lint output prints
  the minimum number of runs a mid-graph `main` task forces.

## 箭线图 (arrow diagram): mandatory

Every manual opens with one activity-on-arrow network under `## 箭线图`, above
`## Tasks`. It is generated, never drawn by hand:

```bash
python3 -I ~/.claude/skills/miniplan/bin/miniplan.py diagram --write <plan>
```

`diagram` builds it from DEPENDS and `working` refreshes the status glyphs
through the ledger. A manual without the diagram is not ready to present. The
generated shape follows these rules:

- **Tasks are the arrows; the nodes are events.** An arrow is labelled
  `T<n> <title> <status>`; a node is a moment in time, written
  `E<k>(("<k>"))` with a circled numeral.
- **Numbering.** One start event ① and one end event. Every arrow runs from a
  smaller number to a larger one. A task with `DEPENDS none` leaves ①; a task
  nothing depends on enters the end event.
- **Dummy activities** — `-.->|"虚工作"|` — carry a dependency that no task
  performs. Two tasks sharing only part of their predecessors need one, and so
  do two tasks that would otherwise run between the same pair of events.
- **Resource edges** are dummy activities drawn `-.->|"资源:<name>"|`; the
  scheduler runs the two tasks in that order.
- **Status glyph**, one per arrow: `⏳未开始` `🔄进行中` `✅完成` `🔁返工`
  `❌失败`. Everything is ⏳ at planning time.
- **One line under the diagram**: `最长链：<n> 个任务（T1→T2→T4），至少 <n> 层`
  — the deepest chain of tasks, counted in tasks, and the tasks on it.
- There is no `## Rounds` section.

No arrow carries a duration or a date; the diagram's only length is the task
count along a chain, the floor on the number of layers. Do not edit the diagram
by hand: change DEPENDS and run `diagram --write` again; `lint` reports a
diagram that differs from the generated one.

## CHECK: executable acceptance, two cases

Prose is not a CHECK. Every CHECK is a command the gate will run and the
result it must show. A CHECK whose test body the task itself writes runs at
the gate, after the builder's step; that is not a manual defect.

- **The task REALIZES an A<i>**: the manual contains the test code itself — the
  test file body or the exact assertion block — written against interfaces
  named in DELIVER. If the interface does not exist yet, DELIVER defines it
  (signature, types) before the test refers to it.
- **Every other task**: the run command (`pytest path::case`, `go test -run
  Name ./pkg`; for docs, config, or device work, a scripted assertion that the
  file exists, the section is present, or the device prints the expected
  state), the case names, one assertion per line. The task writes the bodies;
  the gate runs the command.

These are plan failures: "TBD", "TODO", "处理边界情况", "add appropriate
error handling", "同 T<n>", "为上述内容写测试" without the test text,
"run the tests" without naming them.

## Sizing and ordering

- A task is the smallest unit with its own CHECK. Merge tasks that share one
  CHECK; split a task that needs two.
- **Split wide.** If B depends on A only through A's interface, carve an
  interface task out of A (types, signatures, stubs, contract tests) and run it
  first; A's implementation then runs in parallel with B. A manual with N ≥ 4
  tasks and width 1 carries a header line, `串行理由：<why it cannot be split wide>`.
- **Test selection.** The CHECK of a task that is not a sink uses only the
  project's change-selecting test command. The full suite runs once, in the
  sink task's final gate: a task with a verifier and no builder, run on the
  integration branch. `lint` warns when a non-sink CHECK contains `./...` or a
  full-suite script name.
- Tasks with disjoint OWNS and no dependency run in parallel; tasks that touch
  the same file, schema, lockfile, or generated output are ordered by DEPENDS
  or a resource edge.
- Trivial edits are `main` tasks: no spawn, still a CHECK.

## AGENTS and PROMPT

- A task may list several agents: a builder and its gate, two scouts on
  disjoint questions, a runner collecting evidence before a builder. Each
  gets its own Task Contract with OBJECTIVE from GOAL, ACCEPTANCE equal to
  CHECK, OWNERSHIP equal to OWNS, and CONTEXT holding only the facts that
  agent needs — never the conversation, never the whole design.
- Gate per task: `verifier` when CHECK is runnable, `reviewer` when the risk
  is logic or security, both only for high-risk tasks. AGENTS names roles
  bare; `working` spawns them as `miniplan:<role>`.

## Budget

`预算` is the total number of agents the manual may spawn: every task's
readers, builder, and gates, plus one merge runner per builder task, plus a
repair margin. `lint` computes the base spawns and fails when they exceed
`预算`. The user approves the figure with the manual; if it is above the default
from `miniplan:agents`, say so in the approval question.

## Self-check before presenting

1. Coverage: each A<i> maps to at least one CHECK; each CHECK maps back.
2. Consistency: names, paths, signatures agree across tasks and with the
   design; interfaces a CHECK refers to are defined in some DELIVER.
3. Run `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py diagram --write <plan>`,
   then `python3 -I ~/.claude/skills/miniplan/bin/miniplan.py lint <plan>`. Present
   the manual only when lint exits 0: it covers header keys, the nine task
   fields, dependencies and resources, roles and OWNS, plan-failure phrases, the
   diagram, width, and budget. Read its warnings; a mid-graph `main` task or a
   full-suite CHECK on a non-sink task needs a reason or a rewrite.

## Approve, then hand off

Present the manual with the lint summary line. Ask for approval as a decision:
approve / change (what) / stop. State the `预算` figure; if it is above the
default budget, ask in the same question whether to raise it for this run. On
approval, write the status line `状态：已批准（YYYY-MM-DD）` into the header and
invoke `miniplan:working` with the manual path. On "change", edit, rerun
`diagram --write` and `lint`, and re-present the changed tasks only.

## Anti-patterns

- A CHECK written from memory of an API instead of a read signature.
- Ten tasks and one gate at the end.
- Interfaces that appear in T7 but were never defined in any DELIVER.
- A serial chain of N ≥ 4 tasks with no `串行理由` and no interface split.
- A full-suite command in the CHECK of a task that is not a sink.
- A shared event standing in for a 虚工作, so two unrelated tasks appear to
  wait on each other.
