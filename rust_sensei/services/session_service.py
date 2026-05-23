from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from rust_sensei.constants import ACTIVE_LEARNER_ID, ALLOWED_RUST_LEVELS
from rust_sensei.domain.curriculum import Curriculum
from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.placement import starting_concept_for_level
from rust_sensei.domain.progress import ProgressEvent, ProgressEventType
from rust_sensei.domain.signal import LearnerSignal
from rust_sensei.domain.skill import SkillModel
from rust_sensei.dto.mappers import learner_profile_to_dto, skill_model_to_dto
from rust_sensei.dto.session import (
    GetLearnerProfileRequest,
    GetLearnerProfileResponse,
    StartSessionRequest,
    StartSessionResponse,
    UpdateLearnerSignalRequest,
    UpdateLearnerSignalResponse,
)
from rust_sensei.errors import not_found_error, validation_error
from rust_sensei.repositories.interfaces import (
    CurriculumRepository,
    LearnerRepository,
    LearnerSignalRepository,
)

LOGGER = logging.getLogger(__name__)
PLACEMENT_SKIP_LEVELS = {RustLevel.PROFICIENT, RustLevel.EXPERT}


class SessionService:
    def __init__(
        self,
        learner_repository: LearnerRepository,
        learner_signal_repository: LearnerSignalRepository,
        curriculum_repository: CurriculumRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._learner_repository = learner_repository
        self._learner_signal_repository = learner_signal_repository
        self._curriculum_repository = curriculum_repository
        self._now = now

    def start_session(self, request: StartSessionRequest) -> StartSessionResponse:
        self._validate_active_learner(request.learner_id)

        profile = self._learner_repository.get_profile(request.learner_id)
        if profile is not None:
            LOGGER.debug("Reusing learner profile for learner_id=%s", request.learner_id)
            return StartSessionResponse(
                learner_id=request.learner_id,
                placement_required=False,
                profile=learner_profile_to_dto(profile),
            )

        if request.initial_rust_level is None:
            LOGGER.info("Placement required for learner_id=%s", request.learner_id)
            return StartSessionResponse(
                learner_id=request.learner_id,
                placement_required=True,
                allowed_placements=list(ALLOWED_RUST_LEVELS),
                profile=None,
            )

        created = self._learner_repository.create_profile_if_absent(
            self._create_profile(request),
            event_factory=self._placement_skip_events,
        )
        LOGGER.info(
            "Started learner session learner_id=%s rust_level_initial=%s",
            created.learner_id,
            created.rust_level_initial.value,
        )
        return StartSessionResponse(
            learner_id=request.learner_id,
            placement_required=False,
            profile=learner_profile_to_dto(created),
        )

    def get_learner_profile(
        self,
        request: GetLearnerProfileRequest,
    ) -> GetLearnerProfileResponse:
        self._validate_active_learner(request.learner_id)

        profile = self._learner_repository.get_profile(request.learner_id)
        if profile is None:
            raise not_found_error(
                "Learner profile was not found",
                learner_id=request.learner_id,
            )

        return GetLearnerProfileResponse(
            profile=learner_profile_to_dto(profile),
            skill_model=skill_model_to_dto(profile.skill_model),
        )

    def get_active_profile(self) -> GetLearnerProfileResponse:
        return self.get_learner_profile(
            GetLearnerProfileRequest(learner_id=ACTIVE_LEARNER_ID)
        )

    def update_learner_signal(
        self,
        request: UpdateLearnerSignalRequest,
    ) -> UpdateLearnerSignalResponse:
        self._validate_active_learner(request.learner_id)
        if self._learner_repository.get_profile(request.learner_id) is None:
            raise not_found_error(
                "Learner profile was not found",
                learner_id=request.learner_id,
            )
        if isinstance(request.value, str) and not request.value.strip():
            raise validation_error("signal value must not be blank", field="value")
        if request.notes is not None and not request.notes.strip():
            raise validation_error("signal notes must not be blank", field="notes")

        saved = self._learner_signal_repository.save_signal(
            LearnerSignal(
                signal_id="",
                learner_id=request.learner_id,
                signal_type=request.signal_type,
                value=request.value,
                notes=request.notes,
                created_at=self._now(),
            )
        )
        LOGGER.info(
            "Recorded learner signal signal_id=%s learner_id=%s signal_type=%s",
            saved.signal_id,
            saved.learner_id,
            saved.signal_type.value,
        )
        return UpdateLearnerSignalResponse(
            signal_id=saved.signal_id,
            recorded=True,
        )

    def _placement_skip_events(self, profile: LearnerProfile) -> list[ProgressEvent]:
        if (
            profile.rust_level_initial not in PLACEMENT_SKIP_LEVELS
            or profile.active_concept_id is None
        ):
            return []

        curriculum = self._curriculum_repository.get_curriculum()
        skipped_concept_ids = _concept_ids_before_active_concept(
            curriculum,
            profile.active_concept_id,
        )
        return [
            ProgressEvent(
                event_id="",
                learner_id=profile.learner_id,
                event_type=ProgressEventType.PROVISIONALLY_SKIPPED,
                assignment_id=None,
                attempt_id=None,
                assessment_id=None,
                details={
                    "concept_id": concept_id,
                    "placement_level": profile.rust_level_initial.value,
                    "active_concept_id": profile.active_concept_id,
                    "reason": "initial_placement",
                },
                previous_status=None,
                new_status="provisionally_skipped",
                created_at=profile.created_at,
            )
            for concept_id in skipped_concept_ids
        ]

    def _create_profile(self, request: StartSessionRequest) -> LearnerProfile:
        if request.initial_rust_level is None:
            raise validation_error("initial_rust_level is required")

        now = self._now()
        return LearnerProfile(
            learner_id=request.learner_id,
            rust_level_initial=request.initial_rust_level,
            active_concept_id=starting_concept_for_level(request.initial_rust_level),
            skill_model=SkillModel(),
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _validate_active_learner(learner_id: str) -> None:
        if learner_id != ACTIVE_LEARNER_ID:
            raise validation_error(
                "v1 supports only the active learner id",
                learner_id=learner_id,
                active_learner_id=ACTIVE_LEARNER_ID,
            )


def _concept_ids_before_active_concept(
    curriculum: Curriculum,
    active_concept_id: str,
) -> list[str]:
    active_concept = curriculum.concepts.get(active_concept_id)
    if active_concept is None:
        raise ValueError(
            f"Placement active concept {active_concept_id!r} is not in the curriculum"
        )

    return [
        concept.concept_id
        for concept in sorted(curriculum.concepts.values(), key=lambda item: item.order)
        if concept.order < active_concept.order
    ]
