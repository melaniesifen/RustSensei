from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ProgressEventType(str, Enum):
    ASSIGNMENT_CREATED = "assignment_created"
    ASSIGNMENT_VIEWED = "assignment_viewed"
    ATTEMPT_SUBMITTED = "attempt_submitted"
    ASSESSED = "assessed"
    COMPLETED = "completed"
    REPEATED = "repeated"
    SIMPLIFIED = "simplified"
    ACCELERATED = "accelerated"
    BRANCHED = "branched"
    PROVISIONALLY_SKIPPED = "provisionally_skipped"
    SKIP_CONFIRMED = "skip_confirmed"
    REOPENED = "reopened"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class ProgressEvent:
    event_id: str
    learner_id: str
    event_type: ProgressEventType
    assignment_id: str | None
    attempt_id: str | None
    assessment_id: str | None
    details: dict[str, Any] = field(default_factory=dict)
    previous_status: str | None = None
    new_status: str | None = None
    created_at: datetime | None = None
