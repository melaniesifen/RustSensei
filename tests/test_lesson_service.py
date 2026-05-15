import pytest

from rust_sensei.domain.enums import AssignmentStatus, RustLevel
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEventType
from rust_sensei.dto.assessment import AssessAttemptRequest
from rust_sensei.dto.attempt import SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.assessment_service import AssessmentService
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.session_service import SessionService
from tests.constants import (
    ASSIGNMENT_ID_1,
    ASSIGNMENT_ID_2,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    HELLO_RUST_CODE,
    HELLO_RUST_OUTPUT,
    SUCCESSFUL_CARGO_OUTPUT,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
    TEST_NOW,
    VARIABLES_CONCEPT_ID,
)


def test_get_next_lesson_creates_first_assignment_from_placement(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    response = lesson_service.get_next_lesson(GetNextLessonRequest())
    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )

    assert response.reused_active_assignment is False
    assert response.assignment is not None
    assert response.lesson_plan is not None
    assert response.assignment.assignment_id == ASSIGNMENT_ID_1
    assert response.assignment.status == "active"
    assert response.assignment.concept_id == CARGO_HELLO_WORLD_CONCEPT_ID
    assert response.lesson_plan.learner_command == "cargo run"
    assert response.lesson_plan.rubric_ids == [
        "rust_correctness",
        "compiler_error_handling",
    ]
    assert events[0].event_type == ProgressEventType.ASSIGNMENT_CREATED
    assert events[0].assignment_id == ASSIGNMENT_ID_1


def test_get_next_lesson_reuses_active_assignment(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    session_service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )

    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    second = lesson_service.get_next_lesson(GetNextLessonRequest())
    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )

    assert first.assignment is not None
    assert second.assignment is not None
    assert second.reused_active_assignment is True
    assert second.assignment.assignment_id == first.assignment.assignment_id
    assert second.assignment.concept_id == VARIABLES_CONCEPT_ID
    assert events[0].event_type == ProgressEventType.ASSIGNMENT_VIEWED
    assert events[0].assignment_id == first.assignment.assignment_id


def test_get_next_lesson_requires_existing_profile(tmp_path):
    _, lesson_service, _ = _services(tmp_path)

    with pytest.raises(NotFoundError):
        lesson_service.get_next_lesson(GetNextLessonRequest())


def test_get_next_lesson_rejects_unsupported_learner_id(tmp_path):
    _, lesson_service, _ = _services(tmp_path)

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(GetNextLessonRequest(learner_id="other"))


def test_get_next_lesson_rejects_force_new_variant_for_active_assignment(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    lesson_service.get_next_lesson(GetNextLessonRequest())

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(GetNextLessonRequest(force_new_variant=True))


def test_get_next_lesson_rejects_force_new_variant_without_active_assignment(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(GetNextLessonRequest(force_new_variant=True))


def test_get_next_lesson_rejects_abandon_without_reason(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    lesson_service.get_next_lesson(GetNextLessonRequest())

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(
            GetNextLessonRequest(
                abandon_active_assignment=True,
            )
        )


def test_get_next_lesson_abandons_active_assignment_then_creates_new_one(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None

    response = lesson_service.get_next_lesson(
        GetNextLessonRequest(
            force_new_variant=True,
            abandon_active_assignment=True,
            abandonment_reason="too easy",
        )
    )

    abandoned = repositories.assignment_repository().get_assignment(
        first.assignment.assignment_id
    )
    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )
    assert abandoned is not None
    assert abandoned.status == AssignmentStatus.ABANDONED
    assert "Abandoned: too easy" in abandoned.selection_rationale
    assert response.assignment is not None
    assert response.assignment.assignment_id == ASSIGNMENT_ID_2
    assert response.assignment.status == AssignmentStatus.ACTIVE
    assert response.assignment.concept_id == CARGO_HELLO_WORLD_CONCEPT_ID
    assert response.reused_active_assignment is False
    assert [event.event_type for event in events[:2]] == [
        ProgressEventType.ASSIGNMENT_CREATED,
        ProgressEventType.ABANDONED,
    ]


def test_get_next_lesson_rejects_abandon_without_active_assignment(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(
            GetNextLessonRequest(
                abandon_active_assignment=True,
                abandonment_reason="nothing active",
            )
        )


def test_get_next_lesson_fails_when_assignment_variant_is_missing(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    repositories.assignment_repository().save_assignment(
        LessonAssignment(
            assignment_id="assign_bad_variant",
            learner_id=TEST_LEARNER_ID,
            lesson_id=f"{CARGO_HELLO_WORLD_CONCEPT_ID}:missing_variant",
            concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
            difficulty="intro",
            variant_id="missing_variant",
            status=AssignmentStatus.ACTIVE,
            selection_rationale="test corrupted assignment",
            curriculum_version=TEST_CURRICULUM_VERSION,
            created_at=TEST_NOW,
            updated_at=TEST_NOW,
        )
    )

    with pytest.raises(NotFoundError):
        lesson_service.get_next_lesson(GetNextLessonRequest())
    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    ) == []


def test_get_next_lesson_continues_after_assessed_assignment(tmp_path):
    session_service, lesson_service, assessment_service = _services(tmp_path)
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

    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.pending_assessment is False
    assert response.assignment is not None
    assert response.assignment.assignment_id == ASSIGNMENT_ID_2
    assert response.assignment.concept_id == VARIABLES_CONCEPT_ID
    assert response.assignment.selection_rationale.startswith(
        "Selected by accelerate action after assessment"
    )


def test_get_next_lesson_repeats_after_insufficient_evidence(tmp_path):
    session_service, lesson_service, assessment_service = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            runtime_output="failed",
            agent_notes="Agent says this passes.",
            output_truncated=True,
        )
    )
    assessment_service.assess_attempt(AssessAttemptRequest(attempt_id=submitted.attempt_id))

    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.assignment is not None
    assert response.assignment.assignment_id == ASSIGNMENT_ID_2
    assert response.assignment.concept_id == CARGO_HELLO_WORLD_CONCEPT_ID
    assert response.assignment.selection_rationale.startswith(
        "Selected by repeat action after assessment"
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
    )
