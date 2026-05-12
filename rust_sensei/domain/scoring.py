from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from statistics import mean
from typing import Any, Protocol

from rust_sensei.domain.assessment import (
    AssessmentResult,
    AssessmentScoringProvenance,
    ConfidenceBreakdown,
    FeedbackItem,
)
from rust_sensei.domain.attempt import AttemptSubmission
from rust_sensei.domain.curriculum import VALID_RUBRIC_IDS, Concept
from rust_sensei.domain.enums import Difficulty, NextAction
from rust_sensei.domain.skill import SkillScore
from rust_sensei.errors import validation_error

SCORING_VERSION = "deterministic-rubric-v1"
SCORER_NAME = "deterministic-rubric"
SCORER_VERSION = "v1"
INSUFFICIENT_EVIDENCE_CONFIDENCE_THRESHOLD = 0.45
SIMPLIFY_RUST_SCORE_THRESHOLD = 0.50
CONTINUE_RUST_SCORE_THRESHOLD = 0.70
CONTINUE_CONFIDENCE_THRESHOLD = 0.60
ACCELERATE_RUST_SCORE_THRESHOLD = 0.85
ACCELERATE_PROGRAMMING_SCORE_THRESHOLD = 0.80
ACCELERATE_CONFIDENCE_THRESHOLD = 0.80
ADVANCED_FAILURE_SCORE_THRESHOLD = 0.50
ADVANCED_SUCCESS_SCORE_THRESHOLD = 0.80

NO_DETERMINISTIC_SCORER_SCORE = 0.50
FAILURE_SIGNAL_SCORE = 0.35
SUCCESS_SIGNAL_SCORE = 0.85
CODE_WITHOUT_EXECUTION_SCORE = 0.65
NO_CODE_SCORE = 0.30
MISSING_COMPILER_OUTPUT_SCORE = 0.40
FAILURE_WITH_LEARNER_NOTES_SCORE = 0.45
SHORT_CODE_SCORE = 0.45
BASE_CODE_QUALITY_SCORE = 0.72
BASE_PROBLEM_SOLVING_SCORE = 0.60
FUNCTION_BOUNDARY_BONUS = 0.05
BLUNT_IDIOM_PENALTY = 0.10
MAINTAINABILITY_FUNCTION_BONUS = 0.05
LEARNER_NOTES_BONUS = 0.10
TEST_OUTPUT_BONUS = 0.15
DSA_MARKER_BONUS = 0.05

RUBRIC_EVIDENCE_WEIGHTS = {
    "rust_correctness": {
        "code": 0.40,
        "compiler_output": 0.35,
        "test_output": 0.20,
        "learner_notes": 0.05,
    },
    "rust_idioms": {
        "code": 0.70,
        "compiler_output": 0.10,
        "learner_notes": 0.10,
        "agent_notes": 0.10,
    },
    "readability": {
        "code": 0.80,
        "learner_notes": 0.10,
        "agent_notes": 0.10,
    },
    "maintainability": {
        "code": 0.75,
        "learner_notes": 0.15,
        "agent_notes": 0.10,
    },
    "problem_solving": {
        "code": 0.35,
        "test_output": 0.20,
        "learner_notes": 0.30,
        "agent_notes": 0.15,
    },
    "dsa": {
        "code": 0.40,
        "test_output": 0.20,
        "learner_notes": 0.25,
        "agent_notes": 0.15,
    },
    "compiler_error_handling": {
        "compiler_output": 0.45,
        "learner_notes": 0.35,
        "code": 0.20,
    },
}
CODE_DEPENDENT_RUBRICS = {
    "rust_idioms",
    "readability",
    "maintainability",
}
DIFFICULTY_WEIGHTS = {
    Difficulty.INTRO: 0.70,
    Difficulty.GUIDED: 0.80,
    Difficulty.STANDARD: 0.90,
    Difficulty.CHALLENGE: 1.00,
    Difficulty.ADVANCED: 1.00,
}


class AssessmentScorer(Protocol):
    def score_attempt(
        self,
        attempt: AttemptSubmission,
        concept: Concept,
        difficulty: str,
        now: datetime,
    ) -> AssessmentResult:
        ...


class DeterministicAssessmentScorer:
    def score_attempt(
        self,
        attempt: AttemptSubmission,
        concept: Concept,
        difficulty: str,
        now: datetime,
    ) -> AssessmentResult:
        return build_assessment(
            attempt=attempt,
            concept=concept,
            difficulty=difficulty,
            now=now,
        )


def build_assessment(
    attempt: AttemptSubmission,
    concept: Concept,
    difficulty: str,
    now: datetime,
) -> AssessmentResult:
    validate_rubric_ids(concept.rubric_ids)
    rubric_scores = {
        rubric_id: _score_rubric(attempt, rubric_id)
        for rubric_id in concept.rubric_ids
    }
    observed_score = mean(score.score for score in rubric_scores.values())
    confidence_breakdown = _confidence_breakdown(
        attempt,
        concept.rubric_ids,
        difficulty,
        observed_score,
    )
    confidence = confidence_breakdown.overall
    assessment_status = (
        "insufficient_evidence"
        if confidence < INSUFFICIENT_EVIDENCE_CONFIDENCE_THRESHOLD
        else "assessed"
    )
    rust_score = _mean_scores(
        rubric_scores,
        [
            "rust_correctness",
            "rust_idioms",
            "compiler_error_handling",
        ],
    )
    general_programming_score = _mean_scores(
        rubric_scores,
        [
            "readability",
            "maintainability",
            "problem_solving",
            "dsa",
        ],
        fallback=rust_score,
    )
    next_action, next_action_reason = _choose_next_action(
        rust_score=rust_score,
        general_programming_score=general_programming_score,
        confidence=confidence,
    )
    missing_evidence = _missing_evidence(attempt)

    return AssessmentResult(
        assessment_id="",
        attempt_id=attempt.attempt_id,
        assignment_id=attempt.assignment_id,
        scoring_version=SCORING_VERSION,
        scoring_provenance=AssessmentScoringProvenance(
            scorer_type="deterministic",
            scorer_name=SCORER_NAME,
            scorer_version=SCORER_VERSION,
        ),
        assessment_status=assessment_status,
        rubric_scores=rubric_scores,
        confidence_breakdown=confidence_breakdown,
        missing_evidence=missing_evidence,
        feedback_items=_feedback_items(
            assessment_status=assessment_status,
            missing_evidence=missing_evidence,
            rubric_scores=rubric_scores,
        ),
        next_action=next_action,
        branch_id=None,
        next_action_reason=next_action_reason,
        feedback_summary=_feedback_summary(assessment_status, confidence),
        confidence=confidence,
        created_at=now,
    )


def validate_rubric_ids(rubric_ids: list[str]) -> None:
    if not rubric_ids:
        raise validation_error("Assignment concept has no rubric ids")
    missing_confidence_weights = sorted(
        set(rubric_ids) - set(RUBRIC_EVIDENCE_WEIGHTS)
    )
    if missing_confidence_weights:
        raise validation_error(
            "Rubric ids do not have confidence weights",
            rubric_ids=missing_confidence_weights,
        )
    unknown = sorted(set(rubric_ids) - VALID_RUBRIC_IDS)
    if unknown:
        raise validation_error(
            "Unknown rubric ids",
            rubric_ids=unknown,
        )


def _score_rubric(attempt: AttemptSubmission, rubric_id: str) -> SkillScore:
    confidence = _rubric_confidence(attempt, rubric_id)
    if rubric_id == "rust_correctness":
        score, evidence = _score_rust_correctness(attempt)
    elif rubric_id == "compiler_error_handling":
        score, evidence = _score_compiler_error_handling(attempt)
    elif rubric_id in CODE_DEPENDENT_RUBRICS:
        score, evidence = _score_code_quality(attempt, rubric_id)
    elif rubric_id in {"problem_solving", "dsa"}:
        score, evidence = _score_problem_solving(attempt, rubric_id)
    else:
        score, evidence = (
            NO_DETERMINISTIC_SCORER_SCORE,
            ["No deterministic scorer is available for this rubric."],
        )

    return SkillScore(
        score=round(score, 2),
        confidence=confidence,
        evidence=evidence,
    )


def _score_rust_correctness(attempt: AttemptSubmission) -> tuple[float, list[str]]:
    if _has_failure_signal(attempt):
        return FAILURE_SIGNAL_SCORE, ["Compiler or test output indicates a failure."]
    if _has_success_signal(attempt):
        return SUCCESS_SIGNAL_SCORE, ["Submitted execution evidence indicates success."]
    if attempt.code:
        return CODE_WITHOUT_EXECUTION_SCORE, [
            "Code was submitted without clear execution success evidence."
        ]
    return NO_CODE_SCORE, ["No code was submitted for correctness review."]


def _score_compiler_error_handling(
    attempt: AttemptSubmission,
) -> tuple[float, list[str]]:
    if not attempt.compiler_output:
        if _has_success_signal(attempt):
            return CODE_WITHOUT_EXECUTION_SCORE, [
                "Command metadata or test output indicates execution completed."
            ]
        return MISSING_COMPILER_OUTPUT_SCORE, ["Compiler output was not submitted."]
    if _text_has_failure(attempt.compiler_output):
        if attempt.learner_notes:
            return FAILURE_WITH_LEARNER_NOTES_SCORE, [
                "Compiler output shows errors and learner notes add context."
            ]
        return FAILURE_SIGNAL_SCORE, [
            "Compiler output shows errors without learner explanation."
        ]
    return SUCCESS_SIGNAL_SCORE, ["Compiler output does not show compiler errors."]


def _score_code_quality(
    attempt: AttemptSubmission,
    rubric_id: str,
) -> tuple[float, list[str]]:
    if not attempt.code:
        return NO_CODE_SCORE, ["No code was submitted for code-quality review."]
    stripped = attempt.code.strip()
    if len(stripped) < 20:
        return SHORT_CODE_SCORE, [
            "Submitted code is too small for a strong quality judgment."
        ]

    score = BASE_CODE_QUALITY_SCORE
    evidence = ["Submitted code is large enough for deterministic review."]
    if "fn " in stripped:
        score += FUNCTION_BOUNDARY_BONUS
        evidence.append("Code includes a Rust function boundary.")
    if rubric_id == "rust_idioms" and ("unwrap()" in stripped or "clone()" in stripped):
        score -= BLUNT_IDIOM_PENALTY
        evidence.append("Potentially blunt Rust idiom usage was detected.")
    if rubric_id == "maintainability" and stripped.count("fn ") >= 2:
        score += MAINTAINABILITY_FUNCTION_BONUS
        evidence.append("Code uses more than one function boundary.")
    return _clamp(score), evidence


def _score_problem_solving(
    attempt: AttemptSubmission,
    rubric_id: str,
) -> tuple[float, list[str]]:
    if not attempt.code:
        return FAILURE_SIGNAL_SCORE, ["No code was submitted for solution review."]

    score = BASE_PROBLEM_SOLVING_SCORE
    evidence = ["Code was submitted for solution review."]
    if attempt.learner_notes:
        score += LEARNER_NOTES_BONUS
        evidence.append("Learner notes explain the approach.")
    if attempt.test_output and not _text_has_failure(attempt.test_output):
        score += TEST_OUTPUT_BONUS
        evidence.append("Test output supports the submitted solution.")
    if rubric_id == "dsa" and any(
        marker in attempt.code.lower()
        for marker in ["vec", "hashmap", "btreemap", "iter", "sort"]
    ):
        score += DSA_MARKER_BONUS
        evidence.append("Code includes a recognizable data-structure or iteration marker.")
    return _clamp(score), evidence


def _confidence_breakdown(
    attempt: AttemptSubmission,
    required_rubric_ids: list[str],
    difficulty: str,
    observed_score: float,
) -> ConfidenceBreakdown:
    evidence_completeness = _evidence_completeness(attempt)
    evidence_quality = _evidence_quality(attempt)
    rubric_confidences = {
        rubric_id: _rubric_confidence(attempt, rubric_id)
        for rubric_id in required_rubric_ids
    }
    breakdown = ConfidenceBreakdown(
        critical_evidence_cap=_critical_evidence_cap(attempt),
        evidence_completeness=evidence_completeness,
        evidence_quality=evidence_quality,
        rubric_confidences=rubric_confidences,
        prior_consistency=0.60,
        task_difficulty_weight=_task_difficulty_weight(difficulty, observed_score),
        recency_weight=1.00,
        overall=0.0,
    )
    return replace(
        breakdown,
        overall=_overall_confidence(breakdown, required_rubric_ids),
    )


def _critical_evidence_cap(attempt: AttemptSubmission) -> float | None:
    has_code = bool(attempt.code)
    has_primary_execution_artifact = any(
        [
            attempt.compiler_output,
            attempt.runtime_output,
            attempt.test_output,
            _has_primary_command_metadata(attempt),
        ]
    )

    if not has_code and not has_primary_execution_artifact:
        return 0.44
    if not has_code:
        return 0.59
    return None


def _evidence_completeness(attempt: AttemptSubmission) -> float:
    score = 0.0
    score += 0.35 if attempt.code else 0.0
    score += 0.25 if attempt.compiler_output else 0.0
    score += 0.15 if attempt.runtime_output or attempt.test_output else 0.0
    score += 0.10 if attempt.learner_notes else 0.0
    score += 0.10 if attempt.command_run_metadata else 0.0
    score += 0.05 if attempt.assignment_id else 0.0
    return round(min(score, 1.0), 2)


def _evidence_quality(attempt: AttemptSubmission) -> float:
    quality = 1.0
    if attempt.code and len(attempt.code.strip()) < 20:
        quality -= 0.25
    if attempt.output_truncated and not attempt.truncation_reason:
        quality -= 0.15
    if attempt.compiler_output and not _output_relevant_to_lesson(
        attempt.compiler_output
    ):
        quality -= 0.20
    if _evidence_contradicts_agent_notes(attempt):
        quality -= 0.20
    if attempt.learner_notes and len(attempt.learner_notes.strip()) >= 40:
        quality += 0.05
    if attempt.command_run_metadata:
        quality += 0.05
    return round(_clamp(quality), 2)


def _rubric_confidence(attempt: AttemptSubmission, rubric_id: str) -> float:
    weights = RUBRIC_EVIDENCE_WEIGHTS[rubric_id]
    score = 0.0
    for field_name, weight in weights.items():
        if getattr(attempt, field_name, None):
            score += weight
    capped = _apply_rubric_evidence_cap(attempt, rubric_id, score)
    return round(min(capped * _evidence_quality(attempt), 1.0), 2)


def _apply_rubric_evidence_cap(
    attempt: AttemptSubmission,
    rubric_id: str,
    confidence: float,
) -> float:
    if rubric_id in CODE_DEPENDENT_RUBRICS and not attempt.code:
        return min(confidence, 0.35)
    if rubric_id == "compiler_error_handling" and not attempt.compiler_output:
        return min(confidence, 0.50)
    return confidence


def _task_difficulty_weight(difficulty: str, observed_score: float) -> float:
    difficulty_value = _difficulty_or_default(difficulty)
    base = DIFFICULTY_WEIGHTS.get(difficulty_value, 0.90)
    if (
        difficulty_value in {Difficulty.CHALLENGE, Difficulty.ADVANCED}
        and observed_score < ADVANCED_FAILURE_SCORE_THRESHOLD
    ):
        return 0.75
    if (
        difficulty_value in {Difficulty.CHALLENGE, Difficulty.ADVANCED}
        and observed_score >= ADVANCED_SUCCESS_SCORE_THRESHOLD
    ):
        return 1.00
    return base


def _difficulty_or_default(difficulty: str) -> Difficulty:
    try:
        return Difficulty(difficulty)
    except ValueError:
        return Difficulty.STANDARD


def _overall_confidence(
    breakdown: ConfidenceBreakdown,
    required_rubric_ids: list[str],
) -> float:
    rubric_confidence = _weighted_mean_required_rubrics(
        breakdown.rubric_confidences,
        required_rubric_ids,
    )
    value = (
        breakdown.evidence_completeness * 0.30
        + breakdown.evidence_quality * 0.20
        + rubric_confidence * 0.20
        + breakdown.prior_consistency * 0.10
        + breakdown.task_difficulty_weight * 0.15
        + breakdown.recency_weight * 0.05
    )
    bounded = _clamp(value)
    if breakdown.critical_evidence_cap is not None:
        bounded = min(bounded, breakdown.critical_evidence_cap)
    return round(bounded, 2)


def _weighted_mean_required_rubrics(
    rubric_confidences: dict[str, float],
    required_rubric_ids: list[str],
) -> float:
    if not required_rubric_ids:
        raise validation_error("required_rubric_ids must not be empty")
    missing = [
        rubric_id
        for rubric_id in required_rubric_ids
        if rubric_id not in rubric_confidences
    ]
    if missing:
        raise validation_error(
            "Missing rubric confidence",
            rubric_ids=missing,
        )
    return mean(rubric_confidences[rubric_id] for rubric_id in required_rubric_ids)


def _choose_next_action(
    rust_score: float,
    general_programming_score: float,
    confidence: float,
) -> tuple[NextAction, str]:
    if confidence < INSUFFICIENT_EVIDENCE_CONFIDENCE_THRESHOLD:
        return NextAction.REPEAT, "Assessment confidence is below 0.45."
    if rust_score < SIMPLIFY_RUST_SCORE_THRESHOLD:
        return NextAction.SIMPLIFY, "Rust concept score is below 0.50."
    if (
        rust_score >= ACCELERATE_RUST_SCORE_THRESHOLD
        and general_programming_score >= ACCELERATE_PROGRAMMING_SCORE_THRESHOLD
        and confidence >= ACCELERATE_CONFIDENCE_THRESHOLD
    ):
        return NextAction.ACCELERATE, (
            "Rust, general programming, and confidence scores meet "
            "acceleration thresholds."
        )
    if (
        rust_score >= CONTINUE_RUST_SCORE_THRESHOLD
        and confidence >= CONTINUE_CONFIDENCE_THRESHOLD
    ):
        return NextAction.CONTINUE, (
            "Rust score and confidence meet continuation thresholds."
        )
    return NextAction.REPEAT, "No higher-priority rule matched."


def _feedback_items(
    assessment_status: str,
    missing_evidence: list[str],
    rubric_scores: dict[str, SkillScore],
) -> list[FeedbackItem]:
    items = []
    if assessment_status == "insufficient_evidence":
        items.append(
            FeedbackItem(
                category="evidence",
                message="Assessment confidence is too low for a full assessment.",
                evidence=missing_evidence,
            )
        )
    if missing_evidence:
        items.append(
            FeedbackItem(
                category="missing_evidence",
                message="More artifacts would improve assessment confidence.",
                evidence=missing_evidence,
            )
        )
    weakest = min(rubric_scores.items(), key=lambda item: item[1].score)
    items.append(
        FeedbackItem(
            category=weakest[0],
            message="Lowest deterministic rubric score for this attempt.",
            evidence=list(weakest[1].evidence),
        )
    )
    return items


def _feedback_summary(assessment_status: str, confidence: float) -> str:
    if assessment_status == "insufficient_evidence":
        return "Insufficient evidence to produce a confident assessment."
    return f"Assessment completed with {confidence:.2f} confidence."


def _missing_evidence(attempt: AttemptSubmission) -> list[str]:
    missing = []
    if not attempt.code:
        missing.append("code")
    if not any(
        [
            attempt.compiler_output,
            attempt.runtime_output,
            attempt.test_output,
            _has_primary_command_metadata(attempt),
        ]
    ):
        missing.append("execution_output")
    if not attempt.learner_notes:
        missing.append("learner_notes")
    return missing


def _mean_scores(
    scores: dict[str, SkillScore],
    rubric_ids: list[str],
    fallback: float | None = None,
) -> float:
    values = [
        scores[rubric_id].score
        for rubric_id in rubric_ids
        if rubric_id in scores
    ]
    if values:
        return mean(values)
    if fallback is not None:
        return fallback
    return mean(score.score for score in scores.values())


def _has_success_signal(attempt: AttemptSubmission) -> bool:
    outputs = [attempt.compiler_output, attempt.runtime_output, attempt.test_output]
    return any(output and _text_has_success(output) for output in outputs) or any(
        item.exit_code == 0
        for item in attempt.command_run_metadata
        if _metadata_is_primary(item)
    )


def _has_failure_signal(attempt: AttemptSubmission) -> bool:
    outputs = [attempt.compiler_output, attempt.runtime_output, attempt.test_output]
    return any(output and _text_has_failure(output) for output in outputs) or any(
        item.exit_code not in (None, 0)
        for item in attempt.command_run_metadata
        if _metadata_is_primary(item)
    )


def _text_has_success(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in [
            "finished",
            "running",
            "test result: ok",
            "0 failed",
            "passed",
            "ok",
        ]
    )


def _text_has_failure(value: str) -> bool:
    lowered = value.lower()
    if "test result: ok" in lowered or "0 failed" in lowered:
        return False
    return any(
        marker in lowered
        for marker in [
            "error:",
            "failed",
            "panicked",
            "could not compile",
            "aborting",
        ]
    )


def _output_relevant_to_lesson(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in [
            "cargo",
            "rustc",
            "finished",
            "running",
            "error",
            "warning",
            "compile",
            "test",
        ]
    )


def _evidence_contradicts_agent_notes(attempt: AttemptSubmission) -> bool:
    if not attempt.agent_notes:
        return False
    notes = attempt.agent_notes.lower()
    return (
        "passes" in notes
        and _has_failure_signal(attempt)
    ) or (
        "fails" in notes
        and _has_success_signal(attempt)
    )


def _has_primary_command_metadata(attempt: AttemptSubmission) -> bool:
    return any(_metadata_is_primary(item) for item in attempt.command_run_metadata)


def _metadata_is_primary(item: Any) -> bool:
    return all(
        [
            item.command,
            item.source,
            item.exit_code is not None,
            item.started_at,
            item.output_summary,
        ]
    )


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))
