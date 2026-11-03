# agent-token-efficiency Specification

## Purpose
Spend the subscription quota deliberately: cheap models for mechanical work, stable prompts, small toolkits and bounded runs, tuned by measurement.

## Requirements

### Requirement: Model routing by role
A versioned policy file SHALL assign a model class and reasoning effort to each role, the exploring role MUST use the lightest class, the strongest class MUST NOT be a default for any role, and escalation to it SHALL require an architecture change or two failed reviews.

#### Scenario: Exploration job
- **WHEN** the explorer role runs
- **THEN** it uses the lightest model class and low effort

### Requirement: Stable prompt prefix
Static agent documents (entry file, rules, role definitions) MUST NOT contain dates, identifiers, branch names or metrics, the tool and server set MUST NOT change during a session, and the Claude Code version SHALL be pinned.

#### Scenario: Static document scan
- **WHEN** the harness documents are scanned
- **THEN** no date, id or branch-name pattern is found

### Requirement: Minimal toolkit
Each role SHALL list an explicit tool allowlist of general-purpose tools, the explorer and reviewer MUST be read-only, and memory recall SHALL be exposed on demand rather than as an always-attached tool server.

#### Scenario: Reviewer write attempt
- **WHEN** the reviewer tries to edit a source file
- **THEN** the tool is not available to it

### Requirement: Subagent isolation
Subagents SHALL start with clean context, return a bounded synthesis, and write their detailed output to files instead of returning it to the leader's context.

#### Scenario: Large exploration
- **WHEN** an explorer reads many files
- **THEN** the leader receives a summary within the size limit and a path to the details

### Requirement: Measured defaults
A default in the policy file MUST change only after a before/after comparison on the same set of tasks, and thresholds taken from external guidance (cache savings, context-degradation levels, tool-reduction gains) SHALL be treated as hypotheses until confirmed by this system's own data.

#### Scenario: Policy change
- **WHEN** a model or effort default is changed
- **THEN** a recorded comparison exists in the efficiency view
