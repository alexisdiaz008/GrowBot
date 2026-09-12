---
name: ship-pr
description: >-
  Opens a GitHub pull request with gh, conventional commits, and the app
  PR template. Use when the user asks to open a PR, ship a branch, or create a
  pull request.
disable-model-invocation: true
---

# Ship PR

## When to use

- User asks to open a PR, ship a branch, or create a pull request

## Instructions

1. Confirm cwd is the app git root (or the kit root if working on the kit). Refuse to commit files that belong to a nested, separately-tracked repo.
2. `git status` / `git diff` / `git log -8`. Follow the repo’s recent commit style if it is already conventional.
3. Stage **named** paths only. Commit message: `type(scope): summary` plus a one-line why.
4. Push the current branch. Use `.github/PULL_REQUEST_TEMPLATE.md` when present; otherwise construct the required body below.
5. Body must include: Summary, Test plan, Risk. Link `Fixes #n` when an issue exists.
6. Print the PR URL. Do not merge, do not enable auto-merge, unless asked.
7. Suggest `/review-bugbot` and `/review-security` before or after push.

## Done when

PR is open, URL is printed, and merge/auto-merge was not enabled unless the user asked.
