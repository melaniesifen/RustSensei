# Agent Guide: Rust Sensei

## Project Snapshot

Rust Sensei is a planned local-first MCP server for an adaptive Rust learning agent. The repository contains design documentation and a local Python implementation in progress.

Primary sources of truth:

- `README.md`: project overview, goals, current status, planned architecture.
- `docs/hld.md`: high-level requirements and system design.
- `docs/lld-mcp-server.md`: planned Python MCP server package layout, tool contracts, storage boundaries, and CLI shape.
- `docs/lld-ai-agent.md`: how Codex and other MCP agents should interact with Rust Sensei.
- `docs/lld-adaptive-lessons.md`: adaptive curriculum and lesson selection design.
- `docs/lld-confidence-measuring.md`: confidence scoring and skill update dampening design.
- `feedback/`: review notes for the docs. Treat these as useful context, not as implemented behavior.

## Current State

- This is a documentation-first repo with an initial Python package.
- Existing code covers package metadata, DTO/domain models, JSON learner profile storage, lesson assignment storage, curriculum seed loading, attempt storage, assessment storage, progress event storage, learner signal storage, session service, lesson service, assessment service, progress service, setup service, CLI entrypoint, and tests.
- Implemented flows: `start_session`, `get_learner_profile`, `get_next_lesson`, `submit_attempt`, `assess_attempt`, `get_progress_summary`, `update_learner_signal`, and `get_setup_status`.
- `assess_attempt` persists idempotent assessment records, returns deterministic rubric scores, returns confidence output with explanation details, records missing evidence, marks assignments assessed, and updates the learner skill model with confidence dampening.
- `get_next_lesson` can use the latest assessed assignment and stored assessment action to create the next active assignment through the lesson selector registry. Continue and accelerate actions prefer the current concept's `next_concepts` graph links before falling back to curriculum order. Direct prerequisites that were previously completed or skipped can be reopened when later high-confidence evidence shows a weak required rubric. Deterministic scoring gates continue and accelerate decisions on concept `completion_thresholds` when thresholds are configured.
- `get_next_lesson` resolves stored `branch` actions with `branch_id` through concept-level `branch_targets`, then curriculum-level `branch_fallbacks`, then explicit repeat fallback. The deterministic v1 scorer can emit high-confidence branches for repeated compiler failures and problem-solving gaps when Rust syntax evidence is strong.
- `get_next_lesson` rotates deterministic unused prompt variants for the selected concept and difficulty before reusing the first matching variant.
- `get_next_lesson` can abandon the active assignment when `abandon_active_assignment` is true and a non-empty `abandonment_reason` is supplied. `force_new_variant` is supported only with abandonment while an active assignment exists.
- `get_next_lesson` returns an agent-owned `workspace_suggestion` with stable per-assignment relative paths. Normal lessons suggest a generated Cargo binary package and lesson file. Project-setup lessons such as `cargo new` suggest a directory to open without pre-creating a Cargo package.
- Curriculum seed loading validates the current v1 shape, including nonblank required fields, known difficulty bands, unique concept order values, known rubric ids, richer concept graph metadata, valid concept references, valid branch target lists, completion thresholds, workspace artifact policies, and lesson command metadata. Invalid or unreadable custom curriculum files are returned as structured storage errors.
- `rust_sensei.agent_workflow.prepare_agent_lesson` composes `get_next_lesson` responses with workspace preparation, supports caller-provided editor openers, and returns generated relative paths for attempt evidence.
- `rust_sensei.agent_workflow.build_submit_attempt_request` builds `SubmitAttemptRequest` DTOs from prepared lesson workspaces, generated file paths, current lesson file contents, command evidence, and learner/agent notes. It omits absolute `workspace_root` by default unless local diagnostics explicitly opt in.
- `rust_sensei.agent_workflow.write_agent_lesson_report` writes report files from the prepared workspace, submitted attempt evidence, and canonical assessment output.
- `rust_sensei.agent_workspace.prepare_lesson_workspace` creates or reuses suggested lesson directories and starter Cargo files without overwriting learner code. Opening VS Code remains an agent/client action.
- `rust_sensei.agent_report.write_lesson_report` writes a stable per-assignment `report.md` after assessment. The report includes assignment details, submitted artifacts, command lists, a readable assessment summary, and the canonical Rust Sensei assessment DTO as JSON. Human-readable report sections redact obvious local absolute path fragments while preserving canonical assessment JSON.
- Progress events are persisted for placement skips, assignment creation/viewing, attempt submission, assessment, adaptive assessment outcomes, and assignment abandonment. Lifecycle events for profile creation with placement skips, assignment creation, attempt submission, assessment with its adaptive outcome, and abandonment are written in the same JSON transaction as the canonical state change.
- `get_progress_summary` returns completed/repeated/skipped concepts, recent events, recommended focus, and trend.
- `update_learner_signal` records non-code learner signals such as confusion, confidence, blockers, pacing, boredom, too-easy, and too-hard feedback.
- CLI diagnostics include `setup-status` for JSON setup output and `doctor` for human or JSON local setup checks.
- Implemented MCP resources expose active profile, active progress summary, and curriculum concept inventory.
- Implemented MCP prompts expose tutor behavior, attempt review, and stuck-state coaching guidance.
- MCP handler registration is unit-tested through `register_handlers` with a fake registrar. Registered MCP tools expose direct typed parameters rather than an opaque `payload` wrapper. Real FastMCP integration tests cover registration, schemas, tool flows, resources, prompts, and structured validation errors with `mcp==1.27.1`.
- Do not assume Rust crate support, full MCP tool wiring, hosted behavior, multi-learner support, or a complete release pipeline exists until the files are present.
- If adding implementation, create the missing project structure deliberately and update docs when behavior diverges from the design.

## Handoff Snapshot

Use this order when continuing implementation:

1. Add fuller agent/client examples around the workflow helper if a target MCP client needs setup-specific glue.
2. Continue opportunistic validation and privacy hardening as new storage, report, or workflow surfaces are added.

Important current behavior:

- `start_session` creates the profile only after a valid `RustLevel` placement.
- `get_next_lesson` creates an active assignment, reuses active assignments, abandons active assignments with a required reason, returns pending assessment after an attempt, reopens weak direct prerequisites when the prerequisite was previously completed or skipped, and creates a post-assessment assignment from `repeat`, `simplify`, `continue`, `accelerate`, or `branch`. The deterministic v1 scorer emits `branch` for high-confidence repeated compiler failures and for high-confidence problem-solving gaps when Rust syntax evidence is strong.
- `get_next_lesson` includes `workspace_suggestion` for assignment responses. Pending-assessment responses have no assignment, no lesson plan, and no workspace suggestion.
- Agent workflow helpers can prepare the suggested workspace, open the suggested path through a caller-provided opener such as VS Code, collect generated relative file paths and current lesson code into a `SubmitAttemptRequest`, and write the report after assessment. These helpers are not MCP tools and do not make the server control the editor.
- Branch targets are configured in curriculum JSON with concept-level `branch_targets` and top-level `branch_fallbacks`. Target concept ids are validated when loading the curriculum.
- The implemented curriculum model stores concept id, title, order, default difficulty, learner command, rubric ids, variants, branch targets, and richer graph metadata such as prerequisites, competency goals, baseline task, stretch/struggle signals, next concepts, and completion thresholds. Lesson selection uses `next_concepts` for continue/accelerate graph traversal, direct prerequisites for reopening, branch targets for branch actions, and variant history for deterministic prompt rotation. Scoring uses configured `completion_thresholds` to decide when thresholded concepts may continue or accelerate.
- Placement selects the active starting concept and records `provisionally_skipped` events for earlier concepts when a learner starts as `proficient` or `expert`.
- Assessment writes the canonical `assessed` progress event plus one adaptive outcome event derived from `next_action`: `completed`, `repeated`, `simplified`, `accelerated`, or `branched`. Prerequisite reopening writes a `reopened` event in the same transaction as the new assignment.
- Variant rotation uses prior assignments for the learner and selects the first unused variant for the target concept and difficulty. When all matching variants were used, it falls back to the first matching variant.
- `submit_attempt` validates nonblank evidence, rejects invalid command metadata source/risk values through DTO validation, enforces artifact size limits and truncation reasons, rejects obvious secret-bearing file paths, saves attempts atomically with assignment status updates, and handles idempotent `client_request_id` retries inside the JSON lock.
- `assess_attempt` validates attempt readiness, creates one assessment per attempt, handles repeat calls without changing state, uses deterministic scoring from `domain/scoring.py`, and applies confidence-dampened skill updates from `domain/skill_update.py`.
- `get_progress_summary` derives current progress from learner profile, assignments, assessments, and recent progress events. It does not mutate state.
- `update_learner_signal` validates an existing active learner profile and appends a `LearnerSignal` record to JSON state. It does not currently influence lesson selection.
- `rust-sensei doctor` wraps setup diagnostics and exits `0` only when Python, rustc, Cargo, and state directory checks are ready. Use `rust-sensei doctor --json` for machine-readable output.
- MCP resources expose `rust-sensei://profile/active`, `rust-sensei://progress/summary`, and `rust-sensei://curriculum/concepts`.
- MCP prompts expose `rust_sensei_tutor`, `rust_sensei_attempt_review`, and `rust_sensei_stuck_coaching`.
- `rust_sensei.mcp_server.register_handlers` owns tool, resource, and prompt registration so the MCP surface can be tested with a fake registrar and with real FastMCP when the `mcp` extra is installed. `run` remains the only function that imports `mcp.server.fastmcp.FastMCP` for server startup.
- Progress events are append-only and currently support recent-event listing through the repository and progress summary service. Events tied to canonical lifecycle mutations must stay in the same repository transaction as that mutation.
- JSON state remains the v1 persistence adapter behind repository interfaces. The state store keeps `state.json.bak` as the latest valid pre-replace backup and restores from it when the primary state file is invalid or has an unsupported schema.
- The MCP server must not execute learner Rust code.
- The base package depends on Pydantic, declares `python_requires = >=3.11`, and keeps the official MCP SDK in the optional `mcp` and `dev-mcp` extras. Use `.[dev]` for service/storage/unit work that does not need the real SDK, and `.[dev-mcp]` inside `.venv` for the full test suite including FastMCP integration tests.

## Architecture Guardrails

- v1 implementation language is Python 3.11+.
- Use the official MCP Python SDK when implementing the server.
- Default transport should be stdio for local agent use.
- Rust Sensei must remain client-neutral. Codex setup belongs in docs/examples, not core server logic.
- The MCP server must not execute arbitrary learner Rust code in v1.
- The agent, not Rust Sensei, may run learner workspace commands such as `cargo check`, `cargo run`, and `cargo test` when the learner requests verification or a lesson explicitly requires it.
- Store v1 learner state in local JSON behind repository interfaces so SQLite or another adapter can replace it later.
- JSON writes must be atomic and protected by a single-writer lock or equivalent read-modify-write guard.
- Persist canonical records for learner profile, sessions, assignments, attempts, assessments, learner signals, and progress events with `learner_id` fields.

## Planned Package Layout

The implementation now uses the following package layout. Follow this shape unless there is a documented reason to change it:

```text
rust_sensei/
  __init__.py
  __main__.py
  agent_workflow.py
  agent_report.py
  agent_workspace.py
  cli.py
  mcp_server.py
  domain/
    attempt.py
    curriculum.py
    enums.py
    learner.py
    lesson.py
    placement.py
    lesson_selection.py
    scoring.py
    skill_update.py
    setup.py
    signal.py
    skill.py
    progress.py
    workspace.py
  services/
    assessment_service.py
    progress_service.py
    session_service.py
    lesson_service.py
    setup_service.py
  repositories/
    interfaces.py
    json_repository.py
  prompts/
    tutor_prompts.py
  resources/
    curriculum_seed.json
```

## MCP Tool Contract Expectations

Planned v1 tools:

- `start_session`
- `get_next_lesson`
- `submit_attempt`
- `assess_attempt`
- `get_learner_profile`
- `get_progress_summary`
- `update_learner_signal`
- `get_setup_status`

Implementation rules:

- Validate all tool inputs before updating state.
- Use typed request and response models, preferably Pydantic, rather than loose dictionaries beyond the MCP SDK boundary.
- FastMCP validates function signatures before handler code runs. Keep tool schemas as direct parameters, but avoid strict MCP-facing enums and non-null required annotations when Rust Sensei needs to return its own structured validation envelope; let Pydantic request DTOs own validation and error formatting.
- `start_session` owns the placement protocol.
- `get_next_lesson` must persist a `LessonAssignment` when creating one and return an active unattempted assignment by default.
- `submit_attempt` persists evidence and returns a server-generated `attempt_id`.
- `assess_attempt` must be idempotent for an already assessed `attempt_id` and must not update skill twice.
- Rust Sensei owns canonical scoring, confidence, evidence, and next-step actions. Agent notes are evidence only.

## Agent Workflow Rules

When acting as a tutoring agent using Rust Sensei:

- Call `start_session` before requesting lessons.
- Ask the initial placement question only when `start_session` returns `placement_required: true`.
- Ask exactly one placement question using only: `new`, `beginner`, `intermediate`, `proficient`, `expert`.
- Call `get_next_lesson` before assigning work.
- Create or reuse a lesson-specific Rust file and open it in VS Code when possible, except when the lesson explicitly teaches project setup such as `cargo new`.
- Encourage learner-owned command execution first.
- Run verification commands only when the learner asks for assessment/verification or the lesson explicitly calls for it.
- Submit relevant code, command output, file paths, learner notes, and agent notes through `submit_attempt`.
- Call `assess_attempt` and preserve returned scores, confidence, evidence, and next-step action exactly.
- Write a learner-readable report after assessment when lesson workspace artifacts are available.
- Label any extra advice as agent guidance and do not alter Rust Sensei progression decisions.
- Do not submit secrets, credentials, environment files, or unrelated source files as attempt evidence.

## Verification Commands

Current verification commands:

- Ensure Homebrew or another supported Python is on PATH:
  `source ~/.zshrc && python3 --version`
- Create the local virtual environment:
  `python3 -m venv .venv`
- Install full development dependencies, including the official MCP SDK:
  `.venv/bin/python -m pip install -e ".[dev-mcp]"`
- Test suite:
  `.venv/bin/python -m pytest`
- Coverage:
  `.venv/bin/python -m pytest --cov=rust_sensei --cov-report=term-missing`

Notes:

- The project target is Python 3.11+. Do not lower `python_requires` only to satisfy an older local system Python.
- If `python3 --version` shows `/usr/bin/python3` era Python `3.9.6`, source `~/.zshrc` or open a new shell before creating `.venv`.
- Agents should run pip, setup diagnostics, tests, and coverage through `.venv/bin/python`; do not assume `python`, `pip`, or `pytest` are on the shell `PATH` or that the virtual environment is activated.
- Latest known local verification: `257` tests passed under Python `3.14.5` in `.venv`; latest coverage passed with `94.29%`.
- Real MCP SDK verification is no longer blocked locally after sourcing `~/.zshrc`, using Homebrew Python `3.14.5`, creating `.venv`, and installing `.[dev-mcp]`. `mcp==1.27.1` imported successfully, and FastMCP tests cover tools, resources, prompts, direct-parameter schemas, runtime tool flows, resource reads, prompt reads, and structured validation errors.
- For learner Rust workspaces outside this server, allowed verification commands are limited by the AI Agent LLD to standard Cargo checks or lesson-provided commands.

## Documentation Practices

- Keep HLD and LLD terminology aligned.
- Use `assignment_id` for attempt linkage unless intentionally discussing reusable lesson definitions.
- Preserve the separation between Rust-specific skill and general programming skill.
- Preserve the distinction between skill and confidence.
- Treat placement as provisional; demonstrated work updates estimates.
- Keep specialized tracks out of the default v1 path unless assessment evidence justifies a branch.
- When implementation changes make README or this agent guide stale, update them in the same work slice.
- Update README and this agent guide when there is a significant implementation change, workflow change, limitation, environment finding, test/coverage change, or reviewer finding that future agents need to know.
- Keep handoff context current enough that a new Codex session can continue without relying on prior chat history.

## Editing Notes

- Prefer small, focused changes.
- Do not rewrite existing docs wholesale unless requested.
- If feedback files identify stale wording, update the relevant design doc and keep related LLDs consistent.
- Avoid introducing implementation claims in docs before the code exists.

## Commit Standards

- Do not create commits unless the user explicitly asks for commits or explicitly confirms a proposed commit.
- When the user asks to commit existing work and then continue implementation, commit only the existing reviewed work; do not commit newly implemented follow-up work without another explicit confirmation.
- Commit only after relevant tests and coverage checks pass, unless the user explicitly asks for a checkpoint commit despite known failures.
- Split work into small, reviewable commits grouped by purpose.
- Keep each commit focused on one coherent change, such as project scaffolding, domain models, repository implementation, service behavior, tests, or documentation.
- Avoid mixing unrelated refactors, docs, behavior changes, and test changes in one commit when they can be reviewed separately.
- Use short commit messages that describe the concrete change.
- Before committing, inspect `git status` and `git diff --stat` to confirm the commit contains only intended files.
- Do not include generated logs, coverage output, local state, dependency caches, or other machine-local artifacts in commits.

## Implementation Standards

- Write clear, simple, readable Python that a senior engineer can maintain without extra context.
- Keep a consistent style across modules, names, errors, and tests.
- Order imports as standard library, third-party libraries, then local modules, with blank lines between groups.
- Use type hints for public functions, service methods, repositories, and domain models.
- Keep classes in focused files. Do not let a module become a mixed bucket of unrelated models or services.
- Prefer composition over inheritance unless inheritance expresses a real interface or protocol boundary.
- Prefer `typing.Protocol` for repository and adapter interfaces when structural typing is enough. Use `abc.ABC` only when runtime inheritance checks or shared base behavior are needed.
- Add abstractions only when they protect a real boundary, reduce duplication, or match an established local pattern.
- Use factories when object construction has environment decisions, dependency wiring, or defaults that should not live inside domain logic.
- Keep business logic out of the MCP boundary. MCP handlers should validate input, call services, and return DTOs.
- Keep direct JSON handling inside repository or storage modules only.
- Define repeated categorical values as enums in one domain module, then reuse them in DTOs, services, repositories, and tests.
- Avoid magic strings and magic numbers. Promote repeated or meaningful literal values to named constants, enums, configuration, or test constants.
- Keep reusable behavior in one clear location when it is likely to be used by more than one service, repository, DTO mapper, test, or future adapter.
- Use Pythonic constructs such as comprehensions, generators, context managers, and dataclasses where they improve clarity.
- Avoid clever code. Prefer explicit control flow when it makes validation, persistence, or error behavior easier to audit.
- Write comments only where they explain a non-obvious decision or constraint.

## Logging Standards

- Configure application logging during service factory setup.
- Write logs to a separate log directory under the configured state directory.
- Use append-only daily log rotation. Do not overwrite logs during normal startup.
- Log exceptions at the CLI or MCP boundary before returning structured error payloads.
- Do not swallow exceptions silently. If an exception is handled, log it or document why logging would duplicate a higher boundary log.
- Use `debug` for detailed flow, `info` for important lifecycle events, `warning` for recoverable or user-correctable failures, and `error` for failures that block the requested operation.

## Test And Coverage Standards

- Add or update unit tests with every behavior change.
- Run the unit test suite before handing work back when dependencies are available.
- Run coverage with `.venv/bin/python -m pytest --cov=rust_sensei --cov-report=term-missing`.
- Maintain coverage above `85%`.
- If tests or coverage cannot run because the local environment is missing Python 3.11+ or dependencies, state that explicitly in the final response.
