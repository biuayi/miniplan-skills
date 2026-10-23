---
type: regex
pattern: '^(?=[\s\S]*(?<![\d.])3(?![\d.%]))(?=[\s\S]*40%)(?=[\s\S]*99\.95%)(?=[\s\S]*Lattice)'
target:
  source: file
  path: draft.md
---
Three numbers and the product name are kept
