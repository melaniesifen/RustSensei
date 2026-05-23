from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError as PydanticValidationError

from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.attempt import AttemptSubmission, CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, Curriculum, LessonVariant
from rust_sensei.domain.enums import AssignmentStatus, NextAction, RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEventType
from rust_sensei.domain.skill import SkillModel
from rust_sensei.dto.assessment import AssessAttemptRequest
from rust_sensei.dto.attempt import CommandRunMetadataDTO, SubmitAttemptRequest
from rust_sensei.dto.lesson import GetNextLessonRequest
from rust_sensei.dto.session import StartSessionRequest
from rust_sensei.errors import IdempotencyConflictError, NotFoundError, ValidationError
from rust_sensei.repositories.json_repository import JsonRepositoryFactory
from rust_sensei.services.assessment_service import (
    MAX_CODE_CHARS,
    MAX_COMMAND_CHARS,
    MAX_COMMAND_METADATA_ITEMS,
    MAX_COMMAND_OUTPUT_SUMMARY_CHARS,
    MAX_COMMAND_PURPOSE_CHARS,
    MAX_FILE_PATHS,
    MAX_NOTES_CHARS,
    MAX_OUTPUT_CHARS,
    MAX_PATH_CHARS,
    AssessmentService,
)
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.session_service import SessionService
from tests.constants import (
    ASSESSMENT_ID_1,
    ASSIGNMENT_ID_1,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    HELLO_RUST_CODE,
    HELLO_RUST_OUTPUT,
    SUCCESSFUL_CARGO_OUTPUT,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
    TEST_NOW,
)


def test_submit_attempt_persists_attempt_and_marks_assignment_attempted(tmp_path):
    _, lesson_service, assessment_service, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    response = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output="Finished dev profile",
        )
    )

    attempt = repositories.attempt_repository().get_attempt(response.attempt_id)
    assignment = repositories.assignment_repository().get_assignment(assignment_id)
    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )
    assert response.attempt_id == "attempt_000001"
    assert response.already_submitted is False
    assert attempt is not None
    assert attempt.assignment_id == assignment_id
    assert attempt.code == HELLO_RUST_CODE
    assert assignment is not None
    assert assignment.status == AssignmentStatus.ATTEMPTED
    assert events[0].event_type == ProgressEventType.ATTEMPT_SUBMITTED
    assert events[0].attempt_id == response.attempt_id


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


@pytest.mark.parametrize(
    "field_name",
    ["code", "compiler_output", "runtime_output", "test_output"],
)
def test_submit_attempt_rejects_whitespace_only_text_artifacts(
    tmp_path,
    field_name,
):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                **{field_name: "   \n\t  "},
            )
        )


@pytest.mark.parametrize(
    ("field_name", "max_chars"),
    [
        ("code", MAX_CODE_CHARS),
        ("compiler_output", MAX_OUTPUT_CHARS),
        ("runtime_output", MAX_OUTPUT_CHARS),
        ("test_output", MAX_OUTPUT_CHARS),
        ("learner_notes", MAX_NOTES_CHARS),
        ("agent_notes", MAX_NOTES_CHARS),
    ],
)
def test_submit_attempt_rejects_oversized_text_artifacts(
    tmp_path,
    field_name,
    max_chars,
):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    payload = {
        "assignment_id": assignment_id,
        "code": HELLO_RUST_CODE,
        field_name: "x" * (max_chars + 1),
    }

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(SubmitAttemptRequest(**payload))


def test_submit_attempt_requires_truncation_reason_when_output_truncated(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                code=HELLO_RUST_CODE,
                output_truncated=True,
            )
        )


def test_submit_attempt_rejects_too_many_file_paths(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                code=HELLO_RUST_CODE,
                file_paths=[
                    f"src/example_{index}.rs"
                    for index in range(MAX_FILE_PATHS + 1)
                ],
            )
        )


def test_submit_attempt_rejects_too_many_command_metadata_items(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                command_run_metadata=[
                    _command_metadata()
                    for _ in range(MAX_COMMAND_METADATA_ITEMS + 1)
                ],
            )
        )


@pytest.mark.parametrize(
    ("field_name", "max_chars"),
    [
        ("command", MAX_COMMAND_CHARS),
        ("cwd", MAX_PATH_CHARS),
        ("output_summary", MAX_COMMAND_OUTPUT_SUMMARY_CHARS),
        ("purpose", MAX_COMMAND_PURPOSE_CHARS),
    ],
)
def test_submit_attempt_rejects_oversized_command_metadata_fields(
    tmp_path,
    field_name,
    max_chars,
):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    metadata = _command_metadata(**{field_name: "x" * (max_chars + 1)})

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                command_run_metadata=[metadata],
            )
        )


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "config/.env.local",
        ".ssh/id_ed25519",
        "certs/dev.key",
        "certs/client.pem",
    ],
)
def test_submit_attempt_rejects_secret_bearing_file_paths(tmp_path, path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)

    with pytest.raises(ValidationError):
        assessment_service.submit_attempt(
            SubmitAttemptRequest(
                assignment_id=assignment_id,
                code=HELLO_RUST_CODE,
                file_paths=[path],
            )
        )


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


def test_command_metadata_rejects_invalid_source():
    with pytest.raises(PydanticValidationError):
        CommandRunMetadataDTO(
            command="cargo check",
            source="unknown",
            exit_code=0,
            started_at="2026-05-10T00:00:00Z",
            output_summary="cargo check completed",
        )


def test_command_metadata_rejects_invalid_risk_level():
    with pytest.raises(PydanticValidationError):
        CommandRunMetadataDTO(
            command="cargo check",
            source="agent",
            exit_code=0,
            started_at="2026-05-10T00:00:00Z",
            output_summary="cargo check completed",
            risk_level="severe",
        )


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


def test_assess_attempt_persists_scores_confidence_and_marks_assessed(tmp_path):
    _, lesson_service, assessment_service, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
            runtime_output=HELLO_RUST_OUTPUT,
            learner_notes="I created a Cargo binary and checked that it runs.",
        )
    )

    response = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )

    assessment = response.assessment
    assignment = repositories.assignment_repository().get_assignment(assignment_id)
    stored = repositories.assessment_repository().get_assessment_by_attempt_id(
        submitted.attempt_id
    )
    profile = repositories.learner_repository().get_profile(TEST_LEARNER_ID)
    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )
    assert response.already_assessed is False
    assert assessment.assessment_id == ASSESSMENT_ID_1
    assert assessment.assessment_status == "assessed"
    assert assessment.scoring_provenance is not None
    assert assessment.scoring_provenance.scorer_type == "deterministic"
    assert assessment.scoring_provenance.scorer_name == "deterministic-rubric"
    assert assessment.confidence == assessment.confidence_breakdown.overall
    assert assessment.confidence_breakdown.explanation
    assert assessment.confidence >= 0.70
    assert set(assessment.rubric_scores) == {
        "rust_correctness",
        "compiler_error_handling",
    }
    assert assessment.rubric_scores["rust_correctness"].score == 0.85
    assert assessment.rubric_scores["rust_correctness"].confidence > 0
    assert assessment.next_action in {
        NextAction.CONTINUE,
        NextAction.REPEAT,
        NextAction.ACCELERATE,
    }
    assert assignment is not None
    assert assignment.status == AssignmentStatus.ASSESSED
    assert stored is not None
    assert stored.assessment_id == assessment.assessment_id
    assert stored.confidence_breakdown.explanation == (
        assessment.confidence_breakdown.explanation
    )
    assert profile is not None
    assert profile.skill_model.rust_concepts[CARGO_HELLO_WORLD_CONCEPT_ID].score == 0.80
    assert profile.skill_model.rust_concepts[CARGO_HELLO_WORLD_CONCEPT_ID].confidence == 0.50
    assert f"assessment_id={ASSESSMENT_ID_1}" in (
        profile.skill_model.rust_concepts[CARGO_HELLO_WORLD_CONCEPT_ID].evidence
    )
    assert profile.skill_model.programming_dimensions == {}
    assert events[0].event_type == _adaptive_event_type(assessment.next_action)
    assert events[0].assessment_id == ASSESSMENT_ID_1
    assert events[0].details["next_action"] == assessment.next_action.value
    assert events[0].details["next_action_reason"] == assessment.next_action_reason
    assert events[0].details["concept_id"] == CARGO_HELLO_WORLD_CONCEPT_ID
    assert events[1].event_type == ProgressEventType.ASSESSED
    assert events[1].assessment_id == ASSESSMENT_ID_1
    assert events[1].details["next_action"] == assessment.next_action.value


def test_assess_attempt_uses_injected_scorer_boundary(tmp_path):
    _, lesson_service, _, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    submitted = _assessment_service(repositories).submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
        )
    )
    scorer = _RecordingScorer()
    assessment_service = _assessment_service(repositories, scorer=scorer)

    response = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )

    assert scorer.calls == 1
    assert response.assessment.scoring_version == "test-scorer-v1"
    assert response.assessment.scoring_provenance is not None
    assert response.assessment.scoring_provenance.scorer_name == "test-scorer"


def test_assess_attempt_records_branch_progress_event_with_branch_id(tmp_path):
    _, lesson_service, _, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    submitted = _assessment_service(repositories).submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
        )
    )
    assessment_service = _assessment_service(
        repositories,
        scorer=_NextActionScorer(
            next_action=NextAction.BRANCH,
            branch_id="compiler_feedback_remediation",
        ),
    )

    response = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )

    events = repositories.progress_event_repository().list_recent_events(
        TEST_LEARNER_ID,
        limit=5,
    )
    assert response.assessment.next_action == NextAction.BRANCH
    assert response.assessment.branch_id == "compiler_feedback_remediation"
    assert events[0].event_type == ProgressEventType.BRANCHED
    assert events[0].details["next_action"] == NextAction.BRANCH.value
    assert events[0].details["branch_id"] == "compiler_feedback_remediation"
    assert events[0].details["next_action_reason"] == "test branch action"
    assert events[1].event_type == ProgressEventType.ASSESSED


def test_assess_attempt_rejects_scorer_without_provenance(tmp_path):
    _, lesson_service, _, repositories = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    submitted = _assessment_service(repositories).submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
        )
    )
    assessment_service = _assessment_service(
        repositories,
        scorer=_MissingProvenanceScorer(),
    )

    with pytest.raises(ValidationError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=submitted.attempt_id)
        )


def test_assess_attempt_is_idempotent_for_already_assessed_attempt(tmp_path):
    _, lesson_service, assessment_service, _ = _services(tmp_path)
    assignment_id = _create_assignment(lesson_service)
    submitted = assessment_service.submit_attempt(
        SubmitAttemptRequest(
            assignment_id=assignment_id,
            code=HELLO_RUST_CODE,
            compiler_output=SUCCESSFUL_CARGO_OUTPUT,
        )
    )

    first = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )
    state_revision_after_first = _state_revision(tmp_path)
    second = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )
    state_revision_after_second = _state_revision(tmp_path)

    assert first.already_assessed is False
    assert second.already_assessed is True
    assert second.assessment == first.assessment
    assert state_revision_after_second == state_revision_after_first


def test_assess_attempt_returns_insufficient_evidence_for_low_confidence_state(
    tmp_path,
):
    from rust_sensei.domain.attempt import AttemptSubmission
    from rust_sensei.domain.enums import AssignmentStatus
    from rust_sensei.domain.lesson import LessonAssignment

    repositories = JsonRepositoryFactory(tmp_path)
    _save_profile(repositories)
    assignment = LessonAssignment(
        assignment_id=ASSIGNMENT_ID_1,
        learner_id=TEST_LEARNER_ID,
        lesson_id=f"{CARGO_HELLO_WORLD_CONCEPT_ID}:intro_001",
        concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ATTEMPTED,
        selection_rationale="test",
        curriculum_version=TEST_CURRICULUM_VERSION,
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
    )
    attempt = AttemptSubmission(
        attempt_id="",
        learner_id=TEST_LEARNER_ID,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code=None,
        runtime_output="failed",
        agent_notes="Agent says this passes.",
        output_truncated=True,
        submitted_at=_fixed_now(),
    )
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        attempt,
        assignment,
    )
    assessment_service = AssessmentService(
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        learner_repository=repositories.learner_repository(),
        now=_fixed_now,
    )

    response = assessment_service.assess_attempt(
        AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
    )

    assert response.assessment.assessment_status == "insufficient_evidence"
    assert response.assessment.confidence < 0.45
    assert response.assessment.next_action == NextAction.REPEAT
    assert "code" in response.assessment.missing_evidence


def test_assess_attempt_rejects_missing_attempt(tmp_path):
    _, _, assessment_service, _ = _services(tmp_path)

    with pytest.raises(NotFoundError):
        assessment_service.assess_attempt(AssessAttemptRequest(attempt_id="missing"))


def test_assess_attempt_rejects_assignment_that_is_not_attempted(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    assignment = _manual_assignment(status=AssignmentStatus.ACTIVE)
    repositories.assignment_repository().save_assignment(assignment)
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        _manual_attempt(assignment),
        assignment,
    )
    assessment_service = _assessment_service(repositories)

    with pytest.raises(ValidationError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_missing_curriculum_concept(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    assignment = _manual_assignment(
        status=AssignmentStatus.ATTEMPTED,
        concept_id="missing_concept",
    )
    repositories.assignment_repository().save_assignment(assignment)
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        _manual_attempt(assignment),
        assignment,
    )
    assessment_service = _assessment_service(repositories)

    with pytest.raises(NotFoundError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_missing_learner_profile(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    assignment = _manual_assignment(status=AssignmentStatus.ATTEMPTED)
    repositories.assignment_repository().save_assignment(assignment)
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        _manual_attempt(assignment),
        assignment,
    )
    assessment_service = _assessment_service(repositories)

    with pytest.raises(NotFoundError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_unknown_rubric_ids(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    _save_profile(repositories)
    assignment = _manual_assignment(status=AssignmentStatus.ATTEMPTED)
    repositories.assignment_repository().save_assignment(assignment)
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        _manual_attempt(assignment),
        assignment,
    )
    assessment_service = _assessment_service(
        repositories,
        curriculum_repository=_StaticCurriculumRepository(
            Concept(
                concept_id=assignment.concept_id,
                title="Bad concept",
                order=1,
                default_difficulty="intro",
                learner_command=None,
                rubric_ids=["unknown_rubric"],
                variants=[
                    LessonVariant(
                        variant_id="intro_001",
                        difficulty="intro",
                        prompt="test",
                        success_criteria=["test"],
                    )
                ],
            )
        ),
    )

    with pytest.raises(ValidationError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_attempt_without_assessable_artifact(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    assignment = LessonAssignment(
        assignment_id=ASSIGNMENT_ID_1,
        learner_id=TEST_LEARNER_ID,
        lesson_id=f"{CARGO_HELLO_WORLD_CONCEPT_ID}:intro_001",
        concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
        difficulty="intro",
        variant_id="intro_001",
        status=AssignmentStatus.ATTEMPTED,
        selection_rationale="test",
        curriculum_version=TEST_CURRICULUM_VERSION,
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
    )
    attempt = AttemptSubmission(
        attempt_id="",
        learner_id=TEST_LEARNER_ID,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code=None,
        agent_notes="Looks okay to me.",
        submitted_at=_fixed_now(),
    )
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        attempt,
        assignment,
    )
    assessment_service = AssessmentService(
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        learner_repository=repositories.learner_repository(),
        now=_fixed_now,
    )

    with pytest.raises(ValidationError):
        assessment_service.assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_legacy_whitespace_only_artifact(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    _save_profile(repositories)
    assignment = _manual_assignment(status=AssignmentStatus.ATTEMPTED)
    repositories.assignment_repository().save_assignment(assignment)
    attempt = AttemptSubmission(
        attempt_id="",
        learner_id=TEST_LEARNER_ID,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code="   \n\t  ",
        compiler_output="  ",
        submitted_at=_fixed_now(),
    )
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        attempt,
        assignment,
    )

    with pytest.raises(ValidationError):
        _assessment_service(repositories).assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def test_assess_attempt_rejects_legacy_invalid_command_metadata_source(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    _save_profile(repositories)
    assignment = _manual_assignment(status=AssignmentStatus.ATTEMPTED)
    repositories.assignment_repository().save_assignment(assignment)
    attempt = AttemptSubmission(
        attempt_id="",
        learner_id=TEST_LEARNER_ID,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code=None,
        command_run_metadata=[
            CommandRunMetadata(
                command="cargo check",
                source="unknown",
                cwd=None,
                exit_code=0,
                started_at=TEST_NOW,
                output_summary="cargo check completed",
            )
        ],
        submitted_at=_fixed_now(),
    )
    saved_attempt, _ = repositories.attempt_repository().save_attempt_for_assignment(
        attempt,
        assignment,
    )

    with pytest.raises(ValidationError):
        _assessment_service(repositories).assess_attempt(
            AssessAttemptRequest(attempt_id=saved_attempt.attempt_id)
        )


def _create_assignment(lesson_service):
    response = lesson_service.get_next_lesson(GetNextLessonRequest())
    assert response.assignment is not None
    return response.assignment.assignment_id


def _command_metadata(**overrides) -> CommandRunMetadataDTO:
    values = {
        "command": "cargo check",
        "source": "agent",
        "exit_code": 0,
        "started_at": "2026-05-10T00:00:00Z",
        "output_summary": "cargo check completed",
    }
    values.update(overrides)
    return CommandRunMetadataDTO(**values)


def _services(tmp_path):
    repositories = JsonRepositoryFactory(tmp_path)
    now = lambda: TEST_NOW
    session_service = SessionService(
        learner_repository=repositories.learner_repository(),
        learner_signal_repository=repositories.learner_signal_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        now=now,
    )
    lesson_service = LessonService(
        learner_repository=repositories.learner_repository(),
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        progress_event_repository=repositories.progress_event_repository(),
        now=now,
    )
    assessment_service = AssessmentService(
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=repositories.curriculum_repository(),
        learner_repository=repositories.learner_repository(),
        now=now,
    )
    session_service.start_session(StartSessionRequest(initial_rust_level=RustLevel.NEW))
    return session_service, lesson_service, assessment_service, repositories


def _assessment_service(repositories, curriculum_repository=None, scorer=None):
    return AssessmentService(
        assignment_repository=repositories.assignment_repository(),
        attempt_repository=repositories.attempt_repository(),
        assessment_repository=repositories.assessment_repository(),
        curriculum_repository=(
            curriculum_repository
            if curriculum_repository is not None
            else repositories.curriculum_repository()
        ),
        learner_repository=repositories.learner_repository(),
        now=_fixed_now,
        scorer=scorer,
    )


def _manual_assignment(
    status: AssignmentStatus,
    concept_id: str = CARGO_HELLO_WORLD_CONCEPT_ID,
) -> LessonAssignment:
    return LessonAssignment(
        assignment_id=ASSIGNMENT_ID_1,
        learner_id=TEST_LEARNER_ID,
        lesson_id=f"{concept_id}:intro_001",
        concept_id=concept_id,
        difficulty="intro",
        variant_id="intro_001",
        status=status,
        selection_rationale="test",
        curriculum_version=TEST_CURRICULUM_VERSION,
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
    )


def _manual_attempt(assignment: LessonAssignment) -> AttemptSubmission:
    return AttemptSubmission(
        attempt_id="",
        learner_id=assignment.learner_id,
        assignment_id=assignment.assignment_id,
        lesson_id=assignment.lesson_id,
        client_request_id=None,
        client_request_fingerprint=None,
        workspace_root=None,
        code=HELLO_RUST_CODE,
        compiler_output=SUCCESSFUL_CARGO_OUTPUT,
        submitted_at=_fixed_now(),
    )


def _save_profile(repositories) -> None:
    repositories.learner_repository().save_profile(
        LearnerProfile(
            learner_id=TEST_LEARNER_ID,
            rust_level_initial=RustLevel.NEW,
            active_concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
            skill_model=SkillModel(),
            created_at=TEST_NOW,
            updated_at=TEST_NOW,
        )
    )


class _StaticCurriculumRepository:
    def __init__(self, concept: Concept) -> None:
        self._concept = concept

    def get_curriculum(self) -> Curriculum:
        return Curriculum(
            curriculum_version="test",
            concepts={self._concept.concept_id: self._concept},
        )

    def get_concept(self, concept_id: str) -> Concept | None:
        if concept_id == self._concept.concept_id:
            return self._concept
        return None


def _fixed_now():
    return TEST_NOW


def _state_revision(tmp_path):
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    return state["state_revision"]


def _adaptive_event_type(next_action: NextAction) -> ProgressEventType:
    return {
        NextAction.CONTINUE: ProgressEventType.COMPLETED,
        NextAction.REPEAT: ProgressEventType.REPEATED,
        NextAction.SIMPLIFY: ProgressEventType.SIMPLIFIED,
        NextAction.ACCELERATE: ProgressEventType.ACCELERATED,
        NextAction.BRANCH: ProgressEventType.BRANCHED,
    }[next_action]


class _RecordingScorer:
    def __init__(self) -> None:
        self.calls = 0

    def score_attempt(self, attempt, concept, difficulty, now) -> AssessmentResult:
        from rust_sensei.domain.scoring import build_assessment

        self.calls += 1
        assessment = build_assessment(
            attempt=attempt,
            concept=concept,
            difficulty=difficulty,
            now=now,
        )
        assert assessment.scoring_provenance is not None
        return replace(
            assessment,
            scoring_version="test-scorer-v1",
            scoring_provenance=replace(
                assessment.scoring_provenance,
                scorer_name="test-scorer",
                scorer_version="v1",
            ),
        )


class _MissingProvenanceScorer:
    def score_attempt(self, attempt, concept, difficulty, now) -> AssessmentResult:
        from rust_sensei.domain.scoring import build_assessment

        return replace(
            build_assessment(
                attempt=attempt,
                concept=concept,
                difficulty=difficulty,
                now=now,
            ),
            scoring_provenance=None,
        )


class _NextActionScorer:
    def __init__(self, next_action: NextAction, branch_id: str | None = None) -> None:
        self._next_action = next_action
        self._branch_id = branch_id

    def score_attempt(self, attempt, concept, difficulty, now) -> AssessmentResult:
        from rust_sensei.domain.scoring import build_assessment

        return replace(
            build_assessment(
                attempt=attempt,
                concept=concept,
                difficulty=difficulty,
                now=now,
            ),
            next_action=self._next_action,
            branch_id=self._branch_id,
            next_action_reason="test branch action",
        )
