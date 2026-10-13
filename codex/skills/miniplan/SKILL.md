---
name: miniplan
description: Main entry point of the miniplan pipeline. Invoke as $miniplan <request>, or $miniplan alone to resume unfinished work, for any broad, vague, multi-module, or investigation-type request (整理/梳理/盘点/调研/优化/重构/接入/把X做起来/有哪些能力). Detects the current stage from docs/miniplan/ and runs or resumes brainstorming -> plans -> working with the user's approval at each gate. Never skips a gate because it was invoked explicitly.
---

# $miniplan

It decides which stage to enter and hands off to that stage's skill; it does
no design, planning, or dispatch itself and spawns nothing. Roles, budget, and contracts come from `$miniplan-agents`. User-facing
text is in the user's language.

## 1. Read the arguments

- `$miniplan <request>`: the request text is the input to brainstorming.
- `$miniplan` alone: look for unfinished work first (step 2). If there is
  none, ask what to work on with one AskUserQuestion.

## 2. Detect the stage from `docs/miniplan/` in the current directory

Look only in `./docs/miniplan/` of the current working directory; never in a
parent, sibling, or guessed project directory. Read only the header lines of
`*-design.md` and `*-plan.md`, newest first. A file whose status line matches
none of the states below is treated as absent and mentioned in the one-line
report.

| Found | Enter |
| --- | --- |
| A plan whose header says 已批准 and is not 已完成 | `$miniplan-working`, resuming from its `## Progress` |
| A design whose status is 已批准 and has no plan for the same topic | `$miniplan-plans` with that design |
| A design in 草稿 or 已反证 status | `$miniplan-brainstorming` at the approval step for that file |
| Nothing, or a request naming a new topic | `$miniplan-brainstorming` with the request |

If the request text and the unfinished work disagree (a new topic while a
plan is mid-run), ask which one to take, one question, before anything else.

## 3. Hand off

Say in one line which stage you entered and what in `docs/miniplan/` decided
it. Then invoke the stage skill by name with the file path or the request
text. Do not paraphrase the request; pass the user's words.

## Rules that hold however this skill was entered

- Explicit invocation means "use the pipeline", not "skip the questions".
  Design approval and manual approval still need the user's words.
- Reading is delegated: past the base layer's fan-out trigger, the stage skill
  sends `scout`s and the main thread reads only their evidence maps.
- Investigation requests (整理 / 盘点 / 调研 / 有哪些能力 / 看看能不能) are
  the Spike path of brainstorming: one question on audience and granularity,
  scouts, a report. `plans` and `working` follow only if the report turns
  into work the user approves.
