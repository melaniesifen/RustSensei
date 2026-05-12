from __future__ import annotations

import pytest

from rust_sensei.domain.assessment import AssessmentResult, ConfidenceBreakdown
from rust_sensei.domain.enums import NextAction
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.domain.skill_update import (
    max_delta_for_confidence,
    update_score,
    update_skill_model,
)
from tests.constants import CARGO_HELLO_WORLD_CONCEPT_ID, TEST_NOW


def test_update_skill_model_applies_confidence_dampening():
    assessment = _assessment(
        confidence=0.72,
        assessment_status="assessed",
        rubric_scores={
            "rust_correctness": SkillScore(0.85, 0.80, ["compiled"]),
            "compiler_error_handling": SkillScore(0.75, 0.70, ["read compiler"]),
            "readability": SkillScore(0.90, 0.65, ["clear names"]),
        },
    )

    updated = update_skill_model(
        model=SkillModel(),
        assessment=assessment,
        concept_id=CARGO_HELLO_WORLD_CONCEPT_ID,
    )

    assert updated.rust_concepts[CARGO_HELLO_WORLD_CONCEPT_ID].score == 0.70
    assert updated.rust_concepts[CARGO_HELLO_WORLD_CONCEPT_ID].confidence == 0.40
    assert updated.programming_dimensions["readability"].score == 0.70
    assert updated.programming_dimensions["readability"].confidence == 0.40


def test_update_skill_model_skips_insufficient_evidence():
    model = SkillModel(
        rust_concepts={
            CARGO_HELLO_WORLD_CONCEPT_ID: SkillScore(0.60, 0.50, ["existing"]),
        },
    )
    assessment = _assessment(
        confidence=0.44,
        assessment_status="insufficient_evidence",
        rubric_scores={
            "rust_correctness": SkillScore(0.90, 0.20, ["weak evidence"]),
        },
    )

    assert update_skill_model(model, assessment, CARGO_HELLO_WORLD_CONCEPT_ID) == model


def test_update_score_confidence_bands():
    assert update_score(previous=0.50, observed=1.00, confidence=0.44) == 0.55
    assert update_score(previous=0.50, observed=1.00, confidence=0.45) == 0.60
    assert update_score(previous=0.50, observed=1.00, confidence=0.60) == 0.70
    assert update_score(previous=0.50, observed=1.00, confidence=0.80) == 0.80
    assert update_score(previous=0.50, observed=0.00, confidence=0.80) == 0.20


def test_max_delta_for_confidence_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        max_delta_for_confidence(-0.01)
    with pytest.raises(ValueError):
        max_delta_for_confidence(1.01)


def _assessment(
    confidence: float,
    assessment_status: str,
    rubric_scores: dict[str, SkillScore],
) -> AssessmentResult:
    return AssessmentResult(
        assessment_id="assessment_1",
        attempt_id="attempt_1",
        assignment_id="assign_1",
        scoring_version="test",
        assessment_status=assessment_status,
        rubric_scores=rubric_scores,
        confidence_breakdown=ConfidenceBreakdown(
            critical_evidence_cap=None,
            evidence_completeness=confidence,
            evidence_quality=confidence,
            rubric_confidences={
                rubric_id: score.confidence
                for rubric_id, score in rubric_scores.items()
            },
            prior_consistency=0.60,
            task_difficulty_weight=0.70,
            recency_weight=1.00,
            overall=confidence,
        ),
        missing_evidence=[],
        feedback_items=[],
        next_action=NextAction.CONTINUE,
        branch_id=None,
        next_action_reason="test",
        feedback_summary="test",
        confidence=confidence,
        created_at=TEST_NOW,
    )
