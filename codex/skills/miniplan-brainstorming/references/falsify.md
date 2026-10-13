# Falsification contract (send to `critic`)

Fill every field. Do not forward the conversation.

```text
OBJECTIVE: Falsify the design draft at <design file path>. Find where it
  contradicts itself, contradicts the real constraints of this environment,
  borrows from its stated sources incorrectly, adds cost without value, or
  will fail in practice.
SCOPE: Read-only. Must read, in this order:
  1. <design file>
  2. <files the design claims facts about: paths>
  3. <hooks / configs / role files it depends on>
  4. <what it replaces or migrates away from>
  5. <source material it says it borrows from, if local>
  Do not fetch the web unless listed here.
CONTEXT: <3-6 lines: who the user is, the hard constraints (budget, hooks,
  permissions), what "done" means to the user>
CONSTRAINTS: Every objection needs evidence you read (path:line or quote).
  Opinions without evidence go in a separate list of at most 3 items. Critique
  what is there; no wholesale alternative architecture. Do not restate the
  design.
ACCEPTANCE: Return, in <user language>:
  1. Objections by severity (high/medium/low), max 10. Each: the design text
     targeted, the conflicting evidence, a failure scenario (input -> wrong
     outcome), the fix or the decision the owner must make.
  2. Tried to refute and could not (3-6 items): what you checked, why it held.
  3. Source comparison: where the design claims to borrow from <source>, what
     it borrowed wrongly or left out (cite the source).
  4. Intuitions without evidence (<= 3, may be empty).
OWNERSHIP: read-only
RETURN: STATUS / SUMMARY (<= 3 lines) / then sections 1-4. Under <N> words.
```

Adjudication table for the design's `## Falsification`:
`# | severity | objection (one line) | evidence | ruling: accept -> <change> | reject -> <why> | escalate -> D<n>`
