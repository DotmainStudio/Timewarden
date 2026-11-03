# data-connection-catalog Specification

## Purpose
Describe how data projects connect to their systems through a secret-free connection catalog that is discovered from the user's own authenticated tools and enables read-only live metadata only where a probe works.

## Requirements

### Requirement: Secret-free connection catalog
The system SHALL keep `.agent-memory/connections.yaml`, a versioned catalog that records per environment the system, authentication method, environment variable NAMES, non-secret identifiers (project, dataset, schema, account, workspace) and command templates to connect, validate and run safely. It MUST NOT store passwords, tokens, private keys or their file contents.

#### Scenario: Draft from detection
- **WHEN** `data_connect.py init` runs in a repository with a detected data profile
- **THEN** a draft catalog is created from profile defaults and non-secret project files, with unknown values marked `TODO`, and an existing catalog is never overwritten

#### Scenario: Secret in a profile file
- **WHEN** a scanned connection file contains a password or key
- **THEN** only the existence of the setting is recorded, never its value

### Requirement: Machine capability check
The system SHALL provide `data_connect.py check` reporting, without network access, which required CLIs are installed and which required environment variables are set or unset, never printing their values, and the host operating system.

#### Scenario: Missing CLI
- **WHEN** an environment requires a CLI that is not installed
- **THEN** the check reports it as missing with the install hint from the catalog

### Requirement: Agents do not ask how to connect
The generated connection document and the startup briefing SHALL give the agent each environment's connection recipe, and the project instructions MUST tell the agent to read the catalog before asking the user how to connect.

#### Scenario: Briefing
- **WHEN** a session starts in a data project with a catalog
- **THEN** the briefing lists the environments, their systems and where the recipes are, and states which required tools are missing on this machine

### Requirement: Automatic discovery of identifiers
The system SHALL fill identifiers that are missing or `TODO` by querying the user's already-authenticated CLIs (gcloud and bq, snow, databricks), MUST NOT overwrite an existing value, MUST NOT store secrets, and SHALL treat any discovery failure as non-fatal.

#### Scenario: Missing project id
- **WHEN** a BigQuery environment has `project: TODO` and gcloud has a configured project
- **THEN** the catalog is updated with that project id and the connection document is regenerated

#### Scenario: User value present
- **WHEN** an identifier already has a value
- **THEN** discovery leaves it untouched
