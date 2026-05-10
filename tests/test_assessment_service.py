from datetime import datetime, timezone

import pytest
from pydantic import ValidationError as PydanticValidationError

from rust_sensei.domain.enums import AssignmentStatus, RustLevel
from rust_sensei.dto.attempt import CommandRunMetadataDTO, SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import IdempotencyConflictError, NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.assessment_service import AssessmentService
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.session_service import SessionService


def test_submit_attempt_persists_attempt_and_marks_assignment_attempted(tmp_path):
    _, lesson_service, assessment_service, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    response = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code='fn main() { println!("Hello, Rust Sensei"); }',
            compiler_output="Finished dev profile",
        )
    )

    attempt = repositories.attempt_repository().get_attempt(response.attempt_id)
    assignment = repositories.assignment_repository().get_assignment(assignment_id)
    assert response.attempt_id == "attempt_000001"
    assert response.already_submitted is False
    assert attempt is not None
    assert attempt.assignment_id == assignment_id
    assert attempt.code == 'fn main() { println!("Hello, Rust Sensei"); }'
    assert assignment is not None
    assert assignment.status == AssignmentStatus.ATTEMPTED


def test_get_next_lesson_returns_pending_assessment_after_attempt(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code="fn main() {}",
        )
    )
    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.assignment is None
    assert response.lesson_plan is None
    assert response.pending_assessment is True
    assert response.pending_attempt_id == submitted.attempt_id


def test_submit_attempt_is_idempotent_for_same_client_request(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    request = SubmitAttemptRequest(
        assignment_id=assignment_id,
        client_request_id="req-1",
        client_request_fingerprint="same",
        code="fn main() {}",
    )

    first = assessment_service.submit_attempt(request)
    second = assessment_service.submit_attempt(request)

    assert first.attempt_id == second.attempt_id
    assert first.already_submitted is False
    assert second.already_submitted is True


def test_submit_attempt_rejects_new_submission_for_attempted_assignment(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            client_request_id="req-1",
            client_request_fingerprint="first",
            code="fn main() {}",
        )
    )

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                client_request_id="req-2",
                client_request_fingerprint="second",
                code="fn main() {}",
            )
        )


def test_submit_attempt_rejects_idempotency_conflict(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            client_request_id="req-1",
            client_request_fingerprint="first",
            code="fn main() {}",
        )
    )

    with pytest.raises(IdempotencyConflictError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                client_request_id="req-1",
                client_request_fingerprint="second",
                code="fn main() {}",
            )
        )


def test_submit_attempt_requires_assessable_artifact(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(SubmitAttemptRequest(assignment_id=assignment_id))


def test_submit_attempt_accepts_complete_command_metadata_without_code(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    response = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            command_run_metadata=[
                CommandRunMetadataDTO(
                    command="cargo check",
                    source="agent",
                    exit_code=0,
                    started_at="2026-05-10T00:00:00Z",
                    output_summary="cargo check completed",
                )
            ],
        )
    )

    assert response.attempt_id == "attempt_000001"


def test_submit_attempt_rejects_missing_assignment(tmp_path):
    _, _, assessment_service, _ = _services(tmp_path)

    with pytest.raises(NotFoundError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id="missing",
                code="fn main() {}",
            )
        )


def test_submit_attempt_rejects_unsupported_learner_id(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                learner_id="other",
                assignment_id=assignment_id,
                code="fn main() {}",
            )
        )


def test_command_metadata_rejects_invalid_timestamp():
    with pytest.raises(PydanticValidationError):
        CommandRunMetadataDTO(
            command="cargo check",
            source="agent",
            exit_code=0,
            started_at="not-a-date",
            output_summary="cargo check completed",
        )


def _create_assignment(lesson_service):
    response = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert response.assignment is not None
    return response.assignment.assignment_id


def _services(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    now = lambda: datetime(2026, 5, 10, tzinfo=timezone.utc)
    session_service = SessionService(
        learner_repository=repositories.learner_repository(),
        now=now,
    )
    lesson_service = LessonService(
        learner_repository=repositories.learner_repository(),
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        now=now,
    )
    assessment_service = AssessmentService(
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        now=now,
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    return session_service, lesson_service, assessment_service, repositories
