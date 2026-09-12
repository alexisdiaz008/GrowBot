---
name: spec-driven-dev
description: >-
  Runs spec-first implementation: find the repo spec, plan, execute one
  step, verify against the spec. Use when building a feature, changing
  behavior, or when the user mentions spec, SDD, or plan-then-code.
---

# Spec-driven development

## When to use

- Building a feature or changing behavior
- User mentions spec, SDD, or plan-then-code
- Requirements should be grounded in a written source of truth

## Instructions

1. Find source of truth in the *current* repo, in order: `docs/product-spec.md`, `docs/spec.md`, `.cursor/specs/**`, `AGENTS.md`. If none, ask for a spec or write a short one in the repo’s preferred docs folder and stop for approval.
2. Read constraints / decision logs if present (`docs/decisions.md`, `docs/adr/**`).
3. Produce a plan with file paths. Wait for approval unless the user already approved a plan.
4. Execute **one** plan step. Do not implement the whole plan in one turn.
5. Verify against the spec (tests, checks, or an explicit checklist). Then stop or ask to continue.
6. If the change contradicts a written decision, stop and say so. Do not silently override.

## Done when

One approved plan step is implemented and verified against the spec, or work is blocked pending a missing/contradictory spec or decision.
