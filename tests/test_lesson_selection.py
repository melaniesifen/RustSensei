from __future__ import annotations

from rust_sensei.domain.assessment import (
    AssessmentResult,
    AssessmentScoringProvenance,
    ConfidenceBreakdown,
)
from rust_sensei.domain.curriculum import Concept, Curriculum, LessonVariant
from rust_sensei.domain.enums import AssignmentStatus, Difficulty, NextAction
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.lesson_selection import (
    LessonSelectionContext,
    default_lesson_selector,
)
from tests.constants import TEST_LEARNER_ID, TEST_NOW


def test_lesson_selector_simplifies_to_lower_difficulty_variant():
    selector = default_lesson_selector()
    curriculum = _curriculum()

    decision = selector.select_next_lesson(
        LessonSelectionContext(
            curriculum=curriculum,
            last_assignment=_assignment("concept_1", Difficulty.STANDARD, "standard_001"),
            last_assessment=_assessment(NextAction.SIMPLIFY),
        )
    )

    assert decision.concept.concept_id == "concept_1"
    assert decision.variant.variant_id == "guided_001"
    assert decision.selection_rationale.startswith("Selected by simplify action")


def test_lesson_selector_repeats_for_unknown_action():
    selector = default_lesson_selector()
    curriculum = _curriculum()

    decision = selector.select_next_lesson(
        LessonSelectionContext(
            curriculum=curriculum,
            last_assignment=_assignment("concept_1", Difficulty.STANDARD, "standard_001"),
            last_assessment=_assessment("unknown"),
        )
    )

    assert decision.concept.concept_id == "concept_1"
    assert decision.variant.variant_id == "standard_001"


def test_lesson_selector_branch_falls_back_to_repeat():
    selector = default_lesson_selector()
    curriculum = _curriculum()

    decision = selector.select_next_lesson(
        LessonSelectionContext(
            curriculum=curriculum,
            last_assignment=_assignment("concept_1", Difficulty.STANDARD, "standard_001"),
            last_assessment=_assessment(NextAction.BRANCH),
        )
    )

    assert decision.concept.concept_id == "concept_1"
    assert decision.variant.variant_id == "standard_001"
    assert decision.selection_rationale.startswith("Branch action fell back to repeat")


def test_lesson_selector_continues_terminal_concept_to_same_concept():
    selector = default_lesson_selector()
    curriculum = _curriculum()

    decision = selector.select_next_lesson(
        LessonSelectionContext(
            curriculum=curriculum,
            last_assignment=_assignment("concept_2", Difficulty.CHALLENGE, "challenge_001"),
            last_assessment=_assessment(NextAction.CONTINUE),
        )
    )

    assert decision.concept.concept_id == "concept_2"
    assert decision.variant.variant_id == "challenge_001"


def _curriculum() -> Curriculum:
    first = Concept(
        concept_id="concept_1",
        title="Concept 1",
        order=1,
        default_difficulty=Difficulty.STANDARD,
        learner_command=None,
        rubric_ids=["rust_correctness"],
        variants=[
            LessonVariant(
                variant_id="guided_001",
                difficulty=Difficulty.GUIDED,
                prompt="guided",
                success_criteria=["done"],
            ),
            LessonVariant(
                variant_id="standard_001",
                difficulty=Difficulty.STANDARD,
                prompt="standard",
                success_criteria=["done"],
            ),
        ],
    )
    second = Concept(
        concept_id="concept_2",
        title="Concept 2",
        order=2,
        default_difficulty=Difficulty.CHALLENGE,
        learner_command=None,
        rubric_ids=["rust_correctness"],
        variants=[
            LessonVariant(
                variant_id="challenge_001",
                difficulty=Difficulty.CHALLENGE,
                prompt="challenge",
                success_criteria=["done"],
            )
        ],
    )
    return Curriculum(
        curriculum_version="test",
        concepts={
            first.concept_id: first,
            second.concept_id: second,
        },
    )


def _assignment(
    concept_id: str,
    difficulty: str,
    variant_id: str,
) -> LessonAssignment:
    return LessonAssignment(
        assignment_id="assign_1",
        learner_id=TEST_LEARNER_ID,
        lesson_id=f"{concept_id}:{variant_id}",
        concept_id=concept_id,
        difficulty=difficulty,
        variant_id=variant_id,
        status=AssignmentStatus.ASSESSED,
        selection_rationale="test",
        curriculum_version="test",
        created_at=TEST_NOW,
        updated_at=TEST_NOW,
    )


def _assessment(next_action: str) -> AssessmentResult:
    return AssessmentResult(
        assessment_id="assessment_1",
        attempt_id="attempt_1",
        assignment_id="assign_1",
        scoring_version="test",
        scoring_provenance=AssessmentScoringProvenance(
            scorer_type="deterministic",
            scorer_name="test",
            scorer_version="test",
        ),
        assessment_status="assessed",
        rubric_scores={},
        confidence_breakdown=ConfidenceBreakdown(
            critical_evidence_cap=None,
            evidence_completeness=1.0,
            evidence_quality=1.0,
            rubric_confidences={},
            prior_consistency=1.0,
            task_difficulty_weight=1.0,
            recency_weight=1.0,
            overall=1.0,
        ),
        missing_evidence=[],
        feedback_items=[],
        next_action=next_action,
        branch_id=None,
        next_action_reason="test reason",
        feedback_summary="test",
        confidence=1.0,
        created_at=TEST_NOW,
    )
