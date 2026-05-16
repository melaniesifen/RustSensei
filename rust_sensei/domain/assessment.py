from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from rust_sensei.domain.enums import NextAction
from rust_sensei.domain.skill import SkillScore

AssessmentStatus = Literal["assessed", "insufficient_evidence"]
ScorerType = Literal["deterministic", "llm", "hybrid"]


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
    explanation: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FeedbackItem:
    category: str
    message: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AssessmentScoringProvenance:
    scorer_type: ScorerType
    scorer_name: str
    scorer_version: str
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None


@dataclass(frozen=True)
class AssessmentResult:
    assessment_id: str
    attempt_id: str
    assignment_id: str
    scoring_version: str
    scoring_provenance: AssessmentScoringProvenance | None
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
