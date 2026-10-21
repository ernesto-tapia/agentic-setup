---
name: commit-message
description: Use when the user asks for a git commit message for their current changes.
---
# Write a commit message

1. Run `git diff --staged` with `run_shell` (if empty, run `git diff`).
2. Write a subject line under 60 characters in the imperative mood ("Add", "Fix", not "Added").
3. Leave a blank line, then 1-3 short bullet points explaining *why*, not just what.
4. Show the message to the user. Do not commit unless they ask.
