# AIDLC Orchestrator — Contract Schemas Reference

> Human-readable reference for all handoff contract schemas.
> Auto-generated from actual `.json` schema files — if a field is not here,
> it's not in the schema either.

---

## Stage Contracts

| Schema | Produced by | Consumed by | Key fields |
|--------|-------------|-------------|------------|
| `workspace-scout.input.v1.json` | orchestrator | workspace-scout | `user_request`, `skill_paths_resolved` |
| `workspace-scout.output.v1.json` | workspace-scout | orchestrator, requirements-analyst | `workspace_state` (contains `project_type`, `existing_code`, `next_phase`), `project_profile`, `artifacts[]` |
| `reverse-engineer.input.v1.json` | orchestrator | reverse-engineer | `user_request`, `workspace_state`, `predecessor_artifacts`, `skills_required` |
| `reverse-engineer.output.v1.json` | reverse-engineer | orchestrator, requirements-analyst | `tech_stack_summary`, `architecture_artifacts[]`, `artifacts[]` |
| `requirements-analyst.input.v1.json` | orchestrator | requirements-analyst | `user_request`, `predecessor_artifacts`, `workspace_state`, `depth_override` |
| `requirements-analyst.output.v1.json` | requirements-analyst | orchestrator, workflow-planner | `request_classification` (scope, complexity), `artifacts[]`, `needs_user_input`, `questions_artifact_path` |
| `story-writer.input.v1.json` | orchestrator | story-writer | `requirements_path`, `predecessor_artifacts` |
| `story-writer.output.v1.json` | story-writer | orchestrator, workflow-planner | `stories_artifact_path`, `personas_artifact_path`, `artifacts[]` |
| `workflow-planner.input.v1.json` | orchestrator | workflow-planner | `user_request`, `predecessor_artifacts`, `depth_override` |
| `workflow-planner.output.v1.json` | workflow-planner | orchestrator, unit-decomposer | `execution_plan_path`, `units[]` (name, description, depends_on), `artifacts[]` |
| `unit-decomposer.input.v1.json` | orchestrator | unit-decomposer | `units[]` from workflow-planner, `predecessor_artifacts` |
| `unit-decomposer.output.v1.json` | unit-decomposer | orchestrator | `units_decomposed[]` (name, file, dependencies), `artifacts[]` |
| `code-generator.input.v1.json` | orchestrator | code-generator | `user_request`, `unit_name`, `unit_spec_path`, `predecessor_artifacts`, `fast_path`, `tier`, `locks_required` |
| `code-generator.output.v1.json` | code-generator | orchestrator, build-test-agent | `files_changed[]`, `tests_added`, `commits_made[]`, `artifacts[]`, `cost` |
| `build-test-agent.input.v1.json` | orchestrator | build-test-agent | `unit_name`, `unit_spec_path`, `build_tool`, `test_framework`, `predecessor_artifacts`, `locks_required` |
| `build-test-agent.output.v1.json` | build-test-agent | orchestrator | `build_status`, `tests_total/passing/failing`, `coverage_pct`, `artifacts[]` (kind: doc/test/config/source), `skill_compliance[]` |
| `reviewer.input.v1.json` | orchestrator | reviewer-* | `stage_id` (e.g. `reviewer-code`), `reviewer` (e.g. `code-quality`), `user_request`, `predecessor_artifacts`, `scope_paths` |
| `reviewer.output.v1.json` | reviewer-* | orchestrator, merge-reviews | `findings[]` (severity, file, line, message, recommendation), `findings_summary`, `skill_compliance[]` |
| `ship-agent.input.v1.json` | orchestrator | ship-agent | `user_request`, `predecessor_artifacts`, `release_type` |
| `ship-agent.output.v1.json` | ship-agent | orchestrator | `changelog_path`, `adrs[]`, `release_notes_path`, `artifacts[]` |

---

## Supporting Contracts

| Schema | Purpose | Produced by | Key fields |
|--------|---------|-------------|------------|
| `custom-agent.input.v1.json` | Generic input for user-defined subagents | orchestrator | `task_description`, `context`, `budget` |
| `custom-agent.output.v1.json` | Generic output for user-defined subagents | custom agent | `status`, `summary`, `artifacts[]` (path, kind, hash), `findings[]` |
| `approval.input.v1.json` | Structured approval gate presentation | orchestrator | `run_id`, `stage`, `units[]` (name, tasks, acceptance_criteria), `estimated_tokens`, `estimated_minutes` |
| `shared/complexity-tier.schema.json` | Complexity tier enum (SMALL/MEDIUM/LARGE) + routing | — | `complexity_tier`, `skip_stages[]`, `reviewer_pool[]` |
| `shared/unit-graph.schema.json` | Unit dependency wave structure | — | `unit_waves[][]`, `unit_wave_count`, `unit_max_parallelism` |

---

## Common fields across all output schemas

| Field | Type | Description |
|-------|------|-------------|
| `status` | enum | `complete`, `blocked`, `failed`, `needs_human` |
| `audit_entries[]` | string[] | Chronological audit trail from the agent |
| `emitted_knowledge[]` | object[] | Knowledge artifacts (patterns, ADRs, lessons) with `kind`, `title`, `body` |
| `cost` | object | Token/wall-clock usage: `{tokens_in, tokens_out, wall_clock_min, retries_used}` |
| `skill_compliance[]` | object[] | Per-skill PASS/FAIL/N/A with `skill`, `status`, `evidence` |
| `artifacts[]` | object[] | Files produced: `{path, kind, hash?}` where kind ∈ {doc, source, test, config, plan, report} |

---

## Status meanings

| Status | Meaning |
|--------|---------|
| `complete` | Stage finished successfully |
| `blocked` | Stage could not proceed (missing input, external dependency) |
| `failed` | Stage errored irrecoverably |
| `needs_human` | Stage produced output requiring human approval before proceeding |

---

## Complexity tiers

Tiers (SMALL/MEDIUM/LARGE) set by `factory_complexity.py` control skip/merge
routing and the reviewer pool. Defined in `shared/complexity-tier.schema.json`.

| Tier | Skip stages | Reviewer pool |
|------|-------------|---------------|
| SMALL | story-writer, unit-decomposer | code only |
| MEDIUM | story-writer | code, security, simplifier |
| LARGE | (none) | all 4 reviewers |

---

## File naming exception: reviewer contracts

The reviewer input/output contracts use a shared schema (not per-reviewer).
The `stage_id` field differentiates which reviewer runs:
`reviewer-code` / `reviewer-security` / `reviewer-performance` / `reviewer-simplifier`.
The `reviewer` field uses a separate short name:
`code-quality` / `security` / `performance` / `simplifier`.

---

## Schema version history

| Version | Date | Changes |
|---------|------|---------|
| 1 | 2026-05 | Initial contract set for all 13 stages |

---

## File locations

All schemas live in `.aidlc-orchestrator/contracts/`. The orchestrator validates
every input and output handoff against the corresponding schema using
`aidlc-scripts/factory_validate.py` before spawning or consuming.
