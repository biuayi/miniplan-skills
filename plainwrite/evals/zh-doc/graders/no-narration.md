---
type: regex
pattern: '我先|接下来我|下面我来'
match: not_contains
target:
  source: file
  path: report.md
---
不得在文档里夹带过程旁白
