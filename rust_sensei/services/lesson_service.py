from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.curriculum import Concept, LessonVariant
from rust_sensei.domain.enums import AssignmentStatus
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.lesson_selection import (
    LessonSelectionDecision,
    LessonSelectionContext,
    default_lesson_selector,
)
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.dto.lesson import GetNextLessonRequest, GetNextLessonResponse
from rust_sensei.dto.mappers import lesson_assignment_to_dto, lesson_plan_to_dto
from rust_sensei.errors import not_found_error, validation_error
from rust_sensei.repositories.interfaces import (
    AssessmentRepository,
    AssignmentRepository,
    AttemptRepository,
    CurriculumRepository,
    LearnerRepository,
    ProgressEventRepository,
)

LOGGER = logging.getLogger(__name__)


class LessonService:
    def __init__(
        self,
        learner_repository: LearnerRepository,
        assignment_repository: AssignmentRepository,
        attempt_repository: AttemptRepository,
        assessment_repository: AssessmentRepository,
        curriculum_repository: CurriculumRepository,
        progress_event_repository: ProgressEventRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._learner_repository = learner_repository
        self._assignment_repository = assignment_repository
        self._attempt_repository = attempt_repository
        self._assessment_repository = assessment_repository
        self._curriculum_repository = curriculum_repository
        self._progress_event_repository = progress_event_repository
        self._lesson_selector = default_lesson_selector()
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
            if request.abandon_active_assignment:
                self._abandon_assignment(
                    active_assignment,
                    request.abandonment_reason,
                )
            elif request.force_new_variant:
                raise validation_error(
                    "force_new_variant requires abandon_active_assignment when an active assignment exists",
                    assignment_id=active_assignment.assignment_id,
                )
            else:
                LOGGER.debug(
                    "Reusing active assignment assignment_id=%s learner_id=%s",
                    active_assignment.assignment_id,
                    request.learner_id,
                )
                return self._viewed_response_for_assignment(
                    active_assignment,
                    reused_active_assignment=True,
                )

        if request.abandon_active_assignment and active_assignment is None:
            raise validation_error(
                "abandon_active_assignment requires an active assignment",
                learner_id=request.learner_id,
            )
        if request.force_new_variant and active_assignment is None:
            raise validation_error(
                "force_new_variant requires an active assignment and abandon_active_assignment",
                learner_id=request.learner_id,
            )

        active_assignment_after_abandon = self._assignment_repository.get_active_assignment(
            request.learner_id
        )
        if active_assignment_after_abandon is not None:
            LOGGER.debug(
                "Reusing active assignment assignment_id=%s learner_id=%s",
                active_assignment_after_abandon.assignment_id,
                request.learner_id,
            )
            return self._viewed_response_for_assignment(
                active_assignment_after_abandon,
                reused_active_assignment=True,
            )

        attempted_assignment = self._assignment_repository.get_attempted_assignment(
            request.learner_id
        )
        if attempted_assignment is not None:
            pending_attempt = self._attempt_repository.get_latest_attempt_for_assignment(
                attempted_assignment.assignment_id
            )
            return GetNextLessonResponse(
                assignment=None,
                lesson_plan=None,
                reused_active_assignment=False,
                pending_assessment=True,
                pending_attempt_id=pending_attempt.attempt_id if pending_attempt else None,
            )

        if profile.active_concept_id is None:
            raise validation_error(
                "Learner profile does not have an active concept",
                learner_id=request.learner_id,
            )

        assessed_assignment = self._assignment_repository.get_latest_assessed_assignment(
            request.learner_id
        )
        if assessed_assignment is not None:
            decision = self._selection_after_assessment(assessed_assignment)
        else:
            concept = self._get_concept(profile.active_concept_id)
            decision = LessonSelectionDecision(
                concept=concept,
                variant=concept.default_variant(),
                selection_rationale="Selected from learner placement active concept.",
            )

        return self._create_assignment_from_decision(
            request.learner_id,
            decision,
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

    def _viewed_response_for_assignment(
        self,
        assignment: LessonAssignment,
        reused_active_assignment: bool,
    ) -> GetNextLessonResponse:
        response = self._response_for_assignment(
            assignment,
            reused_active_assignment=reused_active_assignment,
        )
        self._record_assignment_viewed(assignment)
        return response

    def _get_concept(self, concept_id: str) -> Concept:
        concept = self._curriculum_repository.get_concept(concept_id)
        if concept is None:
            raise not_found_error(
                "Curriculum concept was not found",
                concept_id=concept_id,
            )
        return concept

    def _selection_after_assessment(
        self,
        assignment: LessonAssignment,
    ) -> LessonSelectionDecision:
        assessment = self._assessment_repository.get_latest_assessment_for_assignment(
            assignment.assignment_id
        )
        if assessment is None:
            raise not_found_error(
                "Assessment was not found for assessed assignment",
                assignment_id=assignment.assignment_id,
            )
        curriculum = self._curriculum_repository.get_curriculum()
        return self._lesson_selector.select_next_lesson(
            LessonSelectionContext(
                curriculum=curriculum,
                last_assignment=assignment,
                last_assessment=assessment,
            )
        )

    def _create_assignment_from_decision(
        self,
        learner_id: str,
        decision: LessonSelectionDecision,
    ) -> GetNextLessonResponse:
        now = self._now()
        candidate = LessonAssignment(
            assignment_id="",
            learner_id=learner_id,
            lesson_id=_lesson_id(
                decision.concept.concept_id,
                decision.variant.variant_id,
            ),
            concept_id=decision.concept.concept_id,
            difficulty=decision.variant.difficulty,
            variant_id=decision.variant.variant_id,
            status=AssignmentStatus.ACTIVE,
            selection_rationale=decision.selection_rationale,
            curriculum_version=self._curriculum_repository.get_curriculum().curriculum_version,
            created_at=now,
            updated_at=now,
        )
        assignment, created = self._assignment_repository.create_active_assignment_if_absent(
            candidate,
            event_factory=lambda created_assignment: ProgressEvent(
                event_id="",
                learner_id=created_assignment.learner_id,
                event_type=ProgressEventType.ASSIGNMENT_CREATED,
                assignment_id=created_assignment.assignment_id,
                attempt_id=None,
                assessment_id=None,
                details={
                    "concept_id": created_assignment.concept_id,
                    "difficulty": created_assignment.difficulty,
                    "variant_id": created_assignment.variant_id,
                    "selection_rationale": created_assignment.selection_rationale,
                },
                previous_status=None,
                new_status=AssignmentStatus.ACTIVE.value,
                created_at=now,
            ),
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
            concept=decision.concept,
            variant=decision.variant,
        )

    def _abandon_assignment(
        self,
        assignment: LessonAssignment,
        abandonment_reason: str | None,
    ) -> None:
        if not abandonment_reason:
            raise validation_error(
                "abandonment_reason is required when abandoning an active assignment",
                assignment_id=assignment.assignment_id,
            )
        now = self._now()
        abandoned = LessonAssignment(
            assignment_id=assignment.assignment_id,
            learner_id=assignment.learner_id,
            lesson_id=assignment.lesson_id,
            concept_id=assignment.concept_id,
            difficulty=assignment.difficulty,
            variant_id=assignment.variant_id,
            status=AssignmentStatus.ABANDONED,
            selection_rationale=(
                f"{assignment.selection_rationale} Abandoned: {abandonment_reason}"
            ),
            curriculum_version=assignment.curriculum_version,
            created_at=assignment.created_at,
            updated_at=now,
        )
        self._assignment_repository.update_assignment(
            abandoned,
            event_factory=lambda saved_assignment: ProgressEvent(
                event_id="",
                learner_id=saved_assignment.learner_id,
                event_type=ProgressEventType.ABANDONED,
                assignment_id=saved_assignment.assignment_id,
                attempt_id=None,
                assessment_id=None,
                details={"reason": abandonment_reason},
                previous_status=AssignmentStatus.ACTIVE.value,
                new_status=AssignmentStatus.ABANDONED.value,
                created_at=now,
            ),
        )
        LOGGER.info(
            "Abandoned lesson assignment assignment_id=%s learner_id=%s",
            assignment.assignment_id,
            assignment.learner_id,
        )

    def _record_assignment_viewed(self, assignment: LessonAssignment) -> None:
        self._progress_event_repository.save_event(
            ProgressEvent(
                event_id="",
                learner_id=assignment.learner_id,
                event_type=ProgressEventType.ASSIGNMENT_VIEWED,
                assignment_id=assignment.assignment_id,
                attempt_id=None,
                assessment_id=None,
                details={
                    "concept_id": assignment.concept_id,
                    "variant_id": assignment.variant_id,
                },
                previous_status=AssignmentStatus.ACTIVE.value,
                new_status=AssignmentStatus.ACTIVE.value,
                created_at=self._now(),
            )
        )

    @staticmethod
    def _validate_request(request: GetNextLessonRequest) -> None:
        if request.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=request.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )

        if request.abandon_active_assignment and not request.abandonment_reason:
            raise validation_error(
                "abandonment_reason is required when abandon_active_assignment is true"
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
