# ENGINEERING SKILL (UNIFIED)

## Version
Last updated: [YYYY-MM-DD]

## Core Principles
- Explicit > implicit
- Simple > clever
- Contracts define behavior
- Systems fail at boundaries
- If it's not observable, it's not debuggable

## PROJECT RULES
- [stack-specific conventions]
- [domain rules]
- [naming conventions]
- [architecture constraints]
- [deployment/runtime constraints]

## API & CONTRACT DESIGN
- Define strict input/output schemas
- Validate all inputs
- Keep responses consistent
- Avoid hidden side effects

Checklist:
- Are edge cases defined?
- Is behavior predictable?
- Any breaking change risk?

Anti-patterns:
- Overloaded endpoints
- Silent failures

## DATA MODELING
- Model for usage, not storage
- Prefer flat, explicit structures
- Avoid unnecessary nesting

Checklist:
- Does this match query patterns?
- Can it evolve safely?
- Any redundant fields?

Anti-patterns:
- Over-normalization
- Dumping JSON blobs

## STATE MANAGEMENT
- Single source of truth
- Explicit state transitions only

Checklist:
- Who owns this state?
- When does it change?
- What if it's stale?

Anti-patterns:
- Hidden mutations
- Scattered state

## TESTING
- Test behavior, not implementation
- Cover happy, edge, and failure cases
- Tests must be deterministic

Checklist:
- Are failures explicit?
- Do tests catch regressions?

Anti-patterns:
- Only happy path testing
- Flaky tests

## ERROR HANDLING
- Fail fast and clearly
- Never swallow errors

Checklist:
- Is error actionable?
- Is recovery defined?

Anti-patterns:
- Generic errors
- Silent failure

## SECURITY
- Treat all inputs as untrusted
- Enforce auth + validation

Checklist:
- Any injection risk?
- Any data exposure?

Anti-patterns:
- Hardcoded secrets
- Over-permissive access

## PERFORMANCE
- Avoid unnecessary work
- Minimize I/O and repeated computation

Checklist:
- Any obvious bottleneck?
- Can this scale?

Anti-patterns:
- Premature optimization
- Repeated expensive calls

## INTEGRATION
- Never trust other modules blindly
- Validate all boundaries

Checklist:
- What if downstream fails?
- Is retry needed?

Anti-patterns:
- Tight coupling
- Assumed correctness

## OBSERVABILITY
- Log key actions and failures
- Include context

Checklist:
- Can I trace execution?
- Are failures visible?

Anti-patterns:
- No logs
- Noisy logs

## DEBUGGING
- Reproduce → isolate → fix root cause

Checklist:
- Can it be reproduced?
- What changed?

Anti-patterns:
- Guessing fixes
- Ignoring signals

## EVOLUTION RULE
After any bug or integration issue, add:
- What failed
- New rule to prevent it