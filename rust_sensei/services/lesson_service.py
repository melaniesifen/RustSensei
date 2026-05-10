from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.curriculum import Concept, LessonVariant
from rust_sensei.domain.enums import AssignmentStatus
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.dto.lesson import GetNextLessonRequest, GetNextLessonResponse
from rust_sensei.dto.mappers import lesson_assignment_to_dto, lesson_plan_to_dto
from rust_sensei.errors import not_found_error, validation_error
from rust_sensei.repositories.interfaces import (
    AssignmentRepository,
    CurriculumRepository,
    LearnerRepository,
)

LOGGER = logging.getLogger(__name__)


class LessonService:
    def __init__(
        self,
        learner_repository: LearnerRepository,
        assignment_repository: AssignmentRepository,
        curriculum_repository: CurriculumRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._learner_repository = learner_repository
        self._assignment_repository = assignment_repository
        self._curriculum_repository = curriculum_repository
        self._now = now

    def get_next_lesson(self, request: GetNextLessonRequest) -> GetNextLessonResponse:
        self._validate_request(request)

        profile = self._learner_repository.get_profile(request.learner_id)
        if profile is None:
            raise not_found_error(
                "Learner profile was not found",
                learner_id=request.learner_id,
            )

        active_assignment = self._assignment_repository.get_active_assignment(
            request.learner_id
        )
        if active_assignment is not None:
            LOGGER.debug(
                "Reusing active assignment assignment_id=%s learner_id=%s",
                active_assignment.assignment_id,
                request.learner_id,
            )
            return self._response_for_assignment(
                active_assignment,
                reused_active_assignment=True,
            )

        if profile.active_concept_id is None:
            raise validation_error(
                "Learner profile does not have an active concept",
                learner_id=request.learner_id,
            )

        concept = self._get_concept(profile.active_concept_id)
        variant = concept.default_variant()
        now = self._now()
        candidate = LessonAssignment(
            assignment_id="",
            learner_id=request.learner_id,
            lesson_id=_lesson_id(concept.concept_id, variant.variant_id),
            concept_id=concept.concept_id,
            difficulty=variant.difficulty,
            variant_id=variant.variant_id,
            status=AssignmentStatus.ACTIVE,
            selection_rationale="Selected from learner placement active concept.",
            curriculum_version=self._curriculum_repository.get_curriculum().curriculum_version,
            created_at=now,
            updated_at=now,
        )
        assignment, created = self._assignment_repository.create_active_assignment_if_absent(
            candidate
        )
        if created:
            LOGGER.info(
                "Created lesson assignment assignment_id=%s learner_id=%s concept_id=%s",
                assignment.assignment_id,
                assignment.learner_id,
                assignment.concept_id,
            )
        return self._response_for_assignment(
            assignment,
            reused_active_assignment=not created,
            concept=concept,
            variant=variant,
        )

    def _response_for_assignment(
        self,
        assignment: LessonAssignment,
        reused_active_assignment: bool,
        concept: Concept | None = None,
        variant: LessonVariant | None = None,
    ) -> GetNextLessonResponse:
        resolved_concept = concept or self._get_concept(assignment.concept_id)
        resolved_variant = variant or _find_variant(
            resolved_concept,
            assignment.variant_id,
        )
        return GetNextLessonResponse(
            assignment=lesson_assignment_to_dto(assignment),
            lesson_plan=lesson_plan_to_dto(resolved_concept, resolved_variant),
            reused_active_assignment=reused_active_assignment,
        )

    def _get_concept(self, concept_id: str) -> Concept:
        concept = self._curriculum_repository.get_concept(concept_id)
        if concept is None:
            raise not_found_error(
                "Curriculum concept was not found",
                concept_id=concept_id,
            )
        return concept

    @staticmethod
    def _validate_request(request: GetNextLessonRequest) -> None:
        if request.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=request.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )

        if request.force_new_variant:
            raise validation_error(
                "force_new_variant is not supported until variant selection is implemented"
            )

        if request.abandon_active_assignment:
            raise validation_error(
                "abandon_active_assignment is not supported until assignment lifecycle is implemented"
            )


def _find_variant(concept: Concept, variant_id: str) -> LessonVariant:
    variant = next(
        (variant for variant in concept.variants if variant.variant_id == variant_id),
        None,
    )
    if variant is None:
        raise not_found_error(
            "Assignment variant was not found in the curriculum",
            concept_id=concept.concept_id,
            variant_id=variant_id,
        )
    return variant


def _lesson_id(concept_id: str, variant_id: str) -> str:
    return f"{concept_id}:{variant_id}"
