---
type: regex
pattern: '^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}[：:]\*\*|^\s*(?:[-*]\s+)?\*\*[^*\n]{1,30}\*\*[：:]'
flags: m
match: count:0
target:
  source: file
  path: report.md
---
不得出现行首加粗标签
