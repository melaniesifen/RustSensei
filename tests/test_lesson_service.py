import pytest

from rust_sensei.domain.enums import AssignmentStatus, NextAction, RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEventType
from rust_sensei.domain.skill import SkillModel
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
    OWNERSHIP_CONCEPT_ID,
    SUCCESSFUL_CARGO_OUTPUT,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
    TEST_NOW,
    TRAITS_CONCEPT_ID,
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
    assert response.lesson_plan.workspace_artifact_policy == "manual_cargo_project"
    assert response.workspace_suggestion is not None
    assert response.workspace_suggestion.workspace_dir == "rust-sensei-lessons/assign_000001"
    assert response.workspace_suggestion.lesson_file_path is None
    assert response.workspace_suggestion.open_path == "rust-sensei-lessons/assign_000001"
    assert response.workspace_suggestion.create_cargo_package is False
    assert response.lesson_plan.rubric_ids == [
        "rust_correctness",
        "compiler_error_handling",
    ]
    assert events[0].event_type == ProgressEventType.ASSIGNMENT_CREATED
    assert events[0].assignment_id == ASSIGNMENT_ID_1


def test_list_curriculum_concepts_returns_ordered_inventory(tmp_path):
    _, lesson_service, _ = _services(tmp_path)

    response = lesson_service.list_curriculum_concepts()

    assert response.curriculum_version == TEST_CURRICULUM_VERSION
    assert [concept.concept_id for concept in response.concepts][:2] == [
        CARGO_HELLO_WORLD_CONCEPT_ID,
        VARIABLES_CONCEPT_ID,
    ]
    variables = response.concepts[1]
    assert variables.title == "Variables And Primitive Types"
    assert variables.default_difficulty == "guided"
    assert variables.prerequisites == [CARGO_HELLO_WORLD_CONCEPT_ID]
    assert variables.competency_goals == [
        "Declare immutable variables with primitive values",
        "Use println! to display values",
        "Recognize simple type inference",
    ]
    assert variables.baseline_task == (
        "Declare and print 3 immutable variables with different primitive types."
    )
    assert variables.stretch_signals == [
        "Uses meaningful variable names",
        "Adds more than 3 appropriate primitive values",
        "Keeps printed output readable",
    ]
    assert variables.struggle_signals == [
        "Cannot compile a basic let binding",
        "Confuses string literals with owned String values",
        "Does not run the learner command",
    ]
    assert variables.learner_command == "cargo run"
    assert variables.rubric_ids == [
        "rust_correctness",
        "rust_idioms",
        "readability",
        "compiler_error_handling",
    ]
    assert variables.variant_ids == ["guided_001"]
    assert variables.next_concepts == [OWNERSHIP_CONCEPT_ID]
    assert variables.branch_target_ids == [
        "compiler_feedback_remediation",
        "problem_solving_enrichment",
    ]
    assert variables.completion_thresholds == {
        "rust_correctness": 0.7,
        "rust_idioms": 0.6,
        "readability": 0.6,
    }


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
    assert second.workspace_suggestion is not None
    assert second.workspace_suggestion.assignment_id == first.assignment.assignment_id
    assert second.workspace_suggestion.lesson_file_path == (
        "rust-sensei-lessons/assign_000001/src/main.rs"
    )
    assert events[0].event_type == ProgressEventType.ASSIGNMENT_VIEWED
    assert events[0].assignment_id == first.assignment.assignment_id


def test_get_next_lesson_suggests_generated_cargo_package_for_normal_lesson(tmp_path):
    session_service, lesson_service, _ = _services(tmp_path)
    session_service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )

    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.lesson_plan is not None
    assert response.lesson_plan.workspace_artifact_policy == "cargo_binary_package"
    assert response.workspace_suggestion is not None
    assert response.workspace_suggestion.workspace_dir == "rust-sensei-lessons/assign_000001"
    assert response.workspace_suggestion.package_root == "rust-sensei-lessons/assign_000001"
    assert response.workspace_suggestion.lesson_file_path == (
        "rust-sensei-lessons/assign_000001/src/main.rs"
    )
    assert response.workspace_suggestion.report_file_path == (
        "rust-sensei-lessons/assign_000001/report.md"
    )
    assert response.workspace_suggestion.open_path == (
        "rust-sensei-lessons/assign_000001/src/main.rs"
    )
    assert response.workspace_suggestion.create_cargo_package is True


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
    assert response.assignment.variant_id == "intro_002"
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


def test_get_next_lesson_rejects_missing_profile_active_concept(tmp_path):
    _, lesson_service, _ = _services(tmp_path)
    repositories = JsonRepositoryFactory(tmp_path)
    repositories.learner_repository().save_profile(
        LearnerProfile(
            learner_id=TEST_LEARNER_ID,
            rust_level_initial=RustLevel.NEW,
            active_concept_id="missing_concept",
            skill_model=SkillModel(),
            created_at=TEST_NOW,
            updated_at=TEST_NOW,
        )
    )

    with pytest.raises(NotFoundError):
        lesson_service.get_next_lesson(GetNextLessonRequest())


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


def test_get_next_lesson_branches_for_problem_solving_gap(tmp_path):
    session_service, lesson_service, assessment_service = _services(tmp_path)
    session_service.start_session(
        StartSessionRequest(initial_rust_level=RustLevel.INTERMEDIATE)
    )
    first = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert first.assignment is not None
    assert first.assignment.concept_id == OWNERSHIP_CONCEPT_ID
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=first.assignment.assignment_id,
            code=(
                "fn describe(message: &String) -> usize { "
                "println!(\"{message}\"); message.len() "
                "} fn main() { "
                "let message = String::from(\"borrowed\"); "
                "let count = describe(&message); "
                "println!(\"{message} {count}\"); "
                "}"
            ),
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
            test_output="test result: ok. 1 passed; 0 failed",
            learner_notes=(
                "I guessed with trial and error and hardcoded parts; I do not "
                "understand why the borrowing approach works yet."
            ),
        )
    )

    assessment = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )
    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert assessment.assessment.next_action == NextAction.BRANCH
    assert assessment.assessment.branch_id == "problem_solving_enrichment"
    assert response.assignment is not None
    assert response.assignment.concept_id == TRAITS_CONCEPT_ID
    assert response.assignment.selection_rationale.startswith(
        "Selected branch target problem_solving_enrichment after assessment"
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
            truncation_reason="test fixture keeps output short",
        )
    )
    assessment_service.assess_attempt(AssessAttemptRequest(attempt_id=submitted.attempt_id))

    response = lesson_service.get_next_lesson(GetNextLessonRequest())

    assert response.assignment is not None
    assert response.assignment.assignment_id == ASSIGNMENT_ID_2
    assert response.assignment.concept_id == CARGO_HELLO_WORLD_CONCEPT_ID
    assert response.workspace_suggestion is not None
    assert response.workspace_suggestion.assignment_id == ASSIGNMENT_ID_2
    assert response.assignment.variant_id == "intro_002"
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
            curriculum_repository=repositories.curriculum_repository(),
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
