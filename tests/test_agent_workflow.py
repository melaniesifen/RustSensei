from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from rust_sensei.agent_workflow import (
    build_submit_attempt_request,
    open_with_vscode,
    prepare_agent_lesson,
    write_agent_lesson_report,
)
from rust_sensei.domain.enums import (
    AssignmentStatus,
    NextAction,
    RustLevel,
    WorkspaceArtifactPolicy,
)
from rust_sensei.dto.assessment import (
    AssessAttemptRequest,
    AssessmentResultDTO,
    AssessmentScoringProvenanceDTO,
    ConfidenceBreakdownDTO,
    FeedbackItemDTO,
)
from rust_sensei.dto.lesson import (
    AssignmentWorkspaceSuggestionDTO,
    GetNextLessonRequest,
    GetNextLessonResponse,
    LessonAssignmentDTO,
    LessonPlanDTO,
)
from rust_sensei.dto.session import SkillScoreDTO, StartSessionRequest
from rust_sensei.factory import ServiceFactory
from tests.constants import (
    ASSESSMENT_ID_1,
    ASSIGNMENT_ID_1,
    ATTEMPT_ID_1,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    HELLO_RUST_CODE,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
)


def test_prepare_agent_lesson_opens_generated_lesson_and_builds_attempt(tmp_path):
    response = _lesson_response()
    opened_paths = []

    prepared = prepare_agent_lesson(response, tmp_path, opener=opened_paths.append)
    assert prepared.workspace.lesson_file_path is not None
    prepared.workspace.lesson_file_path.write_text(
        'fn main() {\n    println!("Hello, Rust Sensei!");\n}\n',
        encoding="utf-8",
    )

    attempt = build_submit_attempt_request(
        prepared,
        commands_run_by_learner=["cargo run"],
        verification_commands_run_by_agent=["cargo check"],
        compiler_output="Finished dev profile",
    )

    assert opened_paths == [prepared.workspace.lesson_file_path]
    assert prepared.generated_file_paths == (
        "rust-sensei-lessons/assign_000001/src/main.rs",
    )
    assert attempt.assignment_id == ASSIGNMENT_ID_1
    assert attempt.workspace_root is None
    assert attempt.file_paths == ["rust-sensei-lessons/assign_000001/src/main.rs"]
    assert 'println!("Hello, Rust Sensei!")' in attempt.code
    assert attempt.commands_run_by_learner == ["cargo run"]
    assert attempt.verification_commands_run_by_agent == ["cargo check"]


def test_agent_workflow_prepares_submits_assesses_and_reports(tmp_path):
    services = ServiceFactory(state_dir=tmp_path / "state")
    services.session_service().start_session(
        StartSessionRequest(initial_rust_level=RustLevel.BEGINNER)
    )
    lesson = services.lesson_service().get_next_lesson(GetNextLessonRequest())
    prepared = prepare_agent_lesson(lesson, tmp_path / "workspace")
    assert prepared.workspace.lesson_file_path is not None
    prepared.workspace.lesson_file_path.write_text(HELLO_RUST_CODE, encoding="utf-8")

    attempt_request = build_submit_attempt_request(
        prepared,
        commands_run_by_learner=["cargo run"],
        verification_commands_run_by_agent=["cargo check"],
        compiler_output="Finished dev profile",
    )
    submitted = services.assessment_service().submit_attempt(attempt_request)
    assessed = services.assessment_service().assess_attempt(
        AssessAttemptRequest(attempt_id=submitted.attempt_id)
    )
    report_path = write_agent_lesson_report(
        prepared,
        assessed.assessment,
        attempt=attempt_request,
    )

    assert submitted.already_submitted is False
    assert attempt_request.file_paths == [
        "rust-sensei-lessons/assign_000001/src/main.rs"
    ]
    assert assessed.assessment.assignment_id == prepared.assignment.assignment_id
    assert report_path.is_file()
    assert submitted.attempt_id in report_path.read_text(encoding="utf-8")


def test_prepare_agent_lesson_for_manual_project_opens_directory_without_generated_files(
    tmp_path,
):
    response = _lesson_response(
        workspace_suggestion=AssignmentWorkspaceSuggestionDTO(
            assignment_id=ASSIGNMENT_ID_1,
            workspace_dir=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
            package_root=None,
            lesson_file_path=None,
            report_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/report.md",
            open_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
            create_cargo_package=False,
        ),
        lesson_plan=_lesson_plan(
            workspace_artifact_policy=WorkspaceArtifactPolicy.MANUAL_CARGO_PROJECT,
        ),
    )
    opened_paths = []

    prepared = prepare_agent_lesson(response, tmp_path, opener=opened_paths.append)
    attempt = build_submit_attempt_request(
        prepared,
        code="fn main() {}\n",
        include_workspace_root=False,
    )

    assert opened_paths == [prepared.workspace.workspace_dir]
    assert prepared.generated_file_paths == ()
    assert prepared.workspace.lesson_file_path is None
    assert not (prepared.workspace.workspace_dir / "Cargo.toml").exists()
    assert attempt.workspace_root is None
    assert attempt.file_paths == []
    assert attempt.code == "fn main() {}\n"


def test_build_submit_attempt_request_can_include_workspace_root_for_local_diagnostics(
    tmp_path,
):
    prepared = prepare_agent_lesson(_lesson_response(), tmp_path)

    attempt = build_submit_attempt_request(
        prepared,
        code="fn main() {}\n",
        include_workspace_root=True,
    )

    assert attempt.workspace_root == str(tmp_path.resolve(strict=False))


def test_prepare_agent_lesson_rejects_pending_assessment_response(tmp_path):
    response = GetNextLessonResponse(
        assignment=None,
        lesson_plan=None,
        reused_active_assignment=False,
        pending_assessment=True,
        pending_attempt_id=ATTEMPT_ID_1,
        workspace_suggestion=None,
    )

    with pytest.raises(ValueError, match="pending-assessment"):
        prepare_agent_lesson(response, tmp_path)


def test_write_agent_lesson_report_uses_attempt_evidence(tmp_path):
    prepared = prepare_agent_lesson(_lesson_response(), tmp_path)
    attempt = build_submit_attempt_request(
        prepared,
        commands_run_by_learner=["cargo run"],
        verification_commands_run_by_agent=["cargo check"],
        compiler_output="Finished dev profile",
    )

    report_path = write_agent_lesson_report(
        prepared,
        _assessment(),
        attempt=attempt,
        agent_guidance="Try another small println! variation next.",
    )

    report = report_path.read_text(encoding="utf-8")
    assert report_path == prepared.workspace.report_file_path
    assert "rust-sensei-lessons/assign\\_000001/src/main.rs" in report
    assert "cargo run" in report
    assert "cargo check" in report
    assert "Try another small println! variation next." in report


def test_open_with_vscode_invokes_code_command(monkeypatch, tmp_path):
    calls = []

    def fake_run(args, check):
        calls.append((args, check))

    monkeypatch.setattr(subprocess, "run", fake_run)

    open_with_vscode(tmp_path / "src" / "main.rs", command="code")

    assert calls == [(["code", str(tmp_path / "src" / "main.rs")], True)]


def test_build_submit_attempt_request_accepts_relative_extra_paths_from_workspace_root(
    monkeypatch,
    tmp_path,
):
    workspace_root = tmp_path / "workspace"
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.chdir(unrelated_cwd)
    prepared = prepare_agent_lesson(_lesson_response(), workspace_root)

    attempt = build_submit_attempt_request(
        prepared,
        code="fn main() {}\n",
        extra_file_paths=[
            Path("rust-sensei-lessons/assign_000001/src/lib.rs"),
        ],
    )

    assert attempt.file_paths == [
        "rust-sensei-lessons/assign_000001/src/main.rs",
        "rust-sensei-lessons/assign_000001/src/lib.rs",
    ]


def test_build_submit_attempt_request_rejects_extra_path_outside_workspace(tmp_path):
    prepared = prepare_agent_lesson(_lesson_response(), tmp_path)

    with pytest.raises(ValueError, match="inside the workspace root"):
        build_submit_attempt_request(
            prepared,
            code="fn main() {}\n",
            extra_file_paths=[tmp_path.parent / "outside.rs"],
        )


def _lesson_response(**overrides) -> GetNextLessonResponse:
    data = {
        "assignment": _assignment(),
        "lesson_plan": _lesson_plan(),
        "reused_active_assignment": False,
        "pending_assessment": False,
        "pending_attempt_id": None,
        "workspace_suggestion": _workspace_suggestion(),
    }
    data.update(overrides)
    return GetNextLessonResponse.model_validate(data)


def _workspace_suggestion() -> AssignmentWorkspaceSuggestionDTO:
    return AssignmentWorkspaceSuggestionDTO(
        assignment_id=ASSIGNMENT_ID_1,
        workspace_dir=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        package_root=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}",
        lesson_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/src/main.rs",
        report_file_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/report.md",
        open_path=f"rust-sensei-lessons/{ASSIGNMENT_ID_1}/src/main.rs",
        create_cargo_package=True,
    )


def _assignment(**overrides) -> LessonAssignmentDTO:
    data = {
        "assignment_id": ASSIGNMENT_ID_1,
        "learner_id": TEST_LEARNER_ID,
        "lesson_id": f"{CARGO_HELLO_WORLD_CONCEPT_ID}:intro_001",
        "concept_id": CARGO_HELLO_WORLD_CONCEPT_ID,
        "difficulty": "intro",
        "variant_id": "intro_001",
        "status": AssignmentStatus.ACTIVE,
        "selection_rationale": "Selected from placement.",
        "curriculum_version": TEST_CURRICULUM_VERSION,
    }
    data.update(overrides)
    return LessonAssignmentDTO.model_validate(data)


def _lesson_plan(**overrides) -> LessonPlanDTO:
    data = {
        "lesson_id": f"{CARGO_HELLO_WORLD_CONCEPT_ID}:intro_001",
        "concept_id": CARGO_HELLO_WORLD_CONCEPT_ID,
        "prompt": "Create and run a Hello Rust program.",
        "success_criteria": ["Program compiles", "Program prints the greeting"],
        "learner_command": "cargo run",
        "lesson_commands": [],
        "hints": ["Use println!"],
        "rubric_ids": ["rust_correctness"],
        "workspace_artifact_policy": WorkspaceArtifactPolicy.CARGO_BINARY_PACKAGE,
    }
    data.update(overrides)
    return LessonPlanDTO.model_validate(data)


def _assessment() -> AssessmentResultDTO:
    return AssessmentResultDTO(
        assessment_id=ASSESSMENT_ID_1,
        attempt_id=ATTEMPT_ID_1,
        assignment_id=ASSIGNMENT_ID_1,
        scoring_version="deterministic-rubric-v1",
        scoring_provenance=AssessmentScoringProvenanceDTO(
            scorer_type="deterministic",
            scorer_name="deterministic-rubric",
            scorer_version="v1",
        ),
        assessment_status="assessed",
        rubric_scores={
            "rust_correctness": SkillScoreDTO(
                score=0.85,
                confidence=0.8,
                evidence=["Submitted execution evidence indicates success."],
            )
        },
        confidence_breakdown=ConfidenceBreakdownDTO(
            critical_evidence_cap=None,
            evidence_completeness=0.8,
            evidence_quality=1.0,
            rubric_confidences={"rust_correctness": 0.8},
            prior_consistency=0.6,
            task_difficulty_weight=0.7,
            recency_weight=1.0,
            overall=0.78,
            explanation=["Submitted evidence supports the confidence score."],
        ),
        missing_evidence=["learner_notes"],
        feedback_items=[
            FeedbackItemDTO(
                category="missing_evidence",
                message="More artifacts would improve assessment confidence.",
                evidence=["learner_notes"],
            )
        ],
        next_action=NextAction.CONTINUE,
        branch_id=None,
        next_action_reason="Rust score and confidence meet continuation thresholds.",
        feedback_summary="Assessment completed with 0.78 confidence.",
        confidence=0.78,
    )
