from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from rust_sensei.domain.enums import AssignmentStatus


@dataclass(frozen=True)
class LessonAssignment:
    assignment_id: str
    learner_id: str
    lesson_id: str
    concept_id: str
    difficulty: str
    variant_id: str
    status: AssignmentStatus
    selection_rationale: str
    curriculum_version: str
    created_at: datetime
    updated_at: datetime
