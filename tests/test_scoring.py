from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rust_sensei.domain.attempt import AttemptSubmission, CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, LessonVariant
from rust_sensei.domain.enums import Difficulty, NextAction
from rust_sensei.domain.scoring import build_assessment, validate_rubric_ids
from rust_sensei.errors import ValidationError


def test_build_assessment_scores_general_programming_rubrics():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code=(
                "fn parse_numbers(input: &str) -> Vec<i32> { "
                "input.split(',').map(|item| item.parse().unwrap()).collect() "
                "} fn main() {}"
            ),
            test_output="test result: ok. 3 passed; 0 failed",
            learner_notes="I split the input, parsed each item, and collected values.",
            submitted_at=_fixed_now(),
        ),
        concept=_concept(
            [
                "rust_idioms",
                "readability",
                "maintainability",
                "problem_solving",
                "dsa",
            ]
        ),
        difficulty=Difficulty.CHALLENGE,
        now=_fixed_now(),
    )

    assert assessment.assessment_status == "assessed"
    assert assessment.scoring_provenance is not None
    assert assessment.scoring_provenance.scorer_type == "deterministic"
    assert assessment.scoring_provenance.scorer_name == "deterministic-rubric"
    assert assessment.scoring_provenance.scorer_version == "v1"
    assert assessment.rubric_scores["rust_idioms"].score == 0.67
    assert assessment.rubric_scores["maintainability"].score == 0.82
    assert assessment.rubric_scores["dsa"].score == 0.90
    assert assessment.next_action == NextAction.REPEAT


def test_build_assessment_scores_compiler_failure_with_notes():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code="fn main() { println!(\"hi\") }",
            compiler_output="error: expected semicolon",
            learner_notes="I think I missed Rust statement syntax.",
            submitted_at=_fixed_now(),
        ),
        concept=_concept(["rust_correctness", "compiler_error_handling"]),
        difficulty=Difficulty.INTRO,
        now=_fixed_now(),
    )

    assert assessment.rubric_scores["rust_correctness"].score == 0.35
    assert assessment.rubric_scores["compiler_error_handling"].score == 0.45
    assert assessment.next_action == NextAction.SIMPLIFY


def test_build_assessment_branches_for_repeated_compiler_failures():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code="fn main() { println!(\"missing semicolon\") }",
            compiler_output="error: expected `;`",
            command_run_metadata=[
                _command_metadata(exit_code=101, output_summary="cargo check failed"),
                _command_metadata(
                    exit_code=101,
                    output_summary="cargo check failed again",
                ),
            ],
            learner_notes=(
                "I ran cargo check again after editing and still see the same "
                "semicolon compiler error."
            ),
            submitted_at=_fixed_now(),
        ),
        concept=_concept(["rust_correctness", "compiler_error_handling"]),
        difficulty=Difficulty.GUIDED,
        now=_fixed_now(),
    )

    assert assessment.confidence >= 0.80
    assert assessment.next_action == NextAction.BRANCH
    assert assessment.branch_id == "compiler_feedback_remediation"
    assert assessment.next_action_reason == (
        "Repeated compiler-error struggles have high-confidence evidence for "
        "targeted remediation."
    )


def test_build_assessment_branches_for_problem_solving_gap():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code=(
                "fn explain(message: &String) -> usize { "
                "println!(\"{message}\"); message.len() "
                "} fn main() { "
                "let message = String::from(\"hello\"); "
                "let count = explain(&message); "
                "println!(\"{message} {count}\"); "
                "}"
            ),
            compiler_output="Finished dev profile target(s) in 0.10s",
            test_output="test result: ok. 1 passed; 0 failed",
            command_run_metadata=[
                _command_metadata(exit_code=0, output_summary="cargo test passed")
            ],
            learner_notes=(
                "I guessed with trial and error and hardcoded parts; I do not "
                "understand why this approach works yet."
            ),
            submitted_at=_fixed_now(),
        ),
        concept=_concept(
            [
                "rust_correctness",
                "rust_idioms",
                "problem_solving",
                "compiler_error_handling",
            ]
        ),
        difficulty=Difficulty.STANDARD,
        now=_fixed_now(),
    )

    assert assessment.confidence >= 0.80
    assert assessment.rubric_scores["problem_solving"].score == 0.50
    assert assessment.next_action == NextAction.BRANCH
    assert assessment.branch_id == "problem_solving_enrichment"
    assert assessment.next_action_reason == (
        "Rust syntax is progressing faster than problem-solving skill with "
        "high-confidence evidence."
    )


def test_build_assessment_does_not_branch_without_high_confidence():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code=None,
            compiler_output="error: expected `;`",
            command_run_metadata=[
                _command_metadata(exit_code=101, output_summary="cargo check failed"),
                _command_metadata(
                    exit_code=101,
                    output_summary="cargo check failed again",
                ),
            ],
            learner_notes="I am still seeing the semicolon error.",
            submitted_at=_fixed_now(),
        ),
        concept=_concept(["rust_correctness", "compiler_error_handling"]),
        difficulty=Difficulty.GUIDED,
        now=_fixed_now(),
    )

    assert assessment.confidence < 0.80
    assert assessment.next_action == NextAction.SIMPLIFY
    assert assessment.branch_id is None


def test_build_assessment_explains_missing_confidence_evidence():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code=None,
            learner_notes="I have not run this yet.",
            submitted_at=_fixed_now(),
        ),
        concept=_concept(["rust_correctness", "compiler_error_handling"]),
        difficulty=Difficulty.INTRO,
        now=_fixed_now(),
    )

    assert assessment.confidence_breakdown.critical_evidence_cap == 0.44
    assert (
        "Code and primary execution evidence were missing, limiting confidence."
        in assessment.confidence_breakdown.explanation
    )
    assert "Compiler output was not submitted." in (
        assessment.confidence_breakdown.explanation
    )


def test_build_assessment_explains_conflicting_agent_notes():
    assessment = build_assessment(
        attempt=AttemptSubmission(
            attempt_id="attempt_1",
            learner_id="local-default",
            assignment_id="assign_1",
            lesson_id="lesson_1",
            client_request_id=None,
            client_request_fingerprint=None,
            workspace_root=None,
            code="fn main() { println!(\"hi\"); }",
            compiler_output="test result: ok. 1 passed; 0 failed",
            agent_notes="The submitted solution fails to compile.",
            submitted_at=_fixed_now(),
        ),
        concept=_concept(["rust_correctness"]),
        difficulty=Difficulty.STANDARD,
        now=_fixed_now(),
    )

    assert "Agent notes conflicted with submitted execution evidence." in (
        assessment.confidence_breakdown.explanation
    )


def test_validate_rubric_ids_rejects_empty_list():
    with pytest.raises(ValidationError):
        validate_rubric_ids([])


def test_validate_rubric_ids_rejects_unknown_rubric():
    with pytest.raises(ValidationError):
        validate_rubric_ids(["unknown"])


def _concept(rubric_ids: list[str]) -> Concept:
    return Concept(
        concept_id="concept_1",
        title="Concept",
        order=1,
        default_difficulty="intro",
        learner_command=None,
        rubric_ids=rubric_ids,
        variants=[
            LessonVariant(
                variant_id="intro_001",
                difficulty="intro",
                prompt="Prompt",
                success_criteria=["criterion"],
            )
        ],
    )


def _fixed_now() -> datetime:
    return datetime(2026, 5, 10, tzinfo=timezone.utc)


def _command_metadata(
    exit_code: int,
    output_summary: str,
) -> CommandRunMetadata:
    return CommandRunMetadata(
        command="cargo check",
        source="learner",
        cwd=None,
        exit_code=exit_code,
        started_at=_fixed_now(),
        output_summary=output_summary,
    )
