---
type: regex
pattern: '不仅[^。]{0,40}更是|值得注意的是|赋能|希望.{0,6}帮助'
match: not_contains
target:
  source: file
  path: draft.md
---
套路用语必须改掉
