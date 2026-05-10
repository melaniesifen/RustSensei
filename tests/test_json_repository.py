import json

import pytest

from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.skill import SkillModel
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import StorageError
from rust_sensei.repositories.json_state import JsonStateStore
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.session_service import SessionService


def test_json_repository_creates_expected_state_shape(tmp_path):
    service = SessionService(
        learner_repository=JsonRepositoryFactory(tmp_path).learner_repository(),
        now=_fixed_now,
    )

    service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["schema_version"] == 1
    assert state["state_revision"] == 2
    assert state["active_learner_id"] == "local-default"
    assert "local-default" in state["learners"]
    assert state["lesson_assignments"] == []
    assert state["attempts"] == []
    assert state["assessments"] == []
    assert state["progress_events"] == []
    assert state["signals"] == []


def test_json_state_rejects_invalid_json(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text("{", encoding="utf-8")

    with pytest.raises(StorageError):
        JsonStateStore(state_path).read()


def test_json_state_rejects_unsupported_schema_version(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"schema_version": 999}),
        encoding="utf-8",
    )

    with pytest.raises(StorageError):
        JsonStateStore(state_path).read()


def test_create_profile_if_absent_keeps_original_profile(tmp_path):
    repository = JsonRepositoryFactory(tmp_path).learner_repository()
    first = _profile(RustLevel.NEW)
    second = _profile(RustLevel.EXPERT)

    created = repository.create_profile_if_absent(first)
    existing = repository.create_profile_if_absent(second)

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert created.rust_level_initial == RustLevel.NEW
    assert existing.rust_level_initial == RustLevel.NEW
    assert state["learners"]["local-default"]["rust_level_initial"] == "new"
    assert state["state_revision"] == 2


def test_assignment_repository_saves_and_returns_active_assignment(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repository = JsonRepositoryFactory(tmp_path).assignment_repository()
    assignment = LessonAssignment(
        assignment_id="assign_1",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ACTIVE,
        selection_rationale="test",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )

    repository.save_assignment(assignment)

    assert repository.get_assignment("assign_1") == assignment
    assert repository.get_active_assignment("local-default") == assignment
    assert repository.get_assignment("missing") is None


def test_create_active_assignment_if_absent_keeps_existing_active_assignment(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repository = JsonRepositoryFactory(tmp_path).assignment_repository()
    first = LessonAssignment(
        assignment_id="assign_1",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ACTIVE,
        selection_rationale="first",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    second = LessonAssignment(
        assignment_id="assign_2",
        learner_id="local-default",
        lesson_id="lesson_2",
        concept_id="variables_primitive_types",
        difficulty="guided",
        variant_id="guided_001",
        status=AssignmentStatus.ACTIVE,
        selection_rationale="second",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )

    created_assignment, first_created = repository.create_active_assignment_if_absent(
        first
    )
    existing_assignment, second_created = repository.create_active_assignment_if_absent(
        second
    )

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert first_created is True
    assert created_assignment.assignment_id == "assign_000001"
    assert created_assignment.learner_id == first.learner_id
    assert created_assignment.concept_id == first.concept_id
    assert existing_assignment.assignment_id == "assign_000001"
    assert existing_assignment.concept_id == first.concept_id
    assert second_created is False
    assert len(state["lesson_assignments"]) == 1
    assert state["state_revision"] == 2


def test_create_active_assignment_uses_new_id_after_prior_lifecycle_record(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repository = JsonRepositoryFactory(tmp_path).assignment_repository()
    assessed = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="cargo_hello_world:intro_001",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ASSESSED,
        selection_rationale="old",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    candidate = LessonAssignment(
        assignment_id="",
        learner_id="local-default",
        lesson_id="cargo_hello_world:intro_001",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ACTIVE,
        selection_rationale="new",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )

    repository.save_assignment(assessed)
    created, was_created = repository.create_active_assignment_if_absent(candidate)

    assert was_created is True
    assert created.assignment_id == "assign_000002"
    assert repository.get_assignment("assign_000001") == assessed
    assert repository.get_assignment("assign_000002") == created


def test_assignment_lifecycle_lookup_uses_latest_assignment_status(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repository = JsonRepositoryFactory(tmp_path).assignment_repository()
    active = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ACTIVE,
        selection_rationale="active",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    assessed = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ASSESSED,
        selection_rationale="assessed",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )

    repository.save_assignment(active)
    repository.save_assignment(assessed)

    assert repository.get_assignment("assign_000001") == assessed
    assert repository.get_active_assignment("local-default") is None


def test_curriculum_repository_rejects_invalid_curriculum(tmp_path):
    curriculum_path = tmp_path / "bad_curriculum.json"
    curriculum_path.write_text(
        json.dumps(
            {
                "curriculum_version": "test",
                "concepts": [
                    {
                        "concept_id": "duplicate",
                        "title": "One",
                        "order": 1,
                        "default_difficulty": "intro",
                        "learner_command": None,
                        "rubric_ids": ["rust_correctness"],
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Prompt",
                                "success_criteria": ["Compiles"],
                            }
                        ],
                    },
                    {
                        "concept_id": "duplicate",
                        "title": "Two",
                        "order": 2,
                        "default_difficulty": "intro",
                        "learner_command": None,
                        "rubric_ids": ["rust_correctness"],
                        "variants": [
                            {
                                "variant_id": "intro_001",
                                "difficulty": "intro",
                                "prompt": "Prompt",
                                "success_criteria": ["Compiles"],
                            }
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    repository = JsonRepositoryFactory(
        tmp_path,
        curriculum_path=curriculum_path,
    ).curriculum_repository()

    with pytest.raises(StorageError):
        repository.get_curriculum()


def _fixed_now():
    from datetime import datetime, timezone

    return datetime(2026, 5, 10, tzinfo=timezone.utc)


def _profile(level):
    return LearnerProfile(
        learner_id="local-default",
        rust_level_initial=level,
        active_concept_id=None,
        skill_model=SkillModel(),
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
