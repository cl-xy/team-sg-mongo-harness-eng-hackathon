# Standards

> For upholding engineering standards

## Dev Conventions

### Commits

Signed (if possible) semantic commits: `gc -S -m 'type(scope): description'`

Types: feat, fix, chore, refactor, docs, test

One commit per logical change. Atomic, terse messages.

Example: gc -S -m 'feat(consolidation): add salience scoring to pattern extraction'

### Code

- Follow [Refactoring Guru](https://refactoring.guru) patterns — small functions, single responsibility, no god objects
- Name things clearly, no abbreviations unless universal (e.g. db, id)
- Extract early, inline later if wrong
- NO bloody dead code, no commented-out blocks
