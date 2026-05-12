from __future__ import annotations

from datetime import datetime, timezone

import pytest

from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.domain.curriculum import Concept, LessonVariant
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
        difficulty="challenge",
        now=_fixed_now(),
    )

    assert assessment.assessment_status == "assessed"
    assert assessment.rubric_scores["rust_idioms"].score == 0.67
    assert assessment.rubric_scores["maintainability"].score == 0.82
    assert assessment.rubric_scores["dsa"].score == 0.90
    assert assessment.next_action == "repeat"


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
        difficulty="intro",
        now=_fixed_now(),
    )

    assert assessment.rubric_scores["rust_correctness"].score == 0.35
    assert assessment.rubric_scores["compiler_error_handling"].score == 0.45
    assert assessment.next_action == "simplify"


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
