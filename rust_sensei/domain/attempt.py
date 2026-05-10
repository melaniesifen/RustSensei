from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CommandRunMetadata:
    command: str
    source: str
    cwd: str | None
    exit_code: int | None
    started_at: datetime
    duration_ms: int | None = None
    timed_out: bool = False
    timeout_ms: int | None = None
    output_summary: str | None = None
    output_truncated: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    purpose: str | None = None
    risk_level: str | None = None


@dataclass(frozen=True)
class AttemptSubmission:
    attempt_id: str
    learner_id: str
    assignment_id: str
    lesson_id: str
    client_request_id: str | None
    client_request_fingerprint: str | None
    workspace_root: str | None
    code: str | None
    file_paths: list[str] = field(default_factory=list)
    commands_run_by_learner: list[str] = field(default_factory=list)
    verification_commands_run_by_agent: list[str] = field(default_factory=list)
    compiler_output: str | None = None
    runtime_output: str | None = None
    test_output: str | None = None
    command_run_metadata: list[CommandRunMetadata] = field(default_factory=list)
    output_truncated: bool = False
    truncation_reason: str | None = None
    omitted_files: list[str] = field(default_factory=list)
    learner_notes: str | None = None
    agent_notes: str | None = None
    learner_execution_missing: bool = False
    learner_execution_notes: str | None = None
    submitted_at: datetime | None = None
