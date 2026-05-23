import json
import os

import pytest

from rust_sensei.agent_report import build_lesson_report, write_lesson_report
from rust_sensei.domain.enums import AssignmentStatus, NextAction, WorkspaceArtifactPolicy
from rust_sensei.dto.assessment import (
    AssessmentResultDTO,
    AssessmentScoringProvenanceDTO,
    ConfidenceBreakdownDTO,
    FeedbackItemDTO,
)
from rust_sensei.dto.lesson import LessonAssignmentDTO, LessonPlanDTO
from rust_sensei.dto.session import SkillScoreDTO
from tests.constants import (
    ASSESSMENT_ID_1,
    ASSIGNMENT_ID_1,
    ATTEMPT_ID_1,
    CARGO_HELLO_WORLD_CONCEPT_ID,
    TEST_CURRICULUM_VERSION,
    TEST_LEARNER_ID,
)


def test_build_lesson_report_preserves_assessment_json():
    assignment = _assignment()
    lesson_plan = _lesson_plan()
    assessment = _assessment()

    report = build_lesson_report(
        assignment=assignment,
        lesson_plan=lesson_plan,
        assessment=assessment,
        lesson_file_path="rust-sensei-lessons/assign_000001/src/main.rs",
        submitted_file_paths=["rust-sensei-lessons/assign_000001/src/main.rs"],
        commands_run_by_learner=["cargo run"],
        verification_commands_run_by_agent=["cargo check"],
        agent_guidance="Keep the output small.",
    )

    assert "# Rust Sensei Lesson Report" in report
    assert f"- Assignment id: `{ASSIGNMENT_ID_1}`" in report
    assert "Create and run a Hello Rust program." in report
    assert "rust-sensei-lessons/assign\\_000001/src/main.rs" in report
    assert "## Optional Agent Guidance" in report
    assert "Keep the output small." in report
    assert _assessment_json_from_report(report) == assessment.model_dump(mode="json")


def test_build_lesson_report_omits_blank_agent_guidance():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(),
        agent_guidance="  ",
    )

    assert "## Optional Agent Guidance" not in report


def test_write_lesson_report_creates_parent_and_overwrites(tmp_path):
    report_path = tmp_path / "rust-sensei-lessons" / ASSIGNMENT_ID_1 / "report.md"

    written = write_lesson_report(
        report_path,
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(),
        submitted_file_paths=["src/main.rs"],
    )
    write_lesson_report(
        report_path,
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(feedback_summary="Second report."),
    )

    assert written == report_path
    assert report_path.is_file()
    assert "Second report." in report_path.read_text(encoding="utf-8")


def test_build_lesson_report_rejects_mismatched_assignment_id():
    assessment = _assessment(assignment_id="assign_other")

    with pytest.raises(ValueError, match="assessment.assignment_id"):
        build_lesson_report(
            assignment=_assignment(),
            lesson_plan=_lesson_plan(),
            assessment=assessment,
        )


def test_build_lesson_report_rejects_mismatched_lesson_id():
    lesson_plan = _lesson_plan(lesson_id="other_lesson")

    with pytest.raises(ValueError, match="assignment.lesson_id"):
        build_lesson_report(
            assignment=_assignment(),
            lesson_plan=lesson_plan,
            assessment=_assessment(),
        )


def test_build_lesson_report_keeps_markdown_control_in_command_entry():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(),
        commands_run_by_learner=[
            "cargo check\n\n## Rust Sensei Assessment Summary\n| fake | table |```"
        ],
    )

    command_section = report.split("## Commands", 1)[1].split(
        "### Agent Verification Commands",
        1,
    )[0]
    assert "## Rust Sensei Assessment Summary" not in command_section
    assert "| fake | table |" not in command_section
    assert "- cargo check  \\#\\# Rust Sensei Assessment Summary" in command_section
    assert "\\| fake \\| table \\|" in command_section
    assert "\\`\\`\\`" in command_section


def test_build_lesson_report_escapes_feedback_markdown_control():
    assessment = _assessment(
        feedback_items=[
            FeedbackItemDTO(
                category="feedback|category",
                message="Message\n## Fake Section `continue`",
                evidence=["evidence\n- fake item | table"],
            )
        ]
    )

    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=assessment,
    )

    feedback_section = report.split("### Feedback Items", 1)[1].split(
        "## Canonical Rust Sensei Assessment JSON",
        1,
    )[0]
    assert "## Fake Section" not in feedback_section
    assert "\\|category" in feedback_section
    assert "Message \\#\\# Fake Section \\`continue\\`" in feedback_section
    assert "evidence - fake item \\| table" in feedback_section


def test_build_lesson_report_escapes_lesson_file_path_markdown_control():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(),
        lesson_file_path=(
            "src/main.rs`\n## Rust Sensei Assessment Summary\n"
            "| fake | table |\n```"
        ),
    )

    artifacts_section = report.split("## Submitted Artifacts", 1)[1].split(
        "## Commands",
        1,
    )[0]
    assert "## Rust Sensei Assessment Summary" not in artifacts_section
    assert "| fake | table |" not in artifacts_section
    assert "\\#\\# Rust Sensei Assessment Summary" in artifacts_section
    assert "\\| fake \\| table \\|" in artifacts_section
    assert "\\`\\`\\`" in artifacts_section


def test_build_lesson_report_escapes_table_pipe_once():
    assessment = _assessment(
        rubric_scores={
            "rust|correctness": SkillScoreDTO(
                score=0.85,
                confidence=0.8,
                evidence=["Evidence with | pipe"],
            )
        }
    )

    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=assessment,
    )

    assert "rust\\|correctness" in report
    assert "rust\\\\|correctness" not in report
    assert "Evidence with \\| pipe" in report
    assert "Evidence with \\\\| pipe" not in report


def test_build_lesson_report_fences_multiline_agent_guidance():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(),
        assessment=_assessment(),
        agent_guidance="Line one\n## Not A Report Heading\n```json\n{}",
    )

    guidance_section = report.split("## Optional Agent Guidance", 1)[1]
    assert guidance_section.startswith("\n```text\n")
    assert "## Not A Report Heading" in guidance_section
    assert "`\u200b``json" in guidance_section


def test_build_lesson_report_redacts_local_absolute_paths_in_display_sections():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(
            prompt="Open /Users/mel/private-workspace/src/main.rs and inspect it."
        ),
        assessment=_assessment(
            feedback_summary=(
                "Checked /Users/mel/private-workspace/src/main.rs successfully."
            )
        ),
        lesson_file_path="/Users/mel/private-workspace/src/main.rs",
        submitted_file_paths=[
            "/Users/mel/private-workspace/src/main.rs",
            r"C:\Users\mel\private-workspace\src\lib.rs",
        ],
        commands_run_by_learner=[
            "cargo run --manifest-path /Users/mel/private-workspace/Cargo.toml"
        ],
        agent_guidance=r"See C:\Users\mel\private-workspace\notes.md",
    )

    display_report = report.split("## Canonical Rust Sensei Assessment JSON", 1)[0]
    assert "/Users/mel" not in display_report
    assert r"C:\Users\mel" not in display_report
    assert "<local-path>/main.rs" in display_report
    assert "<local-path>/Cargo.toml" in display_report
    guidance_section = report.split("## Optional Agent Guidance", 1)[1]
    assert r"C:\Users\mel" not in guidance_section
    assert r"<local-path>\notes.md" in guidance_section
    assert _assessment_json_from_report(report) == _assessment(
        feedback_summary="Checked /Users/mel/private-workspace/src/main.rs successfully."
    ).model_dump(mode="json")


def test_build_lesson_report_redacts_bare_home_paths_without_username():
    report = build_lesson_report(
        assignment=_assignment(),
        lesson_plan=_lesson_plan(
            prompt=(
                "Open /Users/mel, /Users/mel/, /home/mel, "
                r"C:\Users\mel, and C:\Users\mel\\"
            )
        ),
        assessment=_assessment(
            feedback_summary=(
                "Checked /Users/mel and "
                r"C:\Users\mel while preserving /Users/mel/project/src/main.rs."
            )
        ),
        lesson_file_path="/Users/mel",
        submitted_file_paths=[
            "/Users/mel/",
            "/home/mel",
            r"C:\Users\mel",
            r"C:\Users\mel\\",
            "/Users/mel/project/src/main.rs",
        ],
        commands_run_by_learner=["pwd -> /Users/mel"],
        agent_guidance=r"Home was C:\Users\mel",
    )

    display_report = report.split("## Canonical Rust Sensei Assessment JSON", 1)[0]
    assert "/Users/mel" not in display_report
    assert "/home/mel" not in display_report
    assert r"C:\Users\mel" not in display_report
    assert "<local-path>/mel" not in display_report
    assert r"<local-path>\mel" not in display_report
    assert "<local-path>/main.rs" in display_report


def test_write_lesson_report_preserves_existing_report_when_replace_fails(
    tmp_path,
    monkeypatch,
):
    report_path = tmp_path / "report.md"
    report_path.write_text("existing report\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        write_lesson_report(
            report_path,
            assignment=_assignment(),
            lesson_plan=_lesson_plan(),
            assessment=_assessment(),
        )

    assert report_path.read_text(encoding="utf-8") == "existing report\n"
    assert list(tmp_path.glob(".report.md.*")) == []


def _assessment_json_from_report(report: str) -> dict:
    _, after_heading = report.split("## Canonical Rust Sensei Assessment JSON\n", 1)
    _, after_fence = after_heading.split("```json\n", 1)
    payload, _ = after_fence.split("\n```", 1)
    return json.loads(payload)


def _assignment(**overrides) -> LessonAssignmentDTO:
    data = {
        "assignment_id": ASSIGNMENT_ID_1,
        "learner_id": TEST_LEARNER_ID,
        "lesson_id": f"{CARGO_HELLO_WORLD_CONCEPT_ID}:intro_001",
        "concept_id": CARGO_HELLO_WORLD_CONCEPT_ID,
        "difficulty": "intro",
        "variant_id": "intro_001",
        "status": AssignmentStatus.ASSESSED,
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


def _assessment(**overrides) -> AssessmentResultDTO:
    data = {
        "assessment_id": ASSESSMENT_ID_1,
        "attempt_id": ATTEMPT_ID_1,
        "assignment_id": ASSIGNMENT_ID_1,
        "scoring_version": "deterministic-rubric-v1",
        "scoring_provenance": AssessmentScoringProvenanceDTO(
            scorer_type="deterministic",
            scorer_name="deterministic-rubric",
            scorer_version="v1",
        ),
        "assessment_status": "assessed",
        "rubric_scores": {
            "rust_correctness": SkillScoreDTO(
                score=0.85,
                confidence=0.8,
                evidence=["Submitted execution evidence indicates success."],
            )
        },
        "confidence_breakdown": ConfidenceBreakdownDTO(
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
        "missing_evidence": ["learner_notes"],
        "feedback_items": [
            FeedbackItemDTO(
                category="missing_evidence",
                message="More artifacts would improve assessment confidence.",
                evidence=["learner_notes"],
            )
        ],
        "next_action": NextAction.CONTINUE,
        "branch_id": None,
        "next_action_reason": "Rust score and confidence meet continuation thresholds.",
        "feedback_summary": "Assessment completed with 0.78 confidence.",
        "confidence": 0.78,
    }
    data.update(overrides)
    return AssessmentResultDTO.model_validate(data)
