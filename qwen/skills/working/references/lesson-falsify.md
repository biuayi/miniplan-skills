# Lesson falsification contract (send to `critic`)

Used at the end of a manual when a candidate lesson is added or two lessons are merged. The target is a candidate lesson entry for `docs/lessons/`, not a design draft. Fill every field. Do not forward the conversation.

```text
OBJECTIVE: Falsify the candidate lesson at <entry file path or the entry text
  under review> for the project's `docs/lessons/`. Treat each judgement line
  in its evidence as a claim to overturn. Find where a claim is not backed by
  the raw log and the change, where the lesson is a process lesson, where its
  grain is wrong, where it duplicates an existing entry, or where it will
  mislead a later design.
SCOPE: Read-only. Must read, in this order:
  1. The candidate entry and the judgement lines it rests on
  2. The gate logs those lines cite (paths: <log paths>)
  3. The repair commits' changes (<commit range or diff command>)
  4. The output of `miniplan.py lessons`
  5. Existing entries that may duplicate it (<docs/lessons/ files>)
  6. The paths listed in the entry's 作用对象
  Do not fetch the web unless listed here.
CONTEXT: <3-6 lines: the project, the manual topic, what the candidate claims,
  and the entry rules: a lesson must name a repository path, must be
  repeatable on a different task, and 有效 means the same acceptance command
  failed before the fix and passed after it, one cause fixed, no retry>
CONSTRAINTS: Do not restate the entry. Do not edit any file.
ACCEPTANCE: Return, in <user language>:
  1. For each judgement line: backed or not by the raw log and the change,
     the quoted failing line, and whether it should be 无法归因.
  2. Objections by severity (high/medium/low), max 8. Each: the entry text
     targeted, the conflicting evidence, a failure scenario (input -> wrong
     outcome), the fix or the decision the owner must make. Cover: process
     lesson that holds in an unrelated repository; grain too broad or too
     narrow; duplicate of an existing entry; process markers (task, decision,
     acceptance or round numbers) or links to `docs/miniplan/` outside
     backticks; paths in 作用对象 that do not exist.
  3. Tried to refute and could not (2-4 items): what you checked, why it held.
  4. Intuitions without evidence (<= 2, may be empty).
OWNERSHIP: read-only
BUDGET: 25 tool calls / 10 minutes; at the limit return partial.
RETURN: STATUS / SUMMARY (<= 3 lines) / then sections 1-4. Under <N> words.
```

Adjudication, written in the manual's `## 复盘` as a table:
`# | severity | objection (one line) | evidence | ruling: accept -> <change> | reject -> <why>`

An accepted objection that removes the candidate's support turns the conclusion into `经验：无`.
