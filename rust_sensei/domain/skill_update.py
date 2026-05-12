from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import mean

from rust_sensei.domain.assessment import AssessmentResult
from rust_sensei.domain.skill import SkillModel, SkillScore

RUST_RUBRICS = {
    "rust_correctness",
    "rust_idioms",
    "compiler_error_handling",
}
PROGRAMMING_RUBRICS = {
    "readability",
    "maintainability",
    "problem_solving",
    "dsa",
}
DEFAULT_PRIOR_SCORE = 0.50
DEFAULT_PRIOR_CONFIDENCE = 0.20


@dataclass(frozen=True)
class ConfidenceBand:
    upper_bound: float
    max_delta: float


CONFIDENCE_BANDS = [
    ConfidenceBand(upper_bound=0.45, max_delta=0.05),
    ConfidenceBand(upper_bound=0.60, max_delta=0.10),
    ConfidenceBand(upper_bound=0.80, max_delta=0.20),
    ConfidenceBand(upper_bound=1.01, max_delta=0.30),
]


def update_skill_model(
    model: SkillModel,
    assessment: AssessmentResult,
    concept_id: str,
) -> SkillModel:
    if assessment.assessment_status == "insufficient_evidence":
        return model

    rust_concepts = dict(model.rust_concepts)
    programming_dimensions = dict(model.programming_dimensions)
    rust_observed = _mean_available_scores(assessment, RUST_RUBRICS)
    if rust_observed is not None:
        rust_concepts[concept_id] = _updated_skill_score(
            previous=rust_concepts.get(concept_id),
            observed_score=rust_observed,
            observed_confidence=assessment.confidence,
            evidence=[
                f"assessment_id={assessment.assessment_id}",
                f"attempt_id={assessment.attempt_id}",
            ],
        )

    for rubric_id in sorted(PROGRAMMING_RUBRICS):
        rubric_score = assessment.rubric_scores.get(rubric_id)
        if rubric_score is None:
            continue
        programming_dimensions[rubric_id] = _updated_skill_score(
            previous=programming_dimensions.get(rubric_id),
            observed_score=rubric_score.score,
            observed_confidence=min(assessment.confidence, rubric_score.confidence),
            evidence=[
                f"assessment_id={assessment.assessment_id}",
                *rubric_score.evidence,
            ],
        )

    return replace(
        model,
        rust_concepts=rust_concepts,
        programming_dimensions=programming_dimensions,
    )


def max_delta_for_confidence(confidence: float) -> float:
    if confidence < 0.0 or confidence > 1.0:
        raise ValueError(f"Confidence must be between 0.0 and 1.0: {confidence}")

    for band in CONFIDENCE_BANDS:
        if confidence < band.upper_bound:
            return band.max_delta

    raise AssertionError("Unreachable confidence band")


def update_score(previous: float, observed: float, confidence: float) -> float:
    max_delta = max_delta_for_confidence(confidence)
    delta = observed - previous
    bounded = max(-max_delta, min(delta, max_delta))
    return round(previous + bounded, 2)


def _updated_skill_score(
    previous: SkillScore | None,
    observed_score: float,
    observed_confidence: float,
    evidence: list[str],
) -> SkillScore:
    previous_score = previous.score if previous is not None else DEFAULT_PRIOR_SCORE
    previous_confidence = (
        previous.confidence if previous is not None else DEFAULT_PRIOR_CONFIDENCE
    )
    updated_score = update_score(
        previous=previous_score,
        observed=observed_score,
        confidence=observed_confidence,
    )
    updated_confidence = update_score(
        previous=previous_confidence,
        observed=observed_confidence,
        confidence=observed_confidence,
    )
    previous_evidence = previous.evidence if previous is not None else []

    return SkillScore(
        score=updated_score,
        confidence=updated_confidence,
        evidence=[*previous_evidence[-4:], *evidence],
    )


def _mean_available_scores(
    assessment: AssessmentResult,
    rubric_ids: set[str],
) -> float | None:
    values = [
        score.score
        for rubric_id, score in assessment.rubric_scores.items()
        if rubric_id in rubric_ids
    ]
    if not values:
        return None
    return mean(values)
