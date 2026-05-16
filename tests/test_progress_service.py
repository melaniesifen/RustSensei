from __future__ import annotations

import pytest

from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.dto.assessment import AssessAttemptRequest
from rust_sensei.dto.attempt import SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.progress import GetProgressSummaryRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.assessment_service import AssessmentService
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.progress_service import (
    FOCUS_ASSESS_PENDING_ATTEMPT,
    FOCUS_COMPLETE_ACTIVE_ASSIGNMENT,
    FOCUS_CONTINUE_ACTIVE_CONCEPT,
    FOCUS_RETRY_REPEATED_CONCEPT,
    TREND_ACCELERATING,
    TREND_NEEDS_PRACTICE,
    TREND_NO_ASSESSMENTS,
    ProgressService,
)
from rust_sensei.services.session_service import SessionService
from tests.constants import (
    ASSESSMENT_ID_1,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    HELLO_RUST_CODE,
    HELLO_RUST_OUTPUT,
    SUCCESSFUL_CARGO_OUTPUT,
    TEST_LEARNER_ID,
    TEST_NOW,
    VARIABLES_CONCEPT_ID,
)


def test_get_progress_summary_requires_existing_profile(tmp_path):
    progress_service = _progress_service(JsonRepositoryFactory(tmp_path))

    with pytest.raises(NotFoundError):
        progress_service.get_progress_summary(GetProgressSummaryRequest())


def test_get_progress_summary_rejects_unsupported_learner_id(tmp_path):
    progress_service = _progress_service(JsonRepositoryFactory(tmp_path))

    with pytest.raises(ValidationError):
        progress_service.get_progress_summary(
            GetProgressSummaryRequest(learner_id="other")
        )


def test_get_progress_summary_reports_active_assignment_focus(tmp_path):
    session_service, lesson_service, _, progress_service = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    lesson_service.get_next_lesson(GetNextLessonRequest())

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert response.active_concept_id == CARGO_HELLO_WORLD_CONCEPT_ID
    assert response.completed_concepts == []
    assert response.recommended_focus == FOCUS_COMPLETE_ACTIVE_ASSIGNMENT
    assert response.trend == TREND_NO_ASSESSMENTS
    assert response.recent_events[0].event_type == "assignment_created"


def test_get_active_progress_summary_uses_active_learner(tmp_path):
    session_service, lesson_service, _, progress_service = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    lesson_service.get_next_lesson(GetNextLessonRequest())

    response = progress_service.get_active_progress_summary()

    assert response.learner_id == TEST_LEARNER_ID
    assert response.active_concept_id == CARGO_HELLO_WORLD_CONCEPT_ID


def test_get_progress_summary_reports_pending_assessment_focus(tmp_path):
    session_service, lesson_service, assessment_service, progress_service = _services(
        tmp_path
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            code=HELLO_RUST_CODE,
        )
    )

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert response.recommended_focus == FOCUS_ASSESS_PENDING_ATTEMPT
    assert response.trend == TREND_NO_ASSESSMENTS


def test_get_progress_summary_reports_completed_concept_and_trend(tmp_path):
    session_service, lesson_service, assessment_service, progress_service = _services(
        tmp_path
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
            runtime_output=HELLO_RUST_OUTPUT,
            learner_notes="I created a Cargo binary and checked that it runs.",
        )
    )
    assessment_service.assess_attempt(AssessAttemptRequest(attempt_id=submitted.attempt_id))

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert response.completed_concepts == [CARGO_HELLO_WORLD_CONCEPT_ID]
    assert response.repeated_concepts == []
    assert response.recommended_focus == FOCUS_CONTINUE_ACTIVE_CONCEPT
    assert response.trend == TREND_ACCELERATING
    assert response.recent_events[0].assessment_id == ASSESSMENT_ID_1


def test_get_progress_summary_uses_active_assignment_concept_after_progression(tmp_path):
    session_service, lesson_service, assessment_service, progress_service = _services(
        tmp_path
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
            runtime_output=HELLO_RUST_OUTPUT,
            learner_notes="I created a Cargo binary and checked that it runs.",
        )
    )
    assessment_service.assess_attempt(AssessAttemptRequest(attempt_id=submitted.attempt_id))
    next_lesson = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert next_lesson.assignment is not None

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert next_lesson.assignment.concept_id == VARIABLES_CONCEPT_ID
    assert response.active_concept_id == VARIABLES_CONCEPT_ID


def test_get_progress_summary_reports_repeated_concept(tmp_path):
    session_service, lesson_service, assessment_service, progress_service = _services(
        tmp_path
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            runtime_output="failed",
            agent_notes="Agent says this passes.",
            output_truncated=True,
            truncation_reason="test fixture keeps output short",
        )
    )
    assessment_service.assess_attempt(AssessAttemptRequest(attempt_id=submitted.attempt_id))

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert response.repeated_concepts == [CARGO_HELLO_WORLD_CONCEPT_ID]
    assert response.recommended_focus == FOCUS_RETRY_REPEATED_CONCEPT
    assert response.trend == TREND_NEEDS_PRACTICE


def test_get_progress_summary_derives_skipped_concepts_from_all_events(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    session_service = SessionService(
        learner_repository=repositories.learner_repository(),
        learner_signal_repository=repositories.learner_signal_repository(),
        now=lambda: TEST_NOW,
    )
    progress_service = _progress_service(repositories)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    repositories.progress_event_repository().save_event(
        _progress_event(
            ProgressEventType.PROVISIONALLY_SKIPPED,
            concept_id=VARIABLES_CONCEPT_ID,
        )
    )
    for _ in range(10):
        repositories.progress_event_repository().save_event(
            _progress_event(
                ProgressEventType.ASSIGNMENT_VIEWED,
                concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
            )
        )

    response = progress_service.get_progress_summary(GetProgressSummaryRequest())

    assert response.skipped_concepts == [VARIABLES_CONCEPT_ID]
    assert len(response.recent_events) == 10
    assert all(
        event.event_type == ProgressEventType.ASSIGNMENT_VIEWED.value
        for event in response.recent_events
    )


def _services(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    now = lambda: TEST_NOW
    return (
        SessionService(
            learner_repository=repositories.learner_repository(),
            learner_signal_repository=repositories.learner_signal_repository(),
            now=now,
        ),
        LessonService(
            learner_repository=repositories.learner_repository(),
            assignment_repository=repositories.assignment_repository(),
            attempt_repository=repositories.attempt_repository(),
            assessment_repository=repositories.assessment_repository(),
            curriculum_repository=repositories.curriculum_repository(),
            progress_event_repository=repositories.progress_event_repository(),
            now=now,
        ),
        AssessmentService(
            assignment_repository=repositories.assignment_repository(),
            attempt_repository=repositories.attempt_repository(),
            assessment_repository=repositories.assessment_repository(),
            curriculum_repository=repositories.curriculum_repository(),
            learner_repository=repositories.learner_repository(),
            now=now,
        ),
        _progress_service(repositories),
    )


def _progress_service(repositories):
    return ProgressService(
        learner_repository=repositories.learner_repository(),
        assignment_repository=repositories.assignment_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        progress_event_repository=repositories.progress_event_repository(),
    )


def _progress_event(
    event_type: ProgressEventType,
    concept_id: str,
) -> ProgressEvent:
    return ProgressEvent(
        event_id="",
        learner_id=TEST_LEARNER_ID,
        event_type=event_type,
        assignment_id=None,
        attempt_id=None,
        assessment_id=None,
        details={"concept_id": concept_id},
        previous_status=None,
        new_status=None,
        created_at=TEST_NOW,
    )
