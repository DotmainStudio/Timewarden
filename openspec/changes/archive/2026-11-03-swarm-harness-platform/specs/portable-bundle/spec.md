# Spec Delta

## ADDED Requirements

### Requirement: Swarm components in the kit
The distributable kit SHALL include the swarm platform, harness templates and panel page, MUST keep all neutrality guarantees for them (no project names, no tokens, no machine paths), and the token file and per-machine configuration MUST be generated on each machine, never shipped.

#### Scenario: Kit scan with swarm
- **WHEN** the kit is exported
- **THEN** the neutrality and secret scan covers the swarm files and finds no matches, and the export fails if it does
