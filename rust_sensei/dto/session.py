from __future__ import annotations

from pydantic import Field

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.dto.common import RustLevel, StrictDTO


class SkillScoreDTO(StrictDTO):
    score: float
    confidence: float
    evidence: list[str] = Field(default_factory=list)


class LearnerProfileDTO(StrictDTO):
    learner_id: str
    rust_level_initial: RustLevel
    active_concept_id: str | None
    skill_summary: dict[str, float] = Field(default_factory=dict)


class StartSessionRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID
    initial_rust_level: RustLevel | None = None


class StartSessionResponse(StrictDTO):
    learner_id: str
    placement_required: bool
    allowed_placements: list[RustLevel] = Field(default_factory=list)
    profile: LearnerProfileDTO | None = None


class GetLearnerProfileRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID


class GetLearnerProfileResponse(StrictDTO):
    profile: LearnerProfileDTO
    skill_model: dict[str, dict[str, SkillScoreDTO]]
