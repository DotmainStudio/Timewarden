# Spec Delta

## Purpose
Detect and repair mechanical problems of the memory stack automatically without exceeding a fixed budget of subscription usage.

## ADDED Requirements

### Requirement: Free checks and repairs by default
The healer SHALL perform its detection and its infrastructure repairs (restarting an unhealthy container or the observer, marking swarm runs stuck for hours as failed, closing leftover team sessions) without any model call.

#### Scenario: Unhealthy container
- **WHEN** a stack container is not running or not healthy
- **THEN** the healer restarts only that service without removing volumes, and records the action

#### Scenario: Restart loop protection
- **WHEN** the same component needed more than the allowed attempts in a day
- **THEN** the healer stops restarting it and raises one notification

### Requirement: Token spending is capped
The healer MUST re-index pending documents only within a daily budget: at most the configured syncs per day (hard maximum 6), at most the configured documents per sync (hard maximum 20), at least the configured hours between syncs, and at most the configured attempts per document per day.

#### Scenario: Budget exhausted
- **WHEN** the daily number of syncs has been reached
- **THEN** no further sync is started that day and the pending count is reported

#### Scenario: Repeated failure of one document
- **WHEN** a document has failed the configured number of attempts
- **THEN** it is no longer retried that day and a notification is raised once

### Requirement: Quota awareness
The healer MUST NOT start any action that spends tokens while the subscription's reported utilisation is at or above the configured threshold, and SHALL proceed when the reading is unavailable only with its normal caps.

#### Scenario: High quota
- **WHEN** the reported utilisation is above the threshold
- **THEN** token-spending actions are skipped and free repairs still run

### Requirement: Index only merged state
The healer MUST sync a repository only when its checkout is on the default branch and has no uncommitted changes to tracked files, so nothing unmerged is indexed.

#### Scenario: Feature branch checked out
- **WHEN** the repository is on a branch other than the default branch
- **THEN** the sync is skipped and the reason is reported

### Requirement: Destructive fixes are never automatic
The healer MUST NOT delete datasets, forget data, or remove documents from memory; findings of that kind SHALL be reported only.

#### Scenario: Document in memory without registry entry
- **WHEN** the panel flags documents in memory that have no registry entry
- **THEN** the healer notifies once per day and deletes nothing

### Requirement: Optional bounded diagnosis
AI diagnosis SHALL be disabled by default; when enabled it MUST use the lightest model class with read-only tools, at most the configured number of times per day, and only when the quota threshold allows.

#### Scenario: Diagnosis disabled
- **WHEN** the default configuration is used
- **THEN** the healer makes no model call of its own
