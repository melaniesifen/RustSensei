from __future__ import annotations

from collections.abc import Iterable

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.enums import AssignmentStatus, NextAction
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.domain.skill import SkillScore
from rust_sensei.dto.mappers import progress_event_to_dto
from rust_sensei.dto.progress import GetProgressSummaryRequest, GetProgressSummaryResponse
from rust_sensei.errors import not_found_error, validation_error
from rust_sensei.repositories.interfaces import (
    AssessmentRepository,
    AssignmentRepository,
    CurriculumRepository,
    LearnerRepository,
    ProgressEventRepository,
)

RECENT_PROGRESS_EVENT_LIMIT = 10
COMPLETED_CONCEPT_SCORE_THRESHOLD = 0.70
COMPLETED_CONCEPT_CONFIDENCE_THRESHOLD = 0.60
COMPLETION_ACTIONS = {
    NextAction.CONTINUE,
    NextAction.ACCELERATE,
}

TREND_NO_ASSESSMENTS = "no_assessments"
TREND_NEEDS_PRACTICE = "needs_practice"
TREND_STEADY = "steady"
TREND_ACCELERATING = "accelerating"

FOCUS_START_SESSION = "start_session"
FOCUS_COMPLETE_ACTIVE_ASSIGNMENT = "complete_active_assignment"
FOCUS_ASSESS_PENDING_ATTEMPT = "assess_pending_attempt"
FOCUS_RETRY_REPEATED_CONCEPT = "retry_repeated_concept"
FOCUS_CONTINUE_ACTIVE_CONCEPT = "continue_active_concept"


class ProgressService:
    def __init__(
        self,
        learner_repository: LearnerRepository,
        assignment_repository: AssignmentRepository,
        assessment_repository: AssessmentRepository,
        curriculum_repository: CurriculumRepository,
        progress_event_repository: ProgressEventRepository,
    ) -> None:
        self._learner_repository = learner_repository
        self._assignment_repository = assignment_repository
        self._assessment_repository = assessment_repository
        self._curriculum_repository = curriculum_repository
        self._progress_event_repository = progress_event_repository

    def get_progress_summary(
        self,
        request: GetProgressSummaryRequest,
    ) -> GetProgressSummaryResponse:
        self._validate_request(request)
        profile = self._learner_repository.get_profile(request.learner_id)
        if profile is None:
            raise not_found_error(
                "Learner profile was not found",
                learner_id=request.learner_id,
            )

        assignments = self._assignment_repository.list_assignments_for_learner(
            request.learner_id
        )
        assignment_ids = {assignment.assignment_id for assignment in assignments}
        assessments = self._assessment_repository.list_assessments_for_assignments(
            assignment_ids
        )
        recent_events = self._progress_event_repository.list_recent_events(
            request.learner_id,
            limit=RECENT_PROGRESS_EVENT_LIMIT,
        )
        all_events = self._progress_event_repository.list_events_for_learner(
            request.learner_id
        )

        completed_concepts = self._completed_concepts(
            profile=profile,
            assignments=assignments,
            assessments=assessments,
        )
        repeated_concepts = self._concepts_with_next_action(
            assignments=assignments,
            assessments=assessments,
            action=NextAction.REPEAT,
        )
        skipped_concepts = self._skipped_concepts(all_events)
        active_assignment = _assignment_with_status(
            assignments,
            AssignmentStatus.ACTIVE,
        )

        return GetProgressSummaryResponse(
            learner_id=profile.learner_id,
            active_concept_id=_active_concept_id(profile, active_assignment),
            completed_concepts=completed_concepts,
            repeated_concepts=repeated_concepts,
            skipped_concepts=skipped_concepts,
            recent_events=[
                progress_event_to_dto(event)
                for event in recent_events
            ],
            recommended_focus=self._recommended_focus(
                profile=profile,
                assignments=assignments,
                repeated_concepts=repeated_concepts,
            ),
            trend=self._trend(assessments),
        )

    def get_active_progress_summary(self) -> GetProgressSummaryResponse:
        return self.get_progress_summary(
            GetProgressSummaryRequest(learner_id=ACTIVE_LEARNER_ID)
        )

    def _completed_concepts(
        self,
        profile: LearnerProfile,
        assignments: list[LessonAssignment],
        assessments: list[AssessmentResult],
    ) -> list[str]:
        completed_from_skill_model = {
            concept_id
            for concept_id, score in profile.skill_model.rust_concepts.items()
            if _is_completed(score)
        }
        completed_from_assessments = self._concepts_with_next_actions(
            assignments=assignments,
            assessments=assessments,
            actions=COMPLETION_ACTIONS,
        )
        return self._sort_concept_ids(
            completed_from_skill_model | set(completed_from_assessments)
        )

    def _concepts_with_next_action(
        self,
        assignments: list[LessonAssignment],
        assessments: list[AssessmentResult],
        action: NextAction,
    ) -> list[str]:
        return self._concepts_with_next_actions(
            assignments=assignments,
            assessments=assessments,
            actions={action},
        )

    def _concepts_with_next_actions(
        self,
        assignments: list[LessonAssignment],
        assessments: list[AssessmentResult],
        actions: set[NextAction],
    ) -> list[str]:
        concept_by_assignment_id = {
            assignment.assignment_id: assignment.concept_id
            for assignment in assignments
        }
        concept_ids = {
            concept_by_assignment_id[assessment.assignment_id]
            for assessment in assessments
            if assessment.next_action in actions
            and assessment.assignment_id in concept_by_assignment_id
        }
        return self._sort_concept_ids(concept_ids)

    def _skipped_concepts(self, events: Iterable[ProgressEvent]) -> list[str]:
        concept_ids = {
            str(event.details["concept_id"])
            for event in events
            if event.event_type
            in {
                ProgressEventType.PROVISIONALLY_SKIPPED,
                ProgressEventType.SKIP_CONFIRMED,
            }
            and "concept_id" in event.details
        }
        return self._sort_concept_ids(concept_ids)

    def _recommended_focus(
        self,
        profile: LearnerProfile,
        assignments: list[LessonAssignment],
        repeated_concepts: list[str],
    ) -> str:
        active_assignment = _assignment_with_status(assignments, AssignmentStatus.ACTIVE)
        if active_assignment is not None:
            return FOCUS_COMPLETE_ACTIVE_ASSIGNMENT

        attempted_assignment = _assignment_with_status(
            assignments,
            AssignmentStatus.ATTEMPTED,
        )
        if attempted_assignment is not None:
            return FOCUS_ASSESS_PENDING_ATTEMPT

        if repeated_concepts:
            return FOCUS_RETRY_REPEATED_CONCEPT

        if profile.active_concept_id is not None:
            return FOCUS_CONTINUE_ACTIVE_CONCEPT

        return FOCUS_START_SESSION

    def _sort_concept_ids(self, concept_ids: Iterable[str]) -> list[str]:
        curriculum = self._curriculum_repository.get_curriculum()
        order_by_concept_id = {
            concept.concept_id: concept.order
            for concept in curriculum.concepts.values()
        }
        return sorted(
            set(concept_ids),
            key=lambda concept_id: (
                order_by_concept_id.get(concept_id, len(order_by_concept_id)),
                concept_id,
            ),
        )

    @staticmethod
    def _trend(assessments: list[AssessmentResult]) -> str:
        if not assessments:
            return TREND_NO_ASSESSMENTS

        latest = assessments[-1]
        if latest.next_action in {NextAction.REPEAT, NextAction.SIMPLIFY}:
            return TREND_NEEDS_PRACTICE
        if latest.next_action == NextAction.ACCELERATE:
            return TREND_ACCELERATING
        return TREND_STEADY

    @staticmethod
    def _validate_request(request: GetProgressSummaryRequest) -> None:
        if request.learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=request.learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )


def _is_completed(score: SkillScore) -> bool:
    return (
        score.score >= COMPLETED_CONCEPT_SCORE_THRESHOLD
        and score.confidence >= COMPLETED_CONCEPT_CONFIDENCE_THRESHOLD
    )


def _assignment_with_status(
    assignments: list[LessonAssignment],
    status: AssignmentStatus,
) -> LessonAssignment | None:
    return next(
        (
            assignment
            for assignment in reversed(assignments)
            if assignment.status == status
        ),
        None,
    )


def _active_concept_id(
    profile: LearnerProfile,
    active_assignment: LessonAssignment | None,
) -> str | None:
    if active_assignment is not None:
        return active_assignment.concept_id
    return profile.active_concept_id
