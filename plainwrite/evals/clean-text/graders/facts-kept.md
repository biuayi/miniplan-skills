---
type: regex
pattern: '^(?=[\s\S]*(?<![\d.])5(?![\d.%]))(?=[\s\S]*(?<![\d.])8(?![\d.%]))(?=[\s\S]*0\.1%)(?=[\s\S]*(?<![\d.])120(?![\d.%]))'
target:
  source: file
  path: note.md
---
四个数字都要保留
