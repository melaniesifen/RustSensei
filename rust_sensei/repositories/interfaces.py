from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.domain.curriculum import Concept, Curriculum
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment


class LearnerRepository(Protocol):
    def get_active_profile(self) -> LearnerProfile | None:
        ...

    def get_profile(self, learner_id: str) -> LearnerProfile | None:
        ...

    def save_profile(self, profile: LearnerProfile) -> None:
        ...

    def create_profile_if_absent(self, profile: LearnerProfile) -> LearnerProfile:
        ...


class AssignmentRepository(Protocol):
    def save_assignment(self, assignment: LessonAssignment) -> None:
        ...

    def create_active_assignment_if_absent(
        self,
        assignment: LessonAssignment,
    ) -> tuple[LessonAssignment, bool]:
        ...

    def get_assignment(self, assignment_id: str) -> LessonAssignment | None:
        ...

    def get_active_assignment(self, learner_id: str) -> LessonAssignment | None:
        ...

    def get_attempted_assignment(self, learner_id: str) -> LessonAssignment | None:
        ...

    def get_latest_assessed_assignment(
        self,
        learner_id: str,
    ) -> LessonAssignment | None:
        ...

    def update_assignment(self, assignment: LessonAssignment) -> None:
        ...


class AttemptRepository(Protocol):
    def save_attempt_for_assignment(
        self,
        attempt: AttemptSubmission,
        assignment: LessonAssignment,
    ) -> tuple[AttemptSubmission, bool]:
        ...

    def get_attempt(self, attempt_id: str) -> AttemptSubmission | None:
        ...

    def get_attempt_by_client_request_id(
        self,
        learner_id: str,
        client_request_id: str,
    ) -> AttemptSubmission | None:
        ...

    def get_latest_attempt_for_assignment(
        self,
        assignment_id: str,
    ) -> AttemptSubmission | None:
        ...


class AssessmentRepository(Protocol):
    def save_assessment_for_assignment(
        self,
        result: AssessmentResult,
        assignment: LessonAssignment,
    ) -> tuple[AssessmentResult, bool]:
        ...

    def save_assessment_for_assignment_and_profile(
        self,
        result: AssessmentResult,
        assignment: LessonAssignment,
        profile_updater: Callable[[AssessmentResult, LearnerProfile], LearnerProfile],
    ) -> tuple[AssessmentResult, bool]:
        ...

    def get_assessment_by_attempt_id(
        self,
        attempt_id: str,
    ) -> AssessmentResult | None:
        ...

    def get_latest_assessment_for_assignment(
        self,
        assignment_id: str,
    ) -> AssessmentResult | None:
        ...


class CurriculumRepository(Protocol):
    def get_curriculum(self) -> Curriculum:
        ...

    def get_concept(self, concept_id: str) -> Concept | None:
        ...
