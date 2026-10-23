---
type: regex
pattern: '^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}:\*\*|^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}\*\*:'
flags: m
match: count:0
target:
  source: file
  path: draft.md
---
No bold labels at line start
