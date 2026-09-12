---
name: writing-tests
description: >-
  Writes focused unit and integration tests using the repository's existing
  framework and conventions. Use when adding tests, improving coverage, or
  testing a specific behavior.
disable-model-invocation: true
---

# Writing tests

## Instructions

1. Detect the existing test setup from CI workflows, dependency manifests,
   config files, test directories, and package scripts.
2. Read nearby tests before choosing file placement, naming, fixtures, mocks,
   or assertion style.
3. If no test framework exists, propose a stack-appropriate option and wait
   for approval. Do not install a default framework.
4. Identify the public behavior and cover:
   - expected behavior
   - empty and boundary inputs
   - failures and invalid inputs
   - state transitions or async behavior when present
5. Mock external boundaries such as network, filesystem, time, and third-party
   services. Do not mock the behavior under test.
6. Run the repository's exact test command. Fix test mistakes; do not change
   production behavior merely to satisfy an incorrect expectation.
7. Report the command run, result, and any behavior that remains untested.

## Constraints

- Test observable behavior, not private implementation details.
- Keep tests deterministic and independent of execution order.
- Do not make real external-service calls from unit tests.
- Do not weaken assertions to make a failing implementation pass.
