---
type: regex
pattern: '^(?=[\s\S]*(?<![\d.])3(?![\d.%]))(?=[\s\S]*40%)(?=[\s\S]*99\.95%)(?=[\s\S]*Lattice)'
target:
  source: file
  path: draft.md
---
三个数字和产品名都要保留
