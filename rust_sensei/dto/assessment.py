from __future__ import annotations

from typing import Literal

from pydantic import Field

from rust_sensei.domain.enums import NextAction
from rust_sensei.dto.common import StrictDTO
from rust_sensei.dto.session import SkillScoreDTO


class ConfidenceBreakdownDTO(StrictDTO):
    critical_evidence_cap: float | None = None
    evidence_completeness: float
    evidence_quality: float
    rubric_confidences: dict[str, float]
    prior_consistency: float
    task_difficulty_weight: float
    recency_weight: float
    overall: float
    explanation: list[str] = Field(default_factory=list)


class FeedbackItemDTO(StrictDTO):
    category: str
    message: str
    evidence: list[str] = Field(default_factory=list)


class AssessmentScoringProvenanceDTO(StrictDTO):
    scorer_type: Literal["deterministic", "llm", "hybrid"]
    scorer_name: str
    scorer_version: str
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None


class AssessmentResultDTO(StrictDTO):
    assessment_id: str
    attempt_id: str
    assignment_id: str
    scoring_version: str
    scoring_provenance: AssessmentScoringProvenanceDTO | None = None
    assessment_status: Literal["assessed", "insufficient_evidence"]
    rubric_scores: dict[str, SkillScoreDTO]
    confidence_breakdown: ConfidenceBreakdownDTO
    missing_evidence: list[str] = Field(default_factory=list)
    feedback_items: list[FeedbackItemDTO] = Field(default_factory=list)
    next_action: NextAction
    branch_id: str | None = None
    next_action_reason: str
    feedback_summary: str
    confidence: float


class AssessAttemptRequest(StrictDTO):
    attempt_id: str


class AssessAttemptResponse(StrictDTO):
    assessment: AssessmentResultDTO
    already_assessed: bool
