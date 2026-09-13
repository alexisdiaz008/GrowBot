---
name: gh-issue-workflow
description: >-
  Uses GitHub Issues as the only tracker via gh. Use when creating, triaging,
  or implementing from an issue.
disable-model-invocation: true
---

# GitHub issue workflow

## When to use

- Creating, triaging, or implementing from a GitHub issue

## Instructions

1. No second tracker. Issues + labels + `gh`.
2. Suggested labels (create on demand with `gh label create` if missing): `bug`, `feat`, `docs`, `chore`, `blocked`. Follow additional repository labels; do not invent Jira-like fields.
3. Create: title, body (problem, acceptance, out of scope), labels.
4. Implement: `gh issue view`, work on a branch named `type/issue-n-slug`, finish with `ship-pr` and `Fixes #n`.
5. Do not auto-implement every new issue. Only implement when the user points at one.

## Done when

Issue is created/triaged as requested, or implementation is finished with a PR linking `Fixes #n` when the user asked to implement.
