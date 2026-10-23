---
type: regex
pattern: '希望.{0,6}(帮助|有用)|如有.{0,4}(问题|疑问)|欢迎.{0,4}(交流|反馈)'
match: not_contains
target:
  source: file
  path: report.md
---
不得以客套话收尾
