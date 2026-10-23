---
type: regex
pattern: 'Let me|I''ll start|Here''s (a|the) (quick )?(summary|update)'
match: not_contains
target:
  source: file
  path: report.md
---
No process narration inside the document
