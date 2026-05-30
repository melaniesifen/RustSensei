from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rust_sensei.agent_workflow import (
    PreparedAgentLesson,
    build_submit_attempt_request,
    open_with_vscode,
    prepare_agent_lesson,
    write_agent_lesson_report,
)
from rust_sensei.dto.assessment import AssessmentResultDTO
from rust_sensei.dto.attempt import CommandRunMetadataDTO, SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonResponse


@dataclass(frozen=True)
class CodexCommandEvidence:
    commands_run_by_learner: Sequence[str] = ()
    verification_commands_run_by_agent: Sequence[str] = ()
    compiler_output: str | None = None
    runtime_output: str | None = None
    test_output: str | None = None
    command_run_metadata: Sequence[CommandRunMetadataDTO] = ()
    output_truncated: bool = False
    truncation_reason: str | None = None
    omitted_files: Sequence[str] = ()
    learner_execution_missing: bool = False
    learner_execution_notes: str | None = None


def prepare_lesson_for_codex(
    lesson_response: GetNextLessonResponse,
    learner_workspace: Path,
    *,
    open_editor: bool = False,
    code_command: str = "code",
) -> PreparedAgentLesson:
    """Prepare a Rust Sensei lesson in a Codex-owned learner workspace.

    This example keeps editor control outside the MCP server. It opens VS Code
    only when the caller opts in.
    """
    opener = None
    if open_editor:

        def open_path(path: Path) -> None:
            open_with_vscode(path, command=code_command)

        opener = open_path

    return prepare_agent_lesson(
        lesson_response,
        learner_workspace,
        opener=opener,
    )


def build_codex_attempt_request(
    prepared_lesson: PreparedAgentLesson,
    evidence: CodexCommandEvidence,
    *,
    client_request_id: str | None = None,
    client_request_fingerprint: str | None = None,
    code: str | None = None,
    read_lesson_file: bool = True,
    extra_file_paths: Sequence[Path] = (),
    learner_notes: str | None = None,
    agent_notes: str | None = None,
) -> SubmitAttemptRequest:
    """Build a submit_attempt request from Codex-collected local evidence."""
    return build_submit_attempt_request(
        prepared_lesson,
        client_request_id=client_request_id,
        client_request_fingerprint=client_request_fingerprint,
        include_workspace_root=False,
        code=code,
        read_lesson_file=read_lesson_file,
        extra_file_paths=extra_file_paths,
        commands_run_by_learner=evidence.commands_run_by_learner,
        verification_commands_run_by_agent=evidence.verification_commands_run_by_agent,
        compiler_output=evidence.compiler_output,
        runtime_output=evidence.runtime_output,
        test_output=evidence.test_output,
        command_run_metadata=evidence.command_run_metadata,
        output_truncated=evidence.output_truncated,
        truncation_reason=evidence.truncation_reason,
        omitted_files=evidence.omitted_files,
        learner_notes=learner_notes,
        agent_notes=agent_notes,
        learner_execution_missing=evidence.learner_execution_missing,
        learner_execution_notes=evidence.learner_execution_notes,
    )


def write_codex_assessment_report(
    prepared_lesson: PreparedAgentLesson,
    assessment: AssessmentResultDTO,
    *,
    attempt: SubmitAttemptRequest,
    agent_guidance: str | None = None,
) -> Path:
    """Write the learner-readable report after assess_attempt returns."""
    return write_agent_lesson_report(
        prepared_lesson,
        assessment,
        attempt=attempt,
        agent_guidance=agent_guidance,
    )
