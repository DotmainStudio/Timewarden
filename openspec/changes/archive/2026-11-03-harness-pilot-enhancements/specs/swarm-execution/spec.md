# Spec Delta

## ADDED Requirements

### Requirement: Read-only exploration with proof
The `swarm explore` command SHALL run the explorer role without write tools and MUST verify, by comparing the working tree before and after, that nothing changed, recording the result as an event.

#### Scenario: Clean exploration
- **WHEN** an exploration job finishes
- **THEN** an event states whether the working tree is unchanged, and a changed tree marks the run as failed

### Requirement: Review without finalizing
The `swarm review` command SHALL accept an option that records the verdict without launching the git agent's finalize phase, so reviews can be run read-only.

#### Scenario: Review with no git
- **WHEN** a review passes and the option is set
- **THEN** no merge, push or pull request action is taken
