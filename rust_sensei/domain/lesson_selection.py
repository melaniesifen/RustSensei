from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.curriculum import Concept, Curriculum, LessonVariant
from rust_sensei.domain.enums import Difficulty, NextAction
from rust_sensei.domain.lesson import LessonAssignment

DIFFICULTY_ORDER = [
    Difficulty.INTRO,
    Difficulty.GUIDED,
    Difficulty.STANDARD,
    Difficulty.CHALLENGE,
    Difficulty.ADVANCED,
]


@dataclass(frozen=True)
class LessonSelectionContext:
    curriculum: Curriculum
    last_assignment: LessonAssignment
    last_assessment: AssessmentResult
    prior_assignments: list[LessonAssignment] = field(default_factory=list)
    reopenable_concept_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class LessonSelectionDecision:
    concept: Concept
    variant: LessonVariant
    selection_rationale: str
    branch_id: str | None = None
    reopened_concept_id: str | None = None
    reopen_reason: str | None = None


@dataclass(frozen=True)
class _NextConceptSelection:
    concept: Concept
    rationale_detail: str


LessonHandler = Callable[[LessonSelectionContext], LessonSelectionDecision]


class LessonSelector:
    def __init__(self, handlers: dict[str, LessonHandler]) -> None:
        self._handlers = handlers

    def select_next_lesson(
        self,
        context: LessonSelectionContext,
    ) -> LessonSelectionDecision:
        reopened = _reopened_prerequisite_decision(context)
        if reopened is not None:
            return reopened

        handler = self._handlers.get(
            _next_action_or_none(context.last_assessment.next_action)
        )
        if handler is None:
            return select_repeat_variant(context)
        return handler(context)


def default_lesson_selector() -> LessonSelector:
    return LessonSelector(
        handlers={
            NextAction.SIMPLIFY: select_simplified_lesson,
            NextAction.REPEAT: select_repeat_variant,
            NextAction.CONTINUE: select_next_concept,
            NextAction.ACCELERATE: select_accelerated_concept,
            NextAction.BRANCH: select_branch_lesson,
        }
    )


def select_placement_lesson(
    curriculum: Curriculum,
    concept_id: str,
    prior_assignments: list[LessonAssignment],
) -> LessonSelectionDecision:
    concept = curriculum.concepts[concept_id]
    variant = _variant_for_difficulty(
        concept=concept,
        difficulty=concept.default_difficulty,
        prior_assignments=prior_assignments,
    )
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale="Selected from learner placement active concept.",
    )


def select_simplified_lesson(
    context: LessonSelectionContext,
) -> LessonSelectionDecision:
    concept = context.curriculum.concepts[context.last_assignment.concept_id]
    target_difficulty = _lower_difficulty(context.last_assignment.difficulty)
    variant = _variant_for_difficulty(
        concept=concept,
        difficulty=target_difficulty,
        prior_assignments=context.prior_assignments,
    )
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            "Selected by simplify action after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_repeat_variant(context: LessonSelectionContext) -> LessonSelectionDecision:
    concept = context.curriculum.concepts[context.last_assignment.concept_id]
    variant = _variant_for_difficulty(
        concept=concept,
        difficulty=context.last_assignment.difficulty,
        prior_assignments=context.prior_assignments,
    )
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            "Selected by repeat action after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_next_concept(context: LessonSelectionContext) -> LessonSelectionDecision:
    selected = _next_concept(context.curriculum, context.last_assignment.concept_id)
    concept = selected.concept
    variant = _variant_for_difficulty(
        concept=concept,
        difficulty=concept.default_difficulty,
        prior_assignments=context.prior_assignments,
    )
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            f"Selected by continue action after assessment; {selected.rationale_detail}: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_accelerated_concept(
    context: LessonSelectionContext,
) -> LessonSelectionDecision:
    selected = _next_concept(context.curriculum, context.last_assignment.concept_id)
    concept = selected.concept
    variant = _variant_for_difficulty(
        concept=concept,
        difficulty=Difficulty.CHALLENGE,
        prior_assignments=context.prior_assignments,
    )
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            f"Selected by accelerate action after assessment; {selected.rationale_detail}: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_branch_lesson(context: LessonSelectionContext) -> LessonSelectionDecision:
    branch_id = context.last_assessment.branch_id
    if branch_id is None:
        return _branch_fallback_decision(
            context,
            "Branch action fell back to repeat because no branch_id was provided",
        )

    current_concept = context.curriculum.concepts[context.last_assignment.concept_id]
    target_concept = _branch_target_concept(
        curriculum=context.curriculum,
        current_concept=current_concept,
        branch_id=branch_id,
    )
    if target_concept is None:
        return _branch_fallback_decision(
            context,
            f"Branch action fell back to repeat because branch_id {branch_id} has no target",
        )

    return LessonSelectionDecision(
        concept=target_concept,
        variant=_variant_for_difficulty(
            concept=target_concept,
            difficulty=target_concept.default_difficulty,
            prior_assignments=context.prior_assignments,
        ),
        branch_id=branch_id,
        selection_rationale=(
            f"Selected branch target {branch_id} after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def _branch_fallback_decision(
    context: LessonSelectionContext,
    reason: str,
) -> LessonSelectionDecision:
    repeated = select_repeat_variant(context)
    return LessonSelectionDecision(
        concept=repeated.concept,
        variant=repeated.variant,
        branch_id=context.last_assessment.branch_id,
        selection_rationale=f"{reason}: {context.last_assessment.next_action_reason}",
    )


def _branch_target_concept(
    curriculum: Curriculum,
    current_concept: Concept,
    branch_id: str,
) -> Concept | None:
    target_ids = current_concept.branch_targets.get(
        branch_id,
        curriculum.branch_fallbacks.get(branch_id, []),
    )
    return next(
        (
            curriculum.concepts[concept_id]
            for concept_id in target_ids
            if concept_id in curriculum.concepts
        ),
        None,
    )


def _next_concept(
    curriculum: Curriculum,
    current_concept_id: str,
) -> _NextConceptSelection:
    current_concept = curriculum.concepts[current_concept_id]
    for target_id in current_concept.next_concepts:
        target = curriculum.concepts.get(target_id)
        if target is not None:
            return _NextConceptSelection(
                concept=target,
                rationale_detail=f"followed concept graph next_concepts to {target_id}",
            )

    ordered = sorted(curriculum.concepts.values(), key=lambda concept: concept.order)
    current_index = next(
        (
            index
            for index, concept in enumerate(ordered)
            if concept.concept_id == current_concept_id
        ),
        None,
    )
    if current_index is None or current_index == len(ordered) - 1:
        return _NextConceptSelection(
            concept=current_concept,
            rationale_detail="no next concept was available, repeating current concept",
        )
    target = ordered[current_index + 1]
    return _NextConceptSelection(
        concept=target,
        rationale_detail=f"used curriculum order fallback to {target.concept_id}",
    )


def _reopened_prerequisite_decision(
    context: LessonSelectionContext,
) -> LessonSelectionDecision | None:
    if not context.reopenable_concept_ids:
        return None

    current_concept = context.curriculum.concepts[context.last_assignment.concept_id]
    for prerequisite_id in current_concept.prerequisites:
        if prerequisite_id not in context.reopenable_concept_ids:
            continue
        prerequisite = context.curriculum.concepts.get(prerequisite_id)
        if prerequisite is None:
            continue
        weak_rubric = _weak_reopen_rubric(context.last_assessment, prerequisite)
        if weak_rubric is None:
            continue

        rubric_id, score, confidence = weak_rubric
        variant = _variant_for_difficulty(
            concept=prerequisite,
            difficulty=prerequisite.default_difficulty,
            prior_assignments=context.prior_assignments,
        )
        reason = (
            f"Reopened prerequisite {prerequisite_id} because rubric {rubric_id} "
            f"scored {score:.2f} with confidence {confidence:.2f}."
        )
        return LessonSelectionDecision(
            concept=prerequisite,
            variant=variant,
            reopened_concept_id=prerequisite_id,
            reopen_reason=reason,
            selection_rationale=(
                "Selected by prerequisite reopening after assessment: "
                f"{reason} Original next action was "
                f"{context.last_assessment.next_action.value}: "
                f"{context.last_assessment.next_action_reason}"
            ),
        )

    return None


def _weak_reopen_rubric(
    assessment: AssessmentResult,
    prerequisite: Concept,
) -> tuple[str, float, float] | None:
    required_rubric_ids = (
        list(prerequisite.completion_thresholds)
        if prerequisite.completion_thresholds
        else prerequisite.rubric_ids
    )
    for rubric_id in required_rubric_ids:
        score = assessment.rubric_scores.get(rubric_id)
        if score is None:
            continue
        if score.score < 0.50 and score.confidence >= 0.60:
            return rubric_id, score.score, score.confidence
    return None


def _lower_difficulty(difficulty: str) -> str:
    try:
        index = DIFFICULTY_ORDER.index(difficulty)
    except ValueError:
        return Difficulty.INTRO
    return DIFFICULTY_ORDER[max(index - 1, 0)]


def _variant_for_difficulty(
    concept: Concept,
    difficulty: str,
    prior_assignments: list[LessonAssignment],
) -> LessonVariant:
    candidates = [
        variant
        for variant in concept.variants
        if variant.difficulty == difficulty
    ]
    if not candidates:
        return concept.default_variant()

    used_variant_ids = {
        assignment.variant_id
        for assignment in prior_assignments
        if assignment.concept_id == concept.concept_id
        and assignment.difficulty == difficulty
    }
    return next(
        (variant for variant in candidates if variant.variant_id not in used_variant_ids),
        candidates[0],
    )


def _next_action_or_none(value: str) -> NextAction | None:
    try:
        return NextAction(value)
    except ValueError:
        return None
