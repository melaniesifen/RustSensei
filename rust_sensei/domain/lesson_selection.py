from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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


@dataclass(frozen=True)
class LessonSelectionDecision:
    concept: Concept
    variant: LessonVariant
    selection_rationale: str


LessonHandler = Callable[[LessonSelectionContext], LessonSelectionDecision]


class LessonSelector:
    def __init__(self, handlers: dict[str, LessonHandler]) -> None:
        self._handlers = handlers

    def select_next_lesson(
        self,
        context: LessonSelectionContext,
    ) -> LessonSelectionDecision:
        handler = self._handlers.get(_next_action_or_none(context.last_assessment.next_action))
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


def select_simplified_lesson(
    context: LessonSelectionContext,
) -> LessonSelectionDecision:
    concept = context.curriculum.concepts[context.last_assignment.concept_id]
    target_difficulty = _lower_difficulty(context.last_assignment.difficulty)
    variant = _variant_for_difficulty(concept, target_difficulty)
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
    variant = _variant_for_difficulty(concept, context.last_assignment.difficulty)
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            "Selected by repeat action after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_next_concept(context: LessonSelectionContext) -> LessonSelectionDecision:
    concept = _next_concept(context.curriculum, context.last_assignment.concept_id)
    variant = concept.default_variant()
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            "Selected by continue action after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_accelerated_concept(
    context: LessonSelectionContext,
) -> LessonSelectionDecision:
    concept = _next_concept(context.curriculum, context.last_assignment.concept_id)
    variant = _variant_for_difficulty(concept, Difficulty.CHALLENGE)
    return LessonSelectionDecision(
        concept=concept,
        variant=variant,
        selection_rationale=(
            "Selected by accelerate action after assessment: "
            f"{context.last_assessment.next_action_reason}"
        ),
    )


def select_branch_lesson(context: LessonSelectionContext) -> LessonSelectionDecision:
    # Branch target resolution requires branch-target curriculum metadata. Until that
    # metadata exists in the seed schema, fall back to repeat with an explicit rationale.
    repeated = select_repeat_variant(context)
    return LessonSelectionDecision(
        concept=repeated.concept,
        variant=repeated.variant,
        selection_rationale=(
            "Branch action fell back to repeat because branch targets are not "
            f"implemented: {context.last_assessment.next_action_reason}"
        ),
    )


def _next_concept(curriculum: Curriculum, current_concept_id: str) -> Concept:
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
        return curriculum.concepts[current_concept_id]
    return ordered[current_index + 1]


def _lower_difficulty(difficulty: str) -> str:
    try:
        index = DIFFICULTY_ORDER.index(difficulty)
    except ValueError:
        return Difficulty.INTRO
    return DIFFICULTY_ORDER[max(index - 1, 0)]


def _variant_for_difficulty(concept: Concept, difficulty: str) -> LessonVariant:
    return next(
        (
            variant
            for variant in concept.variants
            if variant.difficulty == difficulty
        ),
        concept.default_variant(),
    )


def _next_action_or_none(value: str) -> NextAction | None:
    try:
        return NextAction(value)
    except ValueError:
        return None
