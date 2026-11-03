# portable-bundle Specification

## Purpose
Distribute the kit as a neutral, relocatable, self-contained package that another agent can install on another machine.

## Requirements

### Requirement: Neutrality
The distributable package MUST NOT contain project names, company names, accounts, email addresses, or absolute paths from the source machine, nor secrets, keys, tokens, databases, or evaluations from a specific project.

#### Scenario: Package scan
- **WHEN** the bundle is packaged
- **THEN** a scan for forbidden terms and secret patterns across all files in the `.zip` finds no matches, and packaging fails if there are any

### Requirement: Relocatable and self-contained
The package SHALL be installable in any directory, resolve all paths relative to its own location (with a variable to override it), and include the Management Memory dashboard, so that it does not depend on external repositories or accounts.

#### Scenario: Installation in another directory
- **WHEN** the `.zip` is unzipped into an arbitrary directory and the requirements check is run
- **THEN** the check reports correct paths and does not reference locations on the source machine

### Requirement: Runbook and verification
The package SHALL include the phased runbook (executed by the agent without approval checkpoints), the prompt to paste into an agent, the technical specification, and an acceptance check, and MUST document what leaves the user's machine (only the text that is indexed via Claude).

#### Scenario: Delivery
- **WHEN** a colleague receives the `.zip`
- **THEN** they find a `LEEME` with the minimal steps and the ready-made prompt, without knowing the system

### Requirement: Unattended installation
The runbook and the prompt SHALL instruct the agent to execute every phase without asking the user for approval (containers, plugin, project setup, indexing, panel, verification) and to report what it did and what indexing cost at the end, and MUST still stop and ask only when the language or project type is ambiguous (exit code 3) or the operating system is not validated.

#### Scenario: Fresh machine and repository
- **WHEN** the user hands the kit and a repository to the agent
- **THEN** the agent completes machine, project, corpus, index, panel and verify phases with no further input and delivers the report

#### Scenario: Ambiguous project type
- **WHEN** the detector cannot decide the project type
- **THEN** the agent asks that single question and continues unattended afterwards

### Requirement: Swarm components in the kit
The distributable kit SHALL include the swarm platform, harness templates and panel page, MUST keep all neutrality guarantees for them (no project names, no tokens, no machine paths), and the token file and per-machine configuration MUST be generated on each machine, never shipped.

#### Scenario: Kit scan with swarm
- **WHEN** the kit is exported
- **THEN** the neutrality and secret scan covers the swarm files and finds no matches, and the export fails if it does
