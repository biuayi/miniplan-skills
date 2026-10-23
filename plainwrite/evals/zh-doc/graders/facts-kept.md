---
type: regex
pattern: '^(?=[\s\S]*(?<!\d)12(?!\d))(?=[\s\S]*(?<!\d)820(?!\d))(?=[\s\S]*(?<!\d)310(?!\d))(?=[\s\S]*(?<!\d)47(?!\d))'
target:
  source: file
  path: report.md
---
四个关键数字都要保留
