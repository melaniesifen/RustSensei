from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Union

from rust_sensei.domain.enums import LearnerSignalType

LearnerSignalValue = Union[str, float, bool]


@dataclass(frozen=True)
class LearnerSignal:
    signal_id: str
    learner_id: str
    signal_type: LearnerSignalType
    value: LearnerSignalValue
    notes: str | None
    created_at: datetime
