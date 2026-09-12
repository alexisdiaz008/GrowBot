# Agent instructions (app repo)

This project uses an **agent-kit** loadout (rules, skills, hooks). Managed files
under `.cursor/rules/`, `.cursor/skills/`, and `.cursor/hooks/*.sh` are refreshed
by agent-kit’s `bin/setup --project` — put app-specific guidance in other files
(or this `AGENTS.md`), not in managed copies.

## Specs

When a product or engineering spec exists in **this** repo (`docs/**/*.md`, `AGENTS.md`, `.cursor/specs/`), prefer it. If requirements are ambiguous, plan before coding.

## Skills

Use installed loadout skills when the task matches. Only `spec-driven-dev` may
auto-invoke; other project skills are explicit slash workflows.

Do not recreate `/review`, `/review-security`, `/review-bugbot`, `/babysit`, or `/split-to-prs`.

## Rules

Stack `.mdc` rules are glob-scoped. `engineering.mdc` is the only always-on invariant. `anti-sycophancy-code-discipline.mdc` is requestable.
