---
type: regex
pattern: '^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}[：:]\*\*|^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}\*\*[：:]'
flags: m
match: count:0
target:
  source: file
  path: note.md
---
不得加入行首加粗标签
