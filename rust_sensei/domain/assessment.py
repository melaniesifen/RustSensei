from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from rust_sensei.domain.skill import SkillScore

AssessmentStatus = Literal["assessed", "insufficient_evidence"]
NextAction = Literal["simplify", "repeat", "continue", "accelerate", "branch"]


@dataclass(frozen=True)
class ConfidenceBreakdown:
    critical_evidence_cap: float | None
    evidence_completeness: float
    evidence_quality: float
    rubric_confidences: dict[str, float]
    prior_consistency: float
    task_difficulty_weight: float
    recency_weight: float
    overall: float


@dataclass(frozen=True)
class FeedbackItem:
    category: str
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AssessmentResult:
    assessment_id: str
    attempt_id: str
    assignment_id: str
    scoring_version: str
    assessment_status: AssessmentStatus
    rubric_scores: dict[str, SkillScore]
    confidence_breakdown: ConfidenceBreakdown
    missing_evidence: list[str]
    feedback_items: list[FeedbackItem]
    next_action: NextAction
    branch_id: str | None
    next_action_reason: str
    feedback_summary: str
    confidence: float
    created_at: datetime
