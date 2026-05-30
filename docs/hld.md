# Rust Sensei HLD

## 1. Overview / Summary

Rust Sensei is a local-first MCP server for an adaptive Rust learning agent.

The learner writes Rust code in VS Code. Codex operates against the same local workspace, uses Rust Sensei through MCP, runs verification commands when asked, and presents coaching feedback to the learner. Rust Sensei owns lesson planning, learner memory, assessment, progress tracking, and next-step recommendations.

The v1 system supports 1 learner profile stored in local JSON. The storage layer must use repository interfaces so JSON can later be replaced by SQLite or another database without changing lesson, assessment, or MCP tool logic.

Rust Sensei must not depend on Codex-specific APIs. Codex is the primary documented client for v1, but the MCP interface must remain usable by other agents such as Claude Code.

This design supports these primary requirements:

- `FR-01`: Ask exactly 1 initial Rust experience placement question.
- `FR-02`: Use demonstrated work to update skill estimates after placement.
- `FR-03`: Track Rust-specific skill separately from general programming skill.
- `FR-05`: Support adaptive lesson progression.
- `FR-09`: Store local learner state in JSON for v1.
- `FR-10`: Abstract persistence for future database support.
- `FR-12`: Keep the MCP server agent-neutral.
- `NFR-01`: Implement in Python.
- `NFR-02`: Operate local-first for v1.
- `NFR-06`: Do not execute arbitrary learner code inside the MCP server in v1.

## 2. Functional Requirements

### 2.1 Learner Placement And Profile

- `FR-01`: On first use, Rust Sensei must ask exactly 1 initial Rust experience question with these allowed answers: `new`, `beginner`, `intermediate`, `proficient`, `expert`.
- `FR-02`: Rust Sensei must treat initial placement as provisional and update skill estimates after each assessed attempt.
- `FR-03`: Rust Sensei must track Rust-specific skill separately from general programming skill.
- `FR-11`: v1 must support 1 active learner profile, but the data model must include a learner identifier so multi-learner support can be added later.

### 2.2 Lesson Planning

- `FR-05`: Rust Sensei must choose a next-step action after each assessment. The implemented deterministic v1 scorer emits `simplify`, `repeat`, `continue`, `accelerate`, and high-confidence `branch` actions for repeated compiler failures and problem-solving gaps when Rust syntax evidence is strong.
- `FR-06`: The default curriculum target must be general Rust fluency before specialized tracks.
- `FR-06`: Specialized tracks such as CLI tools, backend services, async, performance, or LeetCode-style practice are out of the v1 default path unless assessment results justify a branch.
- `FR-01`: A learner who selects `new` may start with Hello World and Cargo basics.
- `FR-01`: A learner who selects `proficient` or `expert` must not be required to complete Hello World, defining a string, or equivalent beginner tasks unless later work shows a need for remediation.

### 2.3 Adaptive Curriculum

- `FR-05`: The curriculum must be represented as structured concept data, not as a fixed list of static lesson scripts. The implemented v1 seed uses an ordered concept model with variants, rubric ids, learner commands, branch targets, prerequisites, competency goals, baseline task criteria, stretch signals, struggle signals, next concepts, and completion thresholds.
- `FR-05`: Selection policy now uses `next_concepts` graph links for continue and accelerate actions. Deterministic scoring uses configured concept `completion_thresholds` to gate continue and accelerate decisions. Further use of richer concept graph metadata can expand incrementally while preserving deterministic v1 behavior.
- `FR-05`: Lesson content must vary based on learner profile, assessment history, confidence, and current concept.
- `FR-05`: If a learner demonstrates competence beyond the prompt, Rust Sensei must support skipping, compressing, or increasing difficulty for future lessons.
- `FR-05`: If a learner struggles, Rust Sensei must support smaller prompts, repeated practice, and targeted remediation.

### 2.4 Assessment

- `FR-04`: Rust Sensei must assess submitted work across rubric dimensions including correctness, readability, maintainability, problem solving, DSA, Rust idioms, and compiler-error handling.
- `FR-04`: Each rubric dimension must produce a score, confidence value, and evidence summary.
- `FR-08`: Rust Sensei must accept assessment input containing assignment id, submitted code, relevant file paths, compiler output, runtime output, test output, learner notes, and agent notes when available.
- `FR-02`: Assessment must update both Rust-specific skill and general programming skill.
- `FR-04`: Assessment must support hybrid signals from code, command output, learner notes, and conversation summaries.
- `FR-04`: Rust Sensei owns canonical scoring and progression decisions. Agent notes are evidence or diagnostic context, not authoritative assessment results.
- `FR-04`: Rust Sensei may return insufficient evidence instead of assigning full rubric scores when critical artifacts are missing.
- `FR-04`: v1 may use deterministic rubric scoring, but the assessment service must keep a clear scorer boundary so later LLM-assisted assessment can be added without changing MCP tool contracts.
- `FR-04`: Any future LLM-assisted scorer must return structured scores, evidence, confidence, scoring version, and `scoring_provenance` model/provider metadata before the result is persisted as the canonical assessment.

### 2.5 Execution Flow

- `FR-07`: Lessons must encourage learner-owned execution before agent-run verification.
- `FR-07`: Early lessons must require the learner to practice commands such as `cargo new`, `cargo run`, `cargo check`, and later `cargo test`.
- `FR-07`: When the learner asks for assessment, Codex may run verification commands and submit the output to Rust Sensei.
- `FR-07`: When presenting a new assignment, the agent should create or reuse a lesson-specific Rust file in a stable lesson workspace path and open it in VS Code so the learner can start coding without creating files manually, except when the lesson explicitly teaches project setup such as `cargo new`.
- `FR-07`: After assessment, the agent should write a learner-readable lesson report file near the lesson workspace artifacts. The report is a convenience artifact; Rust Sensei JSON state remains canonical.
- `NFR-06`: Rust Sensei must not run arbitrary learner code in v1.

### 2.6 MCP Interface

- `FR-12`: Rust Sensei must expose MCP tools, resources, and prompts that are client-neutral.
- `FR-12`: Codex-specific setup belongs in documentation and config examples, not in core server logic.
- `FR-12`: Claude Code and other MCP clients should be able to call the same tools without server changes.

v1 MCP tools:

- `start_session`: Create or resume the active learner session.
- `get_next_lesson`: Return the active lesson assignment or create a new assignment when progression requires it.
- `submit_attempt`: Persist code, command output, notes, and context for a lesson assignment.
- `assess_attempt`: Assess an attempt exactly once and return scores, evidence, feedback, and next-step action.
- `get_learner_profile`: Return current learner profile and skill estimates.
- `get_progress_summary`: Return completed concepts, current concept, trend, and recommended focus.
- `update_learner_signal`: Record non-code signals such as confusion, confidence, or self-reported blockers.
- `get_setup_status`: Return setup checks and missing prerequisites.

v1 MCP resources:

- `rust-sensei://profile/active`: Read-only active learner profile.
- `rust-sensei://progress/summary`: Read-only progress summary derived from canonical events.
- `rust-sensei://curriculum/concepts`: Read-only curriculum concept inventory.

v1 MCP prompts:

- `rust_sensei_tutor`: General tutor behavior and coaching rules.
- `rust_sensei_attempt_review`: Attempt-review behavior using Rust Sensei assessment output.
- `rust_sensei_stuck_coaching`: Coaching behavior when the learner is blocked or confused.

Tools, resources, and prompts are v1 requirements. The current implementation exposes the listed tools, resources, and prompts; richer variants can be added after v1.

### 2.7 Local State And Setup

- `FR-09`: v1 must store learner state in local JSON.
- `FR-10`: Persistence must be accessed through repository interfaces.
- `FR-10`: JSON read-modify-write operations must use a single-writer lock and a state revision value to prevent lost updates.
- `FR-10`: Progress summaries must be derived from canonical records where possible.
- `FR-10`: Rust Sensei must persist lesson assignments, attempts, assessments, learner signals, and progress events for auditability.
- `FR-11`: v1 supports only `local-default` unless explicitly configured.
- `FR-11`: v1 must return a validation or not-found error for unsupported learner ids.
- `FR-13`: `get_setup_status` is the v1 MCP setup diagnostics path.
- `FR-13`: `doctor` wraps `get_setup_status` as a CLI diagnostic command with human and JSON output.

### 2.8 Session And Placement Protocol

- `FR-01`: `start_session` with no existing profile and no placement value must return `placement_required: true` and the allowed choices.
- `FR-01`: The agent must ask exactly 1 placement question using the allowed choices.
- `FR-01`: The agent must call `start_session` again with the selected placement value.
- `FR-01`: Rust Sensei must create the profile only after receiving a valid placement value.
- `FR-01`: After placement is persisted, Rust Sensei must not ask the placement question again for that learner.
- `FR-01`: Invalid placement values must return validation errors without creating a profile.

### 2.9 Assignment And Assessment Protocol

- `FR-05`: `get_next_lesson` must persist a `LessonAssignment` when it creates a new instructional assignment.
- `FR-05`: `get_next_lesson` must return the active unattempted assignment by default instead of creating duplicate assignments.
- `FR-05`: `get_next_lesson` must return a pending-assessment response when the active assignment has an attempt but no assessment.
- `FR-05`: A new assignment may be created after assessment changes progression, after explicit abandonment, or when the client requests a new variant through a defined parameter.
- `FR-08`: `submit_attempt` must persist an attempt and return a server-generated `attempt_id`.
- `FR-08`: `submit_attempt` must link each attempt to the exact `assignment_id` the learner received.
- `FR-04`: `assess_attempt` must be idempotent. Retrying it for an already assessed attempt returns the existing assessment and must not update skill scores twice.

Assessment status boundaries:

- Validation error: missing `assignment_id` or no assessable artifact. No attempt, assessment, or skill update is created.
- `insufficient_evidence`: attempt is accepted, but evidence is below the assessment threshold. The assessment is persisted and skill updates are skipped.
- Assessed with low confidence: scores are produced and skill updates are dampened.

## 3. Non-Functional Requirements

- `NFR-01`: The MCP server must be implemented in Python.
- `NFR-02`: v1 must run locally on the learner machine.
- `NFR-03`: v1 must not require Docker.
- `NFR-04`: MCP tools, resources, and prompts must be client-agnostic.
- `NFR-05`: Feedback must be coaching-oriented by default and become more direct as learner skill and confidence increase.
- `NFR-06`: The MCP server must not execute arbitrary learner code in v1.
- `NFR-07`: The package should support installation through `pipx` or `uv tool`.
- `NFR-08`: Storage adapter boundaries must be explicit.
- `NFR-09`: Local state writes must be atomic to reduce the chance of corrupt JSON.
- `NFR-10`: The server must be usable without network access after dependencies are installed.
- `NFR-11`: Local state updates must be protected from lost updates through file locking or an equivalent single-writer mechanism.

## 4. HLD Summary

Rust Sensei has 5 main subsystems:

1. MCP server interface
2. Learner state service
3. Curriculum engine
4. Assessment engine
5. Storage adapter

The MCP server receives tool calls from Codex or another MCP client. The learner state service reads the active profile and progress history. The curriculum engine selects the next concept, lesson prompt, success criteria, and rubric. The assessment engine scores submitted attempts and computes the next-step action. The storage adapter persists state in JSON for v1.

Codex is responsible for interacting with the workspace. Codex reads files, asks the learner for notes when useful, runs `cargo check`, `cargo run`, or `cargo test` when the learner requests assessment, and sends the collected context to Rust Sensei.

Rust Sensei is responsible for deciding what the learner should do next and why.

Core data concepts:

- Learner profile: learner id, initial Rust level, current skill estimates, preferences, and active path.
- Skill model: Rust concept scores, general programming scores, confidence, and evidence.
- Concept graph: current v1 stores ordered Rust concepts with variants, rubric ids, learner commands, branch targets, prerequisites, competency goals, baseline task criteria, stretch signals, struggle signals, next concepts, and completion thresholds. Current adaptive policy uses graph links, completion thresholds, and direct prerequisite reopening when later high-confidence evidence weakens a previously completed or skipped prerequisite.
- Lesson assignment: assignment id, lesson id, concept id, difficulty, variant id, selection rationale, curriculum version, status, and timestamps.
- Lesson attempt: assignment id, code, outputs, notes, timestamps, and workspace references.
- Assessment result: attempt id, scores, evidence, feedback, confidence, scoring version, and next-step action.
- Progress event: append-only record of assignment, attempt, assessment, reopening, abandonment, or view events in the implemented v1 flow. Event types also define completion, repeat, simplification, acceleration, branch, and skip events for granular adaptive telemetry.
- Repository interfaces: learner, curriculum, assessment, and session persistence boundaries.
- JSON storage adapter: v1 implementation of repository interfaces.

The v1 storage design supports 1 active learner, but the schema must include `learner_id` fields on learner, session, lesson assignment, attempt, assessment, learner signal, and progress event records. This supports later migration to multiple learners.

The v1 curriculum starts with general Rust fluency:

1. Environment, Cargo, and Hello World
2. Variables, primitive types, and printing
3. Mutability, shadowing, and compiler feedback
4. Functions and expression-based returns
5. Conditionals and control flow
6. Loops, arrays, vectors, and iteration
7. Ownership, borrowing, and references
8. Structs, enums, and pattern matching
9. Option, Result, and error handling
10. Modules, testing, and small projects

Placement rules:

- `new`: Start with environment, Cargo, and Hello World.
- `beginner`: Start with variables, mutability, functions, and compiler feedback.
- `intermediate`: Start with ownership, borrowing, structs, enums, or error handling.
- `proficient`: Start with idioms, traits, generics, testing, or applied project tasks.
- `expert`: Start with advanced review, performance, async, unsafe concepts, or architecture-level Rust tasks.

All placement rules are provisional. Assessment can slow down, repeat, skip, or accelerate the path.

## 5. HLD Diagram

```mermaid
flowchart LR
    Learner["1. User"] --> VSCode["2. VS Code Editor"]
    Learner --> Codex["3. Codex Agent"]
    VSCode --> Workspace["4. Rust Workspace on Disk"]
    Codex --> Workspace
    Codex --> Cargo["5. Cargo Commands"]
    Cargo --> Workspace
    Codex <--> MCP["6. Rust Sensei MCP Server"]
    MCP --> Curriculum["7. Curriculum Engine"]
    MCP --> Assessment["8. Assessment Engine"]
    MCP --> State["9. Learner State Repository"]
    State --> Json[("10. Local JSON Store")]
```

Diagram description:

1. User: Writes Rust code, runs commands, asks for help, and requests assessment.
2. VS Code Editor: Primary coding environment for the learner.
3. Codex Agent: Conversational agent that reads workspace files, runs verification commands, and calls Rust Sensei through MCP.
4. Rust Workspace on Disk: Shared source of truth for learner code, edited by the user and inspected by Codex.
5. Cargo Commands: `cargo check`, `cargo run`, and `cargo test` commands used for learner practice and agent verification.
6. Rust Sensei MCP Server: Local Python MCP server that exposes tutoring, assessment, progress, and setup tools.
7. Curriculum Engine: Selects concepts, lesson prompts, success criteria, hints, and next-step actions.
8. Assessment Engine: Scores attempts across Rust skill and general programming skill dimensions.
9. Learner State Repository: Persistence boundary for profile, session, progress, attempt, and assessment records.
10. Local JSON Store: v1 storage adapter for 1 local learner profile.

Requirement mapping:

- `FR-07`: The learner uses VS Code and Cargo before Codex verification.
- `FR-08`: Codex sends code and command output to Rust Sensei.
- `FR-09`: Learner state is stored in local JSON.
- `FR-12`: Codex uses MCP, but Rust Sensei remains client-neutral.
- `NFR-06`: Cargo execution is outside Rust Sensei.

## 6. User Perspective Flow

1. The learner opens a Rust workspace in VS Code.
2. The learner starts Codex in the same workspace.
3. Codex connects to the local Rust Sensei MCP server.
4. Codex calls `start_session`.
5. If no profile exists, Rust Sensei returns `placement_required: true` with allowed choices: `new`, `beginner`, `intermediate`, `proficient`, or `expert`. This satisfies `FR-01`.
6. Codex asks the learner the placement question and calls `start_session` again with the selected value.
7. Codex calls `get_next_lesson`.
8. Rust Sensei returns the active assignment or creates a new assignment with target concept, prompt, success criteria, hints, and rubric. This satisfies `FR-05`.
9. Codex creates or reuses a lesson-specific workspace file, such as a per-assignment `src/main.rs`, and opens it in VS Code. If the lesson explicitly teaches project setup such as `cargo new`, Codex instead opens the parent lesson directory and lets the learner create the package.
10. Codex explains the assignment to the learner.
11. The learner writes Rust code in the opened lesson file or in the learner-created package for project-setup lessons.
12. The learner runs the requested command in the VS Code terminal. Early commands include `cargo run` and `cargo check`. This satisfies `FR-07`.
13. The learner fixes errors or asks Codex for help.
14. When ready, the learner asks Codex to assess the work.
15. Codex reads the relevant files and runs verification commands such as `cargo check`, `cargo run`, or `cargo test`.
16. Codex calls `submit_attempt` with assignment id, code, command output, learner notes, file paths, and context. This satisfies `FR-08`.
17. Rust Sensei persists the attempt and returns a server-generated `attempt_id`.
18. Codex calls `assess_attempt` with the `attempt_id`.
19. Rust Sensei returns an existing assessment for duplicate assessment requests or creates one assessment for a new attempt.
20. Rust Sensei scores the attempt across rubric dimensions and updates learner state. This satisfies `FR-02`, `FR-03`, and `FR-04`.
21. Rust Sensei returns feedback, evidence, confidence, and one next-step action. The deterministic v1 scorer emits `simplify`, `repeat`, `continue`, `accelerate`, or high-confidence remediation/enrichment `branch` actions. This satisfies the current v1 subset of `FR-05`.
22. Codex writes a lesson report file with the prompt, file paths, command evidence, scores, confidence, feedback, and next action.
23. Codex presents coaching feedback and the next learning step.
24. The learner continues the cycle.

Example adaptive outcomes:

- If the learner creates 1 correct integer variable but struggles with strings, Rust Sensei returns `repeat` with a focused string task.
- If the learner creates multiple typed variables with meaningful names and explains inference, Rust Sensei returns `accelerate`.
- If the learner writes correct Rust but poor structure, Rust Sensei keeps the Rust concept moving and adds general code quality feedback.
- If the learner reports confusion despite compiling code, Rust Sensei lowers confidence and returns `simplify` or targeted hints.

## 7. Failure Scenarios

### 7.1 Rust Toolchain Missing

- Trigger: `get_setup_status`, Codex, or `doctor` cannot find `rustc`.
- Related requirements: `FR-07`, `FR-13`.
- Expected behavior: Rust Sensei reports setup incomplete and recommends installing Rust through `rustup`.
- Assessment behavior: Do not score Rust skill from failed setup alone.

### 7.2 Cargo Missing

- Trigger: `get_setup_status`, Codex, or `doctor` cannot find `cargo`.
- Related requirements: `FR-07`, `FR-13`.
- Expected behavior: Rust Sensei reports setup incomplete and blocks lessons that require Cargo commands.
- Assessment behavior: Record workflow blocker, not coding failure.

### 7.3 MCP Server Unavailable

- Trigger: Codex cannot connect to Rust Sensei.
- Related requirements: `FR-12`, `FR-13`.
- Expected behavior: Codex reports that the MCP server is unavailable and suggests running the configured server command.
- Assessment behavior: No learner state update occurs.

### 7.4 Invalid JSON State

- Trigger: JSON parse failure, missing required fields, or incompatible version.
- Related requirements: `FR-09`, `FR-10`, `NFR-09`.
- Expected behavior: Rust Sensei first attempts to restore the latest valid `state.json.bak` backup. If no valid backup exists, it refuses to overwrite the invalid file and reports the state path.
- Assessment behavior: Do not create new progress over invalid state unless backup recovery succeeds.

### 7.5 Learner Code Does Not Compile

- Trigger: `cargo check` returns a non-zero exit code.
- Related requirements: `FR-04`, `FR-07`, `FR-08`.
- Expected behavior: Rust Sensei assesses compiler-error handling, relevant concept understanding, and next remediation step.
- Assessment behavior: Compilation failure is evidence, not an automatic failure for every rubric dimension.

### 7.6 Codex Cannot Access Workspace

- Trigger: Codex cannot read files or run commands in the Rust workspace.
- Related requirements: `FR-08`, `FR-12`.
- Expected behavior: Codex asks the learner to open the correct workspace or provide pasted code and output.
- Assessment behavior: Rust Sensei may assess pasted code if provided.

### 7.7 Low Assessment Confidence

- Trigger: Submitted context lacks code, command output, learner notes, or enough evidence.
- Related requirements: `FR-02`, `FR-04`, `FR-05`.
- Expected behavior: Rust Sensei returns a low confidence result and requests one additional concrete signal.
- Assessment behavior: Skill estimates must change less than they would for a high-confidence assessment.

### 7.8 Wrong Difficulty Selected

- Trigger: Learner feedback or next attempt shows the selected lesson was too easy or too hard.
- Related requirements: `FR-02`, `FR-05`, `NFR-05`.
- Expected behavior: Rust Sensei updates confidence and selects `simplify`, `repeat`, or `accelerate` on the next step.
- Assessment behavior: Wrong difficulty is treated as calibration data, not as learner failure.

### 7.9 Agent Submits Incomplete Attempt

- Trigger: Missing assignment id or missing all assessable artifacts.
- Related requirements: `FR-08`, `NFR-04`.
- Expected behavior: Rust Sensei returns a structured validation error when `assignment_id` is missing or no assessable artifact is present.
- Assessment behavior: Missing code or missing command output may produce low confidence or `insufficient_evidence` when another assessable artifact exists. No learner skill update occurs for validation errors.

### 7.10 Storage Path Not Writable

- Trigger: JSON state directory cannot be created or written.
- Related requirements: `FR-09`, `FR-13`, `NFR-09`.
- Expected behavior: Rust Sensei reports the path and required permission.
- Assessment behavior: No assessment should be accepted if progress cannot be persisted.

### 7.11 Concurrent State Update

- Trigger: 2 mutating MCP calls attempt to update JSON state at the same time.
- Related requirements: `FR-10`, `NFR-11`.
- Expected behavior: Rust Sensei serializes writes through a lock or returns a retryable conflict error.
- Assessment behavior: No skill score should be updated from stale state.

### 7.12 Duplicate Lesson Request

- Trigger: The agent calls `get_next_lesson` multiple times before the learner submits an attempt.
- Related requirements: `FR-05`, `FR-10`.
- Expected behavior: Rust Sensei returns the active unattempted assignment and records a view event instead of creating duplicate assignments.
- Assessment behavior: Prompt-repeat logic should count created assignments, not view events.

## Appendix A. Future Changes

### A.1 Future Changes Discussed

- Multi-learner support: v1 supports 1 active learner, but records include `learner_id` so later versions can support multiple local profiles or hosted users.
- Database storage: v1 uses JSON, but repository interfaces should allow a later SQLite or hosted database adapter without changing MCP tools or assessment logic.
- Other MCP clients: Codex is the primary documented client for v1, but Claude Code and other MCP clients should be supported through the same tools.
- Packaged installation: Later versions should support `pipx install rust-sensei` or `uv tool install rust-sensei`.
- `doctor` command: v1 wraps Python, rustc, Cargo, and state path setup diagnostics. Later versions should also check lesson catalog validity and MCP startup.
- Specialized tracks: After general Rust fluency, later versions can add CLI, backend, async, performance, systems programming, and LeetCode-style tracks.
- Optional code runner: v1 does not execute learner code inside Rust Sensei. A later version may add a sandboxed runner behind a separate interface.
- LLM-assisted assessment: v1 deterministic scoring is a baseline for idempotency and local operation, not the final code-understanding strategy. A later version should add an assessment provider interface that can use an LLM to judge Rust idioms, compiler-error handling, and problem solving while preserving persisted scoring versions, evidence, confidence, and retry idempotency.
- Richer editor integration: VS Code is the target editor for v1. Later versions may add editor-specific helpers for debugger practice, rust-analyzer diagnostics, or current-file submission.
- Hosted mode: Later versions may support remote accounts, synced progress, and team or classroom usage. This is outside v1.

### A.2 Requirement Traceability

| Requirement | Owning section | Primary LLD |
| --- | --- | --- |
| `FR-01` | Learner placement and session protocol | MCP server, AI agent |
| `FR-02` | Skill updates from demonstrated work | Confidence measuring, adaptive lessons |
| `FR-03` | Separate Rust and programming skill | MCP server, confidence measuring |
| `FR-04` | Assessment and scoring | MCP server, confidence measuring |
| `FR-05` | Adaptive progression | Adaptive lessons |
| `FR-06` | General Rust fluency path | Adaptive lessons |
| `FR-07` | Learner-owned execution | AI agent |
| `FR-08` | Attempt submission | MCP server, AI agent |
| `FR-09` | Local JSON state | MCP server |
| `FR-10` | Persistence abstraction and audit history | MCP server |
| `FR-11` | Single learner v1, multi-learner-ready schema | MCP server |
| `FR-12` | Agent-neutral MCP interface | MCP server, AI agent |
| `FR-13` | Setup diagnostics | MCP server |
