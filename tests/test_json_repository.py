from __future__ import annotations

import json
from dataclasses import replace

import pytest

from rust_sensei.domain.assessment import AssessmentResult, ConfidenceBreakdown
from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.domain.enums import AssignmentStatus, Difficulty, NextAction, RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import IdempotencyConflictError, StorageError
from rust_sensei.repositories.json_state import JsonStateStore
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.session_service import SessionService
from tests.constants import (
    ASSIGNMENT_ID_1,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
    TEST_NOW,
)


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


def test_json_state_defaults_missing_current_collections_for_schema_one(tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "state_revision": 1,
                "active_learner_id": TEST_LEARNER_ID,
                "learners": {},
                "lesson_assignments": [],
                "attempts": [],
                "assessments": [],
            }
        ),
        encoding="utf-8",
    )
    repositories = JsonRepositoryFactory(tmp_path)

    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    ) == []
    saved = repositories.progress_event_repository().save_event(
        _progress_event(
            event_type=ProgressEventType.ASSIGNMENT_VIEWED,
            assignment_id=ASSIGNMENT_ID_1,
        )
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved.event_id == "event_000001"
    assert state["progress_events"][0]["event_id"] == "event_000001"
    assert state["signals"] == []


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


def test_attempt_repository_saves_attempt_and_assignment_status_atomically(tmp_path):
    from rust_sensei.domain.attempt import AttemptSubmission
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repositories = JsonRepositoryFactory(tmp_path)
    assignment = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ATTEMPTED,
        selection_rationale="test",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    attempt = AttemptSubmission(
        attempt_id="",
        learner_id="local-default",
        assignment_id="assign_000001",
        lesson_id="lesson_1",
        client_request_id="req-1",
        client_request_fingerprint="fingerprint",
        workspace_root=None,
        code="fn main() {}",
        submitted_at=_fixed_now(),
    )

    saved, created = repositories.attempt_repository().save_attempt_for_assignment(
        attempt,
        assignment,
    )

    assert created is True
    assert saved.attempt_id == "attempt_000001"
    assert repositories.attempt_repository().get_attempt(saved.attempt_id) == saved
    assert repositories.attempt_repository().get_attempt_by_client_request_id(
        "local-default",
        "req-1",
    ) == saved
    assert repositories.assignment_repository().get_assignment(
        "assign_000001"
    ) == assignment


def test_attempt_repository_enforces_idempotency_inside_transaction(tmp_path):
    from rust_sensei.domain.attempt import AttemptSubmission
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repositories = JsonRepositoryFactory(tmp_path)
    assignment = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ATTEMPTED,
        selection_rationale="test",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    first = AttemptSubmission(
        attempt_id="",
        learner_id="local-default",
        assignment_id="assign_000001",
        lesson_id="lesson_1",
        client_request_id="req-1",
        client_request_fingerprint="same",
        workspace_root=None,
        code="fn main() {}",
        submitted_at=_fixed_now(),
    )
    second = AttemptSubmission(
        attempt_id="",
        learner_id="local-default",
        assignment_id="assign_000001",
        lesson_id="lesson_1",
        client_request_id="req-1",
        client_request_fingerprint="same",
        workspace_root=None,
        code="fn main() {}",
        submitted_at=_fixed_now(),
    )

    saved, created = repositories.attempt_repository().save_attempt_for_assignment(
        first,
        assignment,
    )
    existing, duplicated = repositories.attempt_repository().save_attempt_for_assignment(
        second,
        assignment,
    )

    assert created is True
    assert duplicated is False
    assert existing == saved


def test_attempt_repository_rejects_idempotency_conflict_inside_transaction(tmp_path):
    from rust_sensei.domain.attempt import AttemptSubmission
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repositories = JsonRepositoryFactory(tmp_path)
    assignment = LessonAssignment(
        assignment_id="assign_000001",
        learner_id="local-default",
        lesson_id="lesson_1",
        concept_id="cargo_hello_world",
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ATTEMPTED,
        selection_rationale="test",
        curriculum_version="0.1.0",
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )
    first = AttemptSubmission(
        attempt_id="",
        learner_id="local-default",
        assignment_id="assign_000001",
        lesson_id="lesson_1",
        client_request_id="req-1",
        client_request_fingerprint="first",
        workspace_root=None,
        code="fn main() {}",
        submitted_at=_fixed_now(),
    )
    conflicting = AttemptSubmission(
        attempt_id="",
        learner_id="local-default",
        assignment_id="assign_000001",
        lesson_id="lesson_1",
        client_request_id="req-1",
        client_request_fingerprint="second",
        workspace_root=None,
        code="fn main() {}",
        submitted_at=_fixed_now(),
    )

    repositories.attempt_repository().save_attempt_for_assignment(first, assignment)

    with pytest.raises(IdempotencyConflictError):
        repositories.attempt_repository().save_attempt_for_assignment(
            conflicting,
            assignment,
        )


def test_assessment_repository_saves_assessment_with_existing_wrapper(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus

    repositories = JsonRepositoryFactory(tmp_path)
    assignment = _assignment(AssignmentStatus.ASSESSED)
    assessment = _assessment("attempt_1", assignment.assignment_id)

    saved, created = repositories.assessment_repository().save_assessment_for_assignment(
        assessment,
        assignment,
    )

    assert created is True
    assert saved.assessment_id == "assessment_000001"
    assert repositories.assessment_repository().get_assessment_by_attempt_id(
        "attempt_1"
    ) == saved
    assert repositories.assignment_repository().get_assignment(
        assignment.assignment_id
    ) == assignment


def test_assessment_repository_profile_updater_uses_current_profile_inside_transaction(
    tmp_path,
):
    from rust_sensei.domain.enums import AssignmentStatus

    repositories = JsonRepositoryFactory(tmp_path)
    current_profile = _profile(RustLevel.NEW)
    repositories.learner_repository().save_profile(
        replace(
            current_profile,
            skill_model=SkillModel(
                rust_concepts={
                    "existing": SkillScore(0.65, 0.70, ["existing evidence"]),
                }
            ),
        )
    )
    assignment = _assignment(AssignmentStatus.ASSESSED)
    assessment = _assessment("attempt_1", assignment.assignment_id)

    def update_profile(saved_assessment, profile):
        assert saved_assessment.assessment_id == "assessment_000001"
        assert "existing" in profile.skill_model.rust_concepts
        return replace(profile, active_concept_id="updated")

    saved, created = (
        repositories.assessment_repository().save_assessment_for_assignment_and_profile(
            assessment,
            assignment,
            update_profile,
        )
    )
    saved_profile = repositories.learner_repository().get_profile("local-default")

    assert created is True
    assert saved.assessment_id == "assessment_000001"
    assert saved_profile is not None
    assert saved_profile.active_concept_id == "updated"
    assert "existing" in saved_profile.skill_model.rust_concepts


def test_repositories_return_latest_assessed_assignment_and_assessment(tmp_path):
    from rust_sensei.domain.enums import AssignmentStatus

    repositories = JsonRepositoryFactory(tmp_path)
    first_assignment = _assignment(AssignmentStatus.ASSESSED)
    second_assignment = replace(
        _assignment(AssignmentStatus.ASSESSED),
        assignment_id="assign_000002",
        lesson_id="lesson_2",
        concept_id="variables_primitive_types",
    )
    first_assessment = _assessment("attempt_1", first_assignment.assignment_id)
    second_assessment = _assessment("attempt_2", second_assignment.assignment_id)

    repositories.assessment_repository().save_assessment_for_assignment(
        first_assessment,
        first_assignment,
    )
    saved_second, _ = repositories.assessment_repository().save_assessment_for_assignment(
        second_assessment,
        second_assignment,
    )

    assert repositories.assignment_repository().get_latest_assessed_assignment(
        TEST_LEARNER_ID
    ) == second_assignment
    assert repositories.assessment_repository().get_latest_assessment_for_assignment(
        second_assignment.assignment_id
    ) == saved_second
    assert repositories.assessment_repository().get_latest_assessment_for_assignment(
        "missing"
    ) is None


def test_progress_event_repository_saves_and_lists_recent_events(tmp_path):
    repository = JsonRepositoryFactory(tmp_path).progress_event_repository()
    first = repository.save_event(
        _progress_event(
            event_type=ProgressEventType.ASSIGNMENT_CREATED,
            assignment_id=ASSIGNMENT_ID_1,
        )
    )
    second = repository.save_event(
        _progress_event(
            event_type=ProgressEventType.ASSIGNMENT_VIEWED,
            assignment_id=ASSIGNMENT_ID_1,
        )
    )

    events = repository.list_recent_events(TEST_LEARNER_ID, limit=1)

    assert first.event_id == "event_000001"
    assert second.event_id == "event_000002"
    assert events == [second]


def test_assignment_create_rolls_back_when_progress_event_creation_fails(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)

    with pytest.raises(RuntimeError):
        repositories.assignment_repository().create_active_assignment_if_absent(
            _assignment(AssignmentStatus.ACTIVE),
            event_factory=_raise_progress_event_error,
        )

    assert (
        repositories.assignment_repository().get_active_assignment(TEST_LEARNER_ID)
        is None
    )
    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=10,
    ) == []


def test_assignment_update_rolls_back_when_progress_event_creation_fails(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    active = _assignment(AssignmentStatus.ACTIVE)
    abandoned = replace(active, status=AssignmentStatus.ABANDONED)
    repositories.assignment_repository().save_assignment(active)

    with pytest.raises(RuntimeError):
        repositories.assignment_repository().update_assignment(
            abandoned,
            event_factory=_raise_progress_event_error,
        )

    saved = repositories.assignment_repository().get_assignment(active.assignment_id)
    assert saved is not None
    assert saved.status == AssignmentStatus.ACTIVE
    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=10,
    ) == []


def test_attempt_save_rolls_back_when_progress_event_creation_fails(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    active = _assignment(AssignmentStatus.ACTIVE)
    attempted = replace(active, status=AssignmentStatus.ATTEMPTED)
    repositories.assignment_repository().save_assignment(active)

    with pytest.raises(RuntimeError):
        repositories.attempt_repository().save_attempt_for_assignment(
            _attempt(active),
            attempted,
            event_factory=_raise_progress_event_error,
        )

    assert repositories.attempt_repository().get_attempt("attempt_000001") is None
    saved = repositories.assignment_repository().get_assignment(active.assignment_id)
    assert saved is not None
    assert saved.status == AssignmentStatus.ACTIVE
    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=10,
    ) == []


def test_assessment_save_rolls_back_when_progress_event_creation_fails(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    attempted = _assignment(AssignmentStatus.ATTEMPTED)
    assessed = replace(attempted, status=AssignmentStatus.ASSESSED)
    repositories.assignment_repository().save_assignment(attempted)

    with pytest.raises(RuntimeError):
        repositories.assessment_repository().save_assessment_for_assignment(
            _assessment("attempt_1", attempted.assignment_id),
            assessed,
            event_factory=_raise_progress_event_error,
        )

    assert (
        repositories.assessment_repository().get_assessment_by_attempt_id("attempt_1")
        is None
    )
    saved = repositories.assignment_repository().get_assignment(attempted.assignment_id)
    assert saved is not None
    assert saved.status == AssignmentStatus.ATTEMPTED
    assert repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=10,
    ) == []


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
    return TEST_NOW


def _profile(level):
    return LearnerProfile(
        learner_id=TEST_LEARNER_ID,
        rust_level_initial=level,
        active_concept_id=None,
        skill_model=SkillModel(),
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )


def _assignment(status):
    from rust_sensei.domain.lesson import LessonAssignment

    return LessonAssignment(
        assignment_id=ASSIGNMENT_ID_1,
        learner_id=TEST_LEARNER_ID,
        lesson_id="lesson_1",
        concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
        difficulty=Difficulty.INTRO,
        variant_id="intro_001",
        status=status,
        selection_rationale="test",
        curriculum_version=TEST_CURRICULUM_VERSION,
        created_at=_fixed_now(),
        updated_at=_fixed_now(),
    )


def _assessment(attempt_id, assignment_id):
    return AssessmentResult(
        assessment_id="",
        attempt_id=attempt_id,
        assignment_id=assignment_id,
        scoring_version="test",
        assessment_status="assessed",
        rubric_scores={
            "rust_correctness": SkillScore(0.80, 0.75, ["compiled"]),
        },
        confidence_breakdown=ConfidenceBreakdown(
            critical_evidence_cap=None,
            evidence_completeness=1.0,
            evidence_quality=1.0,
            rubric_confidences={"rust_correctness": 0.75},
            prior_consistency=0.60,
            task_difficulty_weight=0.70,
            recency_weight=1.0,
            overall=0.75,
        ),
        missing_evidence=[],
        feedback_items=[],
        next_action=NextAction.CONTINUE,
        branch_id=None,
        next_action_reason="test",
        feedback_summary="test",
        confidence=0.75,
        created_at=_fixed_now(),
    )


def _attempt(assignment):
    return AttemptSubmission(
        attempt_id="",
        learner_id=TEST_LEARNER_ID,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code='fn main() { println!("Hello"); }',
        compiler_output=None,
        runtime_output="Hello",
        test_output=None,
        agent_notes=None,
        output_truncated=False,
        submitted_at=TEST_NOW,
    )


def _progress_event(
    event_type: ProgressEventType,
    assignment_id: str | None,
) -> ProgressEvent:
    return ProgressEvent(
        event_id="",
        learner_id=TEST_LEARNER_ID,
        event_type=event_type,
        assignment_id=assignment_id,
        attempt_id=None,
        assessment_id=None,
        details={"source": "test"},
        previous_status=None,
        new_status=AssignmentStatus.ACTIVE.value,
        created_at=TEST_NOW,
    )


def _raise_progress_event_error(_):
    raise RuntimeError("progress event write failed")
