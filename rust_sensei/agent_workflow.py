from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rust_sensei.agent_report import write_lesson_report
from rust_sensei.agent_workspace import (
    PreparedLessonWorkspace,
    prepare_lesson_workspace,
)
from rust_sensei.dto.assessment import AssessmentResultDTO
from rust_sensei.dto.attempt import CommandRunMetadataDTO, SubmitAttemptRequest
from rust_sensei.dto.lesson import (
    GetNextLessonResponse,
    LessonAssignmentDTO,
    LessonPlanDTO,
)

LessonOpener = Callable[[Path], None]


@dataclass(frozen=True)
class PreparedAgentLesson:
    assignment: LessonAssignmentDTO
    lesson_plan: LessonPlanDTO
    workspace_root: Path
    workspace: PreparedLessonWorkspace
    generated_file_paths: tuple[str, ...]
    opened_path: Path | None


def prepare_agent_lesson(
    lesson_response: GetNextLessonResponse,
    workspace_root: Path,
    *,
    opener: LessonOpener | None = None,
) -> PreparedAgentLesson:
    assignment = lesson_response.assignment
    lesson_plan = lesson_response.lesson_plan
    suggestion = lesson_response.workspace_suggestion

    if lesson_response.pending_assessment:
        raise ValueError("pending-assessment responses do not have lesson workspaces")
    if assignment is None or lesson_plan is None or suggestion is None:
        raise ValueError(
            "lesson response must include assignment, plan, and workspace suggestion"
        )
    if suggestion.assignment_id != assignment.assignment_id:
        raise ValueError("workspace suggestion assignment_id must match assignment")
    _validate_assignment_plan(assignment, lesson_plan)

    prepared_workspace = prepare_lesson_workspace(suggestion, workspace_root)
    resolved_root = workspace_root.expanduser().resolve(strict=False)
    generated_file_paths = (
        ()
        if prepared_workspace.lesson_file_path is None
        else (_relative_posix(resolved_root, prepared_workspace.lesson_file_path),)
    )

    opened_path = None
    if opener is not None:
        opener(prepared_workspace.open_path)
        opened_path = prepared_workspace.open_path

    return PreparedAgentLesson(
        assignment=assignment,
        lesson_plan=lesson_plan,
        workspace_root=resolved_root,
        workspace=prepared_workspace,
        generated_file_paths=generated_file_paths,
        opened_path=opened_path,
    )


def build_submit_attempt_request(
    prepared_lesson: PreparedAgentLesson,
    *,
    client_request_id: str | None = None,
    client_request_fingerprint: str | None = None,
    include_workspace_root: bool = False,
    code: str | None = None,
    read_lesson_file: bool = True,
    extra_file_paths: Sequence[Path] = (),
    commands_run_by_learner: Sequence[str] = (),
    verification_commands_run_by_agent: Sequence[str] = (),
    compiler_output: str | None = None,
    runtime_output: str | None = None,
    test_output: str | None = None,
    command_run_metadata: Sequence[CommandRunMetadataDTO] = (),
    output_truncated: bool = False,
    truncation_reason: str | None = None,
    omitted_files: Sequence[str] = (),
    learner_notes: str | None = None,
    agent_notes: str | None = None,
    learner_execution_missing: bool = False,
    learner_execution_notes: str | None = None,
) -> SubmitAttemptRequest:
    collected_code = code
    lesson_file_path = prepared_lesson.workspace.lesson_file_path
    if collected_code is None and read_lesson_file and lesson_file_path is not None:
        collected_code = lesson_file_path.read_text(encoding="utf-8")

    file_paths = _dedupe(
        [
            *prepared_lesson.generated_file_paths,
            *[
                _relative_posix(prepared_lesson.workspace_root, path)
                for path in extra_file_paths
            ],
        ]
    )

    return SubmitAttemptRequest(
        assignment_id=prepared_lesson.assignment.assignment_id,
        client_request_id=client_request_id,
        client_request_fingerprint=client_request_fingerprint,
        workspace_root=(
            str(prepared_lesson.workspace_root) if include_workspace_root else None
        ),
        code=collected_code,
        file_paths=file_paths,
        commands_run_by_learner=list(commands_run_by_learner),
        verification_commands_run_by_agent=list(verification_commands_run_by_agent),
        compiler_output=compiler_output,
        runtime_output=runtime_output,
        test_output=test_output,
        command_run_metadata=list(command_run_metadata),
        output_truncated=output_truncated,
        truncation_reason=truncation_reason,
        omitted_files=list(omitted_files),
        learner_notes=learner_notes,
        agent_notes=agent_notes,
        learner_execution_missing=learner_execution_missing,
        learner_execution_notes=learner_execution_notes,
    )


def write_agent_lesson_report(
    prepared_lesson: PreparedAgentLesson,
    assessment: AssessmentResultDTO,
    *,
    attempt: SubmitAttemptRequest | None = None,
    agent_guidance: str | None = None,
) -> Path:
    return write_lesson_report(
        prepared_lesson.workspace.report_file_path,
        assignment=prepared_lesson.assignment,
        lesson_plan=prepared_lesson.lesson_plan,
        assessment=assessment,
        lesson_file_path=(
            None
            if prepared_lesson.workspace.lesson_file_path is None
            else _relative_posix(
                prepared_lesson.workspace_root,
                prepared_lesson.workspace.lesson_file_path,
            )
        ),
        submitted_file_paths=(
            prepared_lesson.generated_file_paths
            if attempt is None
            else attempt.file_paths
        ),
        commands_run_by_learner=(
            ()
            if attempt is None
            else attempt.commands_run_by_learner
        ),
        verification_commands_run_by_agent=(
            ()
            if attempt is None
            else attempt.verification_commands_run_by_agent
        ),
        agent_guidance=agent_guidance,
    )


def open_with_vscode(path: Path, *, command: str = "code") -> None:
    subprocess.run([command, str(path)], check=True)


def _validate_assignment_plan(
    assignment: LessonAssignmentDTO,
    lesson_plan: LessonPlanDTO,
) -> None:
    if assignment.lesson_id != lesson_plan.lesson_id:
        raise ValueError("assignment.lesson_id must match lesson_plan.lesson_id")
    if assignment.concept_id != lesson_plan.concept_id:
        raise ValueError("assignment.concept_id must match lesson_plan.concept_id")


def _relative_posix(root: Path, path: Path) -> str:
    resolved_root = root.expanduser().resolve(strict=False)
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = resolved_root / candidate
    resolved_path = candidate.resolve(strict=False)
    if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
        raise ValueError(f"path must be inside the workspace root: {path}")
    return resolved_path.relative_to(resolved_root).as_posix()


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
