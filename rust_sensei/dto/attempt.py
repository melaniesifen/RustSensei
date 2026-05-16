from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.dto.common import StrictDTO


class CommandRunMetadataDTO(StrictDTO):
    command: str
    source: Literal["learner", "agent"]
    cwd: str | None = None
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
    risk_level: Literal["low", "medium", "high"] | None = None


class SubmitAttemptRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID
    assignment_id: str
    client_request_id: str | None = None
    client_request_fingerprint: str | None = None
    workspace_root: str | None = None
    code: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    commands_run_by_learner: list[str] = Field(default_factory=list)
    verification_commands_run_by_agent: list[str] = Field(default_factory=list)
    compiler_output: str | None = None
    runtime_output: str | None = None
    test_output: str | None = None
    command_run_metadata: list[CommandRunMetadataDTO] = Field(default_factory=list)
    output_truncated: bool = False
    truncation_reason: str | None = None
    omitted_files: list[str] = Field(default_factory=list)
    learner_notes: str | None = None
    agent_notes: str | None = None
    learner_execution_missing: bool = False
    learner_execution_notes: str | None = None


class SubmitAttemptResponse(StrictDTO):
    attempt_id: str
    already_submitted: bool
