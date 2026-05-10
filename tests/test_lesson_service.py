from datetime import datetime, timezone

import pytest

from rust_sensei.domain.enums import AssignmentStatus, RustLevel
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.session_service import SessionService


def test_get_next_lesson_creates_first_assignment_from_placement(tmp_path):
    session_service, lesson_service = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.reused_active_assignment is False
    assert response.assignment is not None
    assert response.lesson_plan is not None
    assert response.assignment.assignment_id == "assign_000001"
    assert response.assignment.status == "active"
    assert response.assignment.concept_id == "cargo_hello_world"
    assert response.lesson_plan.learner_command == "cargo run"
    assert response.lesson_plan.rubric_ids == [
        "rust_correctness",
        "compiler_error_handling",
    ]


def test_get_next_lesson_reuses_active_assignment(tmp_path):
    session_service, lesson_service = _services(tmp_path)
    session_service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )

    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    second = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert first.assignment is not None
    assert second.assignment is not None
    assert second.reused_active_assignment is True
    assert second.assignment.assignment_id == first.assignment.assignment_id
    assert second.assignment.concept_id == "variables_primitive_types"


def test_get_next_lesson_requires_existing_profile(tmp_path):
    _, lesson_service = _services(tmp_path)

    with pytest.raises(NotFoundError):
        lesson_service.get_next_lesson(GetNextLessonRequest())


def test_get_next_lesson_rejects_unsupported_learner_id(tmp_path):
    _, lesson_service = _services(tmp_path)

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(GetNextLessonRequest(learner_id="other"))


def test_get_next_lesson_rejects_unimplemented_variant_controls(tmp_path):
    session_service, lesson_service = _services(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(GetNextLessonRequest(force_new_variant=True))

    with pytest.raises(ValidationError):
        lesson_service.get_next_lesson(
            GetNextLessonRequest(
                abandon_active_assignment=True,
                abandonment_reason="too easy",
            )
        )


def test_get_next_lesson_fails_when_assignment_variant_is_missing(tmp_path):
    session_service, lesson_service = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    repositories.assignment_repository().save_assignment(
        LessonAssignment(
            assignment_id="assign_bad_variant",
            learner_id="local-default",
            lesson_id="cargo_hello_world:missing_variant",
            concept_id="cargo_hello_world",
            difficulty="intro",
            variant_id="missing_variant",
            status=AssignmentStatus.ACTIVE,
            selection_rationale="test corrupted assignment",
            curriculum_version="0.1.0",
            created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
            updated_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        )
    )

    with pytest.raises(NotFoundError):
        lesson_service.get_next_lesson(GetNextLessonRequest())


def _services(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    now = lambda: datetime(2026, 5, 10, tzinfo=timezone.utc)
    return (
        SessionService(
            learner_repository=repositories.learner_repository(),
            now=now,
        ),
        LessonService(
            learner_repository=repositories.learner_repository(),
            assignment_repository=repositories.assignment_repository(),
            curriculum_repository=repositories.curriculum_repository(),
            now=now,
        ),
    )
