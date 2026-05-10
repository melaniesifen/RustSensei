from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rust_sensei.domain.enums import RustLevel
from rust_sensei.domain.skill import SkillModel


@dataclass(frozen=True)
class LearnerProfile:
    learner_id: str
    rust_level_initial: RustLevel
    active_concept_id: str | None
    skill_model: SkillModel
    created_at: datetime
    updated_at: datetime
