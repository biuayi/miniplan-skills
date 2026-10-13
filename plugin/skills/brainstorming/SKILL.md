---
name: brainstorming
description: Use when a request is broad, loosely specified, or spans several modules or steps without explicit acceptance criteria — wording like 整体/全面/整理/梳理/盘点/调研/优化一下/重构一下/把X做起来/接入一下/有哪些能力, or a multi-part ask whose boundaries and "done" are fuzzy. Splits the problem into decisions, gets each decision explicitly from the user, writes a design draft, has a critic falsify it, and stops for approval before any implementation. Not for single-file fixes, direct questions, or requests that already state scope and acceptance. Ends by handing off to miniplan:plans.
---

# Brainstorming

Turn a vague request into an approved design. The main conversation owns the
dialogue, the design, and every decision. User-facing text is in the user's
language. Roles, budget, and contracts come
from `miniplan:agents`.

<HARD-GATE>
No implementation action (edit, side-effecting command, `builder` spawn,
invoking `miniplan:plans`) until the user has explicitly approved the design.
Silence, an unanswered question, or "差不多吧" is not approval. This holds on
every path below without exception.
</HARD-GATE>

## Phase 0: Triage (one line to the user)

Say which path you are on before anything else:

| Path | Signal | Questions | Output |
| --- | --- | --- | --- |
| Spike | Investigation, inventory, or feasibility: 整理 / 盘点 / 调研 / 有哪些能力 / 看看能不能 | 1 (audience and granularity), then investigate | report in chat, then re-triage if it turns into work |
| Bounded | One module or subsystem; acceptance fuzzy | <= 3 | short design file, one approval |
| Architectural | Several modules, unknown acceptance, new interfaces, or 整体/全面 wording | <= 6 in <= 3 rounds | full design file, falsified, approved |

Clear scope and acceptance with one write scope is none of these: leave this
skill and do the work. Triage escalates only: a Bounded task that uncovers a
second subsystem becomes Architectural, never the reverse.

## Phase 1: Read before asking

Ground every question in facts. Read the code, docs, or device the request
touches; past the base layer's fan-out trigger, send `scout`s instead. A
question a scout could answer is not asked.

Spike path: the investigation itself is this phase. Ask the one question,
fan out scouts by module, then write the report (what exists, grouped the way
the audience thinks, each claim with a file pointer; gaps and risks last).

## Phase 2: Split the problem into decisions

Walk five dimensions and list only what is still unknown:

1. Outcome: what "done" looks like to the user, and for whom.
2. Boundary: what is out of scope; what must not be touched.
3. Acceptance: how the user will check it (command, behaviour, artifact).
4. Constraints: environment, compatibility, deadline; destructive,
   credentialed, or external actions that need per-step approval.
5. Tradeoff: when speed, thoroughness, and minimal diff conflict, which wins.

Each unknown becomes one decision. Ask with AskUserQuestion: one decision per
question, at most two questions per call, 2-4 options each, the recommended
option first and marked "(Recommended)", with one line on why. Where
AskUserQuestion is unavailable (Codex), ask in plain text, one question per
message. A question whose answer would not change the design is not asked.

Record every answer in the design's `## Decisions` as
`D<n>: <question> — chose <option> — because <reason>`. Decisions the user
delegated back ("你定") are recorded the same way with "delegated" and your
reasoning; they are still shown at approval.

## Phase 3: Design

Propose 2-3 approaches with tradeoffs, recommended one first, YAGNI applied
to each (strip every feature the decisions did not ask for). Write the design
from `references/design-template.md`. The main thread writes it; spawn
`designer` only when the design needs to read more code than the main context
should hold.

Self-review before falsification: placeholder scan (TBD / TODO / 处理边界 /
"similar to"), internal consistency (names, interfaces, paths agree across
sections), scope creep (anything not traceable to a decision), ambiguity
(two readers would build different things). Fix inline.

## Phase 4: Falsify (Architectural always; Bounded when risk warrants)

Spawn one `critic` (`subagent_type: miniplan:critic`) with the contract in
`references/falsify.md`. The contract
must carry a must-read list: the design file, the files the design claims
facts about, hooks or configs it depends on, anything it replaces, and the
source it says it borrows from.

Adjudicate every objection yourself: accept (change the design), reject
(state why, with evidence), or escalate (becomes a new decision for the user).
Record the table in `## Falsification`. One round by default; a second only
when the first changed the design materially.

## Phase 5: Approve, then hand off

Present the design with Decisions and Falsification visible. Ask for approval
as a decision: approve / change (what) / stop. On approval, say so, then
invoke `miniplan:plans` with the design file path. On "change", edit the file
and re-present the changed sections only.

Spike path: present the recommendation report instead, then re-triage the
request as Bounded or Architectural with the user.

## Output

`docs/miniplan/YYYY-MM-DD-<topic>-design.md` under the current working
directory. Bounded designs use the same template with short sections; do not
drop sections, write "none" where that is the truth.

## Anti-patterns

- Asking what the code answers, or six questions in one message.
- Options without a recommendation; a recommendation without a reason.
- Skipping the falsifier because the design "feels solid".
- Adjudicating objections by deleting them.
- Treating an answered AskUserQuestion as approval of the whole design.
- Starting `miniplan:plans` before the approval words exist in the transcript.
