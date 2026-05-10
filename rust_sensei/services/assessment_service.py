from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.dto.attempt import CommandRunMetadataDTO
from rust_sensei.domain.enums import AssignmentStatus
from rust_sensei.dto.attempt import SubmitAttemptRequest, SubmitAttemptResponse
from rust_sensei.dto.mappers import command_metadata_from_dto
from rust_sensei.errors import (
    idempotency_conflict_error,
    not_found_error,
    validation_error,
)
from rust_sensei.repositories.interfaces import AssignmentRepository, AttemptRepository

LOGGER = logging.getLogger(__name__)


class AssessmentService:
    def __init__(
        self,
        assignment_repository: AssignmentRepository,
        attempt_repository: AttemptRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._assignment_repository = assignment_repository
        self._attempt_repository = attempt_repository
        self._now = now

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


def _has_assessable_artifact(request: SubmitAttemptRequest) -> bool:
    return any(
        [
            bool(request.code),
            bool(request.compiler_output),
            bool(request.runtime_output),
            bool(request.test_output),
            any(_is_complete_command_metadata(item) for item in request.command_run_metadata),
        ]
    )


def _is_complete_command_metadata(item: CommandRunMetadataDTO) -> bool:
    return all(
        [
            item.command,
            item.source,
            item.exit_code is not None,
            item.started_at,
            item.output_summary,
        ]
    )
