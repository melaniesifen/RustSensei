from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.domain.enums import AssignmentStatus, NextAction
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.domain.scoring import AssessmentScorer, DeterministicAssessmentScorer
from rust_sensei.domain.skill_update import update_skill_model
from rust_sensei.dto.assessment import AssessAttemptRequest, AssessAttemptResponse
from rust_sensei.dto.attempt import (
    CommandRunMetadataDTO,
    SubmitAttemptRequest,
    SubmitAttemptResponse,
)
from rust_sensei.dto.mappers import (
    assessment_result_to_dto,
    command_metadata_from_dto,
)
from rust_sensei.errors import (
    idempotency_conflict_error,
    not_found_error,
    validation_error,
)
from rust_sensei.repositories.interfaces import (
    AssessmentRepository,
    AssignmentRepository,
    AttemptRepository,
    CurriculumRepository,
    LearnerRepository,
)

LOGGER = logging.getLogger(__name__)
ADAPTIVE_EVENT_TYPE_BY_NEXT_ACTION = {
    NextAction.CONTINUE: ProgressEventType.COMPLETED,
    NextAction.REPEAT: ProgressEventType.REPEATED,
    NextAction.SIMPLIFY: ProgressEventType.SIMPLIFIED,
    NextAction.ACCELERATE: ProgressEventType.ACCELERATED,
    NextAction.BRANCH: ProgressEventType.BRANCHED,
}
COMMAND_METADATA_SOURCES = {"learner", "agent"}
MAX_CODE_CHARS = 50_000
MAX_OUTPUT_CHARS = 30_000
MAX_NOTES_CHARS = 10_000
MAX_PATH_CHARS = 500
MAX_FILE_PATHS = 20
MAX_OMITTED_FILES = 50
MAX_COMMAND_METADATA_ITEMS = 20
MAX_COMMAND_CHARS = 500
MAX_COMMAND_PURPOSE_CHARS = 500
MAX_COMMAND_OUTPUT_SUMMARY_CHARS = 5_000
SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    ".envrc",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "known_hosts",
}
SENSITIVE_FILE_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)


class AssessmentService:
    def __init__(
        self,
        assignment_repository: AssignmentRepository,
        attempt_repository: AttemptRepository,
        assessment_repository: AssessmentRepository,
        curriculum_repository: CurriculumRepository,
        learner_repository: LearnerRepository,
        now: Callable[[], datetime],
        scorer: AssessmentScorer | None = None,
    ) -> None:
        self._assignment_repository = assignment_repository
        self._attempt_repository = attempt_repository
        self._assessment_repository = assessment_repository
        self._curriculum_repository = curriculum_repository
        self._learner_repository = learner_repository
        self._now = now
        self._scorer = scorer or DeterministicAssessmentScorer()

    def submit_attempt(self, request: SubmitAttemptRequest) -> SubmitAttemptResponse:
        self._validate_request(request)
        assignment = self._assignment_repository.get_assignment(request.assignment_id)
        if assignment is None:
            raise not_found_error(
                "assignment_id was not found",
                assignment_id=request.assignment_id,
            )

        if assignment.learner_id != request.learner_id:
            raise validation_error(
                "assignment_id does not belong to learner_id",
                assignment_id=request.assignment_id,
                learner_id=request.learner_id,
            )

        if assignment.status != AssignmentStatus.ACTIVE:
            existing = self._existing_attempt_for_request(request)
            if existing is not None and existing.assignment_id == assignment.assignment_id:
                return SubmitAttemptResponse(
                    attempt_id=existing.attempt_id,
                    already_submitted=True,
                )
            raise validation_error(
                "assignment_id is not active",
                assignment_id=request.assignment_id,
                status=assignment.status.value,
            )

        now = self._now()
        attempt = _attempt_from_request(request, assignment.lesson_id, now)
        updated_assignment = replace(
            assignment,
            status=AssignmentStatus.ATTEMPTED,
            updated_at=now,
        )
        saved, created = self._attempt_repository.save_attempt_for_assignment(
            attempt,
            updated_assignment,
            event_factory=lambda saved_attempt: ProgressEvent(
                event_id="",
                learner_id=saved_attempt.learner_id,
                event_type=ProgressEventType.ATTEMPT_SUBMITTED,
                assignment_id=saved_attempt.assignment_id,
                attempt_id=saved_attempt.attempt_id,
                assessment_id=None,
                details={
                    "lesson_id": saved_attempt.lesson_id,
                    "has_code": bool(saved_attempt.code),
                    "has_execution_output": bool(
                        saved_attempt.compiler_output
                        or saved_attempt.runtime_output
                        or saved_attempt.test_output
                    ),
                },
                previous_status=AssignmentStatus.ACTIVE.value,
                new_status=AssignmentStatus.ATTEMPTED.value,
                created_at=now,
            ),
        )
        if created:
            LOGGER.info(
                "Submitted attempt attempt_id=%s assignment_id=%s learner_id=%s",
                saved.attempt_id,
                saved.assignment_id,
                saved.learner_id,
            )
        return SubmitAttemptResponse(
            attempt_id=saved.attempt_id,
            already_submitted=not created,
        )

    def assess_attempt(self, request: AssessAttemptRequest) -> AssessAttemptResponse:
        if not request.attempt_id:
            raise validation_error("attempt_id is required", field="attempt_id")

        existing = self._assessment_repository.get_assessment_by_attempt_id(
            request.attempt_id
        )
        if existing is not None:
            return AssessAttemptResponse(
                assessment=assessment_result_to_dto(existing),
                already_assessed=True,
            )

        attempt = self._attempt_repository.get_attempt(request.attempt_id)
        if attempt is None:
            raise not_found_error(
                "attempt_id was not found",
                attempt_id=request.attempt_id,
            )
        self._validate_attempt_for_assessment(attempt)

        assignment = self._assignment_repository.get_assignment(attempt.assignment_id)
        if assignment is None:
            raise not_found_error(
                "assignment_id was not found",
                assignment_id=attempt.assignment_id,
            )
        if assignment.learner_id != attempt.learner_id:
            raise validation_error(
                "attempt assignment does not belong to learner_id",
                assignment_id=assignment.assignment_id,
                learner_id=attempt.learner_id,
            )
        if assignment.status != AssignmentStatus.ATTEMPTED:
            raise validation_error(
                "assignment_id is not ready for assessment",
                assignment_id=assignment.assignment_id,
                status=assignment.status.value,
            )

        concept = self._curriculum_repository.get_concept(assignment.concept_id)
        if concept is None:
            raise not_found_error(
                "Curriculum concept was not found",
                concept_id=assignment.concept_id,
            )
        profile = self._learner_repository.get_profile(attempt.learner_id)
        if profile is None:
            raise not_found_error(
                "Learner profile was not found",
                learner_id=attempt.learner_id,
            )

        now = self._now()
        candidate = self._scorer.score_attempt(
            attempt=attempt,
            concept=concept,
            difficulty=assignment.difficulty,
            now=now,
        )
        if candidate.scoring_provenance is None:
            raise validation_error(
                "Assessment scorer did not provide scoring provenance",
                scoring_version=candidate.scoring_version,
            )
        updated_assignment = replace(
            assignment,
            status=AssignmentStatus.ASSESSED,
            updated_at=now,
        )
        saved, created = (
            self._assessment_repository.save_assessment_for_assignment_and_profile(
                candidate,
                updated_assignment,
                lambda saved_assessment, current_profile: replace(
                    current_profile,
                    skill_model=update_skill_model(
                        model=current_profile.skill_model,
                        assessment=saved_assessment,
                        concept_id=assignment.concept_id,
                    ),
                    updated_at=now,
                ),
                event_factory=lambda saved_assessment: _assessment_progress_events(
                    saved_assessment=saved_assessment,
                    assignment=assignment,
                    learner_id=attempt.learner_id,
                    now=now,
                ),
            )
        )
        if created:
            LOGGER.info(
                "Assessed attempt attempt_id=%s assessment_id=%s learner_id=%s",
                saved.attempt_id,
                saved.assessment_id,
                attempt.learner_id,
            )
        return AssessAttemptResponse(
            assessment=assessment_result_to_dto(saved),
            already_assessed=not created,
        )

    def _existing_attempt_for_request(
        self,
        request: SubmitAttemptRequest,
    ) -> AttemptSubmission | None:
        if request.client_request_id is None:
            return None

        existing = self._attempt_repository.get_attempt_by_client_request_id(
            request.learner_id,
            request.client_request_id,
        )
        if existing is None:
            return None

        if existing.client_request_fingerprint != request.client_request_fingerprint:
            raise idempotency_conflict_error(
                "client_request_id was reused with different content",
                client_request_id=request.client_request_id,
            )

        return existing

    @staticmethod
    def _validate_request(request: SubmitAttemptRequest) -> None:
        if request.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=request.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )

        if not request.assignment_id:
            raise validation_error("assignment_id is required", field="assignment_id")

        if not _has_assessable_artifact(request):
            raise validation_error(
                "At least 1 assessable artifact is required",
                fields=[
                    "code",
                    "compiler_output",
                    "runtime_output",
                    "test_output",
                    "command_run_metadata",
                ],
            )
        _validate_artifact_limits(request)
        _validate_file_paths(request.file_paths, "file_paths", MAX_FILE_PATHS)
        _validate_file_paths(request.omitted_files, "omitted_files", MAX_OMITTED_FILES)
        _validate_command_metadata_limits(request.command_run_metadata)
        if request.output_truncated and not _has_text(request.truncation_reason):
            raise validation_error(
                "truncation_reason is required when output_truncated is true",
                field="truncation_reason",
            )

    @staticmethod
    def _validate_attempt_for_assessment(attempt: AttemptSubmission) -> None:
        if attempt.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=attempt.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )

        if not _attempt_has_assessable_artifact(attempt):
            raise validation_error(
                "Attempt does not contain an assessable artifact",
                attempt_id=attempt.attempt_id,
            )


def _attempt_from_request(
    request: SubmitAttemptRequest,
    lesson_id: str,
    submitted_at: datetime,
) -> AttemptSubmission:
    return AttemptSubmission(
        attempt_id="",
        learner_id=request.learner_id,
        assignment_id=request.assignment_id,
        lesson_id=lesson_id,
        client_request_id=request.client_request_id,
        client_request_fingerprint=request.client_request_fingerprint,
        workspace_root=request.workspace_root,
        code=request.code,
        file_paths=list(request.file_paths),
        commands_run_by_learner=list(request.commands_run_by_learner),
        verification_commands_run_by_agent=list(
            request.verification_commands_run_by_agent
        ),
        compiler_output=request.compiler_output,
        runtime_output=request.runtime_output,
        test_output=request.test_output,
        command_run_metadata=[
            command_metadata_from_dto(item)
            for item in request.command_run_metadata
        ],
        output_truncated=request.output_truncated,
        truncation_reason=request.truncation_reason,
        omitted_files=list(request.omitted_files),
        learner_notes=request.learner_notes,
        agent_notes=request.agent_notes,
        learner_execution_missing=request.learner_execution_missing,
        learner_execution_notes=request.learner_execution_notes,
        submitted_at=submitted_at,
    )


def _assessment_progress_events(
    saved_assessment: AssessmentResult,
    assignment: LessonAssignment,
    learner_id: str,
    now: datetime,
) -> list[ProgressEvent]:
    common_details = {
        "lesson_id": assignment.lesson_id,
        "concept_id": assignment.concept_id,
        "assessment_status": saved_assessment.assessment_status,
        "confidence": saved_assessment.confidence,
        "next_action": saved_assessment.next_action.value,
        "next_action_reason": saved_assessment.next_action_reason,
    }
    if saved_assessment.branch_id is not None:
        common_details["branch_id"] = saved_assessment.branch_id

    assessed_event = _assessment_progress_event(
        saved_assessment=saved_assessment,
        learner_id=learner_id,
        event_type=ProgressEventType.ASSESSED,
        details=common_details,
        now=now,
    )
    adaptive_event = _assessment_progress_event(
        saved_assessment=saved_assessment,
        learner_id=learner_id,
        event_type=ADAPTIVE_EVENT_TYPE_BY_NEXT_ACTION[saved_assessment.next_action],
        details=common_details,
        now=now,
    )
    return [assessed_event, adaptive_event]


def _assessment_progress_event(
    saved_assessment: AssessmentResult,
    learner_id: str,
    event_type: ProgressEventType,
    details: dict[str, Any],
    now: datetime,
) -> ProgressEvent:
    return ProgressEvent(
        event_id="",
        learner_id=learner_id,
        event_type=event_type,
        assignment_id=saved_assessment.assignment_id,
        attempt_id=saved_assessment.attempt_id,
        assessment_id=saved_assessment.assessment_id,
        details=dict(details),
        previous_status=AssignmentStatus.ATTEMPTED.value,
        new_status=AssignmentStatus.ASSESSED.value,
        created_at=now,
    )


def _has_assessable_artifact(request: SubmitAttemptRequest) -> bool:
    return any(
        [
            _has_text(request.code),
            _has_text(request.compiler_output),
            _has_text(request.runtime_output),
            _has_text(request.test_output),
            any(
                _is_complete_command_metadata(item)
                for item in request.command_run_metadata
            ),
        ]
    )


def _is_complete_command_metadata(item: Any) -> bool:
    return all(
        [
            _has_text(item.command),
            item.source in COMMAND_METADATA_SOURCES,
            item.exit_code is not None,
            item.started_at,
            _has_text(item.output_summary),
        ]
    )


def _attempt_has_assessable_artifact(attempt: AttemptSubmission) -> bool:
    return any(
        [
            _has_text(attempt.code),
            _has_text(attempt.compiler_output),
            _has_text(attempt.runtime_output),
            _has_text(attempt.test_output),
            any(
                _is_complete_command_metadata(item)
                for item in attempt.command_run_metadata
            ),
        ]
    )


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _validate_artifact_limits(request: SubmitAttemptRequest) -> None:
    _validate_text_size(request.code, "code", MAX_CODE_CHARS)
    for field_name in ["compiler_output", "runtime_output", "test_output"]:
        _validate_text_size(
            getattr(request, field_name),
            field_name,
            MAX_OUTPUT_CHARS,
        )
    for field_name in [
        "learner_notes",
        "agent_notes",
        "learner_execution_notes",
        "truncation_reason",
    ]:
        _validate_text_size(
            getattr(request, field_name),
            field_name,
            MAX_NOTES_CHARS,
        )
    _validate_text_size(request.workspace_root, "workspace_root", MAX_PATH_CHARS)


def _validate_text_size(value: str | None, field_name: str, max_chars: int) -> None:
    if value is not None and len(value) > max_chars:
        raise validation_error(
            f"{field_name} exceeds maximum length",
            field=field_name,
            max_chars=max_chars,
        )


def _validate_file_paths(
    paths: list[str],
    field_name: str,
    max_count: int,
) -> None:
    if len(paths) > max_count:
        raise validation_error(
            f"{field_name} contains too many paths",
            field=field_name,
            max_count=max_count,
        )

    for path in paths:
        _validate_text_size(path, field_name, MAX_PATH_CHARS)
        if _is_sensitive_path(path):
            raise validation_error(
                "attempt evidence must not include secret-bearing file paths",
                field=field_name,
                path=path,
            )


def _is_sensitive_path(path: str) -> bool:
    parts = [part.lower() for part in path.replace("\\", "/").split("/") if part]
    if any(part in SENSITIVE_FILE_NAMES for part in parts):
        return True
    if not parts:
        return False
    return parts[-1].endswith(SENSITIVE_FILE_SUFFIXES)


def _validate_command_metadata_limits(
    metadata_items: list[CommandRunMetadataDTO],
) -> None:
    if len(metadata_items) > MAX_COMMAND_METADATA_ITEMS:
        raise validation_error(
            "command_run_metadata contains too many items",
            field="command_run_metadata",
            max_count=MAX_COMMAND_METADATA_ITEMS,
        )

    for index, item in enumerate(metadata_items):
        field_prefix = f"command_run_metadata[{index}]"
        _validate_text_size(
            item.command,
            f"{field_prefix}.command",
            MAX_COMMAND_CHARS,
        )
        _validate_text_size(item.cwd, f"{field_prefix}.cwd", MAX_PATH_CHARS)
        _validate_text_size(
            item.output_summary,
            f"{field_prefix}.output_summary",
            MAX_COMMAND_OUTPUT_SUMMARY_CHARS,
        )
        _validate_text_size(
            item.purpose,
            f"{field_prefix}.purpose",
            MAX_COMMAND_PURPOSE_CHARS,
        )
