from __future__ import annotations

from pydantic import Field

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.dto.common import StrictDTO


class ProgressEventDTO(StrictDTO):
    event_id: str
    event_type: str
    assignment_id: str | None = None
    attempt_id: str | None = None
    assessment_id: str | None = None
    details: dict[str, object] = Field(default_factory=dict)
    previous_status: str | None = None
    new_status: str | None = None
    created_at: str


class GetProgressSummaryRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID


class GetProgressSummaryResponse(StrictDTO):
    learner_id: str
    active_concept_id: str | None
    completed_concepts: list[str] = Field(default_factory=list)
    repeated_concepts: list[str] = Field(default_factory=list)
    skipped_concepts: list[str] = Field(default_factory=list)
    recent_events: list[ProgressEventDTO] = Field(default_factory=list)
    recommended_focus: str | None = None
    trend: str
