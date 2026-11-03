# data-project-graph Specification

## Purpose
Build an offline lineage graph for data projects (dbt, Dataform, Databricks) so structure and impact can be answered exactly, without spending model tokens.

## Requirements

### Requirement: Offline lineage graph
The system SHALL build a lineage graph of a data repository by static analysis only, without network access, warehouse access or credentials, and persist it as `docs/agent-memory/data-graph/graph.json`.

#### Scenario: dbt project
- **WHEN** the repository contains `dbt_project.yml`
- **THEN** nodes exist for models, sources, seeds, snapshots, exposures and tests, with `depends_on` edges derived from `ref()` and `source()`

#### Scenario: Dataform project
- **WHEN** the repository contains `workflow_settings.yaml` or `dataform.json`
- **THEN** nodes exist for tables, views, incrementals, assertions, operations and declarations, with edges derived from `ref()`

#### Scenario: Databricks project
- **WHEN** the repository contains `databricks.yml` or Delta Live Tables code
- **THEN** nodes exist for jobs, pipelines and the tables they read or write, with `reads`/`writes`/`runs` edges

#### Scenario: Unresolvable reference
- **WHEN** a reference is built dynamically and cannot be resolved statically
- **THEN** the node is flagged `dynamic` and listed by `check`, and no edge is guessed

### Requirement: Generated memory documents
The system SHALL generate Markdown documents under `docs/agent-memory/data-graph/` (overview, observed conventions, per-folder model cards, sources) with `generated: true` frontmatter so the existing sync indexes them, and MUST NOT overwrite `rules.md`.

#### Scenario: Regeneration
- **WHEN** the graph is rebuilt
- **THEN** generated documents are overwritten and `rules.md` is left untouched

#### Scenario: Bounded size
- **WHEN** a folder contains many models
- **THEN** its cards are split across documents so that no single document exceeds the configured size cap

### Requirement: Structural queries
The system SHALL answer `find`, `show`, `upstream`, `downstream`, `impact` and `path` queries from `graph.json` without any network call, with an optional depth limit.

#### Scenario: Impact analysis
- **WHEN** the agent asks for the impact of a model
- **THEN** the answer lists every downstream node (models, exposures, tests) grouped by depth

### Requirement: Observed conventions and checks
The system SHALL derive conventions from the graph (naming prefix per folder, materialization per layer, test and description coverage) and report violations (cycles, orphans, models without tests, layer-skipping references) through `check`, labeling inferred conventions as observed and never as rules.

#### Scenario: Layer violation
- **WHEN** a mart-layer model references a source directly while the project uses a staging layer
- **THEN** `check` reports it with both node names and paths

### Requirement: Freshness and agent usage
The system SHALL record a content hash of the scanned files, report staleness in the startup briefing, and instruct the agent (CLAUDE.md section and skill) to query the graph before asking the user or opening many files.

#### Scenario: Stale graph
- **WHEN** a model file changed after the graph was built
- **THEN** the briefing marks the graph stale and rebuilds it within a time budget

### Requirement: Sensitive data exclusion
The scanner MUST NOT read or store `profiles.yml` secret values, key files, `.env*` files, service-account JSON or sample data directories.

#### Scenario: Excluded paths
- **WHEN** the scan runs on a repository containing such files
- **THEN** none of their contents appear in `graph.json` or any generated document
