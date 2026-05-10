from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from rust_sensei.constants import ACTIVE_LEARNER_ID, ALLOWED_RUST_LEVELS
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.placement import starting_concept_for_level
from rust_sensei.domain.skill import SkillModel
from rust_sensei.dto.mappers import learner_profile_to_dto, skill_model_to_dto
from rust_sensei.dto.session import (
    GetLearnerProfileRequest,
    GetLearnerProfileResponse,
    StartSessionRequest,
    StartSessionResponse,
)
from rust_sensei.errors import not_found_error, validation_error
from rust_sensei.repositories.interfaces import LearnerRepository

LOGGER = logging.getLogger(__name__)


class SessionService:
    def __init__(
        self,
        learner_repository: LearnerRepository,
        now: Callable[[], datetime],
    ) -> None:
        self._learner_repository = learner_repository
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
            self._create_profile(request)
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
