---
name: ci-green
description: >-
  Runs the same checks as GitHub Actions locally and fixes failures without
  weakening CI. Use when CI fails, when making a PR green, or when the user
  asks to run CI locally.
disable-model-invocation: true
---

# CI green

## When to use

- CI fails, making a PR green, or user asks to run CI locally

## Instructions

1. Read `.github/workflows/*.yml` in the current repo. Recreate the same commands locally.
2. If there is no workflow, report that CI is undefined. Do not invent passing checks.
3. Fix the code or tests. Do not delete jobs, add `continue-on-error` to hide failures, or skip required checks.
4. Prefer Linux GitHub-hosted runners. Add macOS only when the repository requires it.
5. Report the exact commands that must pass before merge.

## Done when

Local commands matching the workflow pass, or the remaining failures are reported without weakening CI.
