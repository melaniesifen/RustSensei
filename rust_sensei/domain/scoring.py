from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
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
BRANCH_CONFIDENCE_THRESHOLD = 0.80
COMPILER_FEEDBACK_BRANCH_ID = "compiler_feedback_remediation"
COMPILER_FEEDBACK_BRANCH_SCORE_THRESHOLD = 0.50
COMPILER_FEEDBACK_BRANCH_FAILURE_COUNT = 2
PROBLEM_SOLVING_BRANCH_ID = "problem_solving_enrichment"
PROBLEM_SOLVING_BRANCH_RUST_SCORE_THRESHOLD = 0.70
PROBLEM_SOLVING_BRANCH_SCORE_THRESHOLD = 0.55
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
PROBLEM_SOLVING_STRUGGLE_SCORE = 0.50
FUNCTION_BOUNDARY_BONUS = 0.05
BLUNT_IDIOM_PENALTY = 0.10
MAINTAINABILITY_FUNCTION_BONUS = 0.05
LEARNER_NOTES_BONUS = 0.10
TEST_OUTPUT_BONUS = 0.15
DSA_MARKER_BONUS = 0.05
PROBLEM_SOLVING_STRUGGLE_MARKERS = (
    "i guessed",
    "i'm guessing",
    "i am guessing",
    "trial and error",
    "not sure why",
    "don't understand",
    "do not understand",
    "copied this",
    "copied the",
)

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


@dataclass(frozen=True)
class _ConfidenceEvidence:
    has_code: bool
    has_compiler_output: bool
    has_runtime_or_test_output: bool
    has_learner_notes: bool
    has_command_metadata: bool
    has_primary_command_metadata: bool
    has_assignment: bool
    has_primary_execution_artifact: bool


@dataclass(frozen=True)
class _ConfidenceQualityAdjustment:
    delta: float
    explanation: str


@dataclass(frozen=True)
class _AssessmentSummary:
    rust_score: float
    general_programming_score: float
    compiler_error_handling_score: float
    problem_solving_score: float
    confidence: float
    recent_compile_failures: int


@dataclass(frozen=True)
class _NextStepRule:
    rule_id: str
    action: NextAction
    branch_id: str | None
    predicate: Callable[[_AssessmentSummary], bool]
    reason: str


NEXT_STEP_RULES = [
    _NextStepRule(
        rule_id="compiler_feedback_branch",
        action=NextAction.BRANCH,
        branch_id=COMPILER_FEEDBACK_BRANCH_ID,
        predicate=lambda summary: (
            summary.compiler_error_handling_score
            < COMPILER_FEEDBACK_BRANCH_SCORE_THRESHOLD
            and summary.recent_compile_failures >= COMPILER_FEEDBACK_BRANCH_FAILURE_COUNT
            and summary.confidence >= BRANCH_CONFIDENCE_THRESHOLD
        ),
        reason=(
            "Repeated compiler-error struggles have high-confidence evidence for "
            "targeted remediation."
        ),
    ),
    _NextStepRule(
        rule_id="problem_solving_branch",
        action=NextAction.BRANCH,
        branch_id=PROBLEM_SOLVING_BRANCH_ID,
        predicate=lambda summary: (
            summary.rust_score >= PROBLEM_SOLVING_BRANCH_RUST_SCORE_THRESHOLD
            and summary.problem_solving_score < PROBLEM_SOLVING_BRANCH_SCORE_THRESHOLD
            and summary.confidence >= BRANCH_CONFIDENCE_THRESHOLD
        ),
        reason=(
            "Rust syntax is progressing faster than problem-solving skill with "
            "high-confidence evidence."
        ),
    ),
    _NextStepRule(
        rule_id="low_confidence_repeat",
        action=NextAction.REPEAT,
        branch_id=None,
        predicate=lambda summary: (
            summary.confidence < INSUFFICIENT_EVIDENCE_CONFIDENCE_THRESHOLD
        ),
        reason="Assessment confidence is below 0.45.",
    ),
    _NextStepRule(
        rule_id="rust_gap_simplify",
        action=NextAction.SIMPLIFY,
        branch_id=None,
        predicate=lambda summary: summary.rust_score < SIMPLIFY_RUST_SCORE_THRESHOLD,
        reason="Rust concept score is below 0.50.",
    ),
    _NextStepRule(
        rule_id="strong_performance_accelerate",
        action=NextAction.ACCELERATE,
        branch_id=None,
        predicate=lambda summary: (
            summary.rust_score >= ACCELERATE_RUST_SCORE_THRESHOLD
            and summary.general_programming_score
            >= ACCELERATE_PROGRAMMING_SCORE_THRESHOLD
            and summary.confidence >= ACCELERATE_CONFIDENCE_THRESHOLD
        ),
        reason=(
            "Rust, general programming, and confidence scores meet "
            "acceleration thresholds."
        ),
    ),
    _NextStepRule(
        rule_id="expected_progress_continue",
        action=NextAction.CONTINUE,
        branch_id=None,
        predicate=lambda summary: (
            summary.rust_score >= CONTINUE_RUST_SCORE_THRESHOLD
            and summary.confidence >= CONTINUE_CONFIDENCE_THRESHOLD
        ),
        reason="Rust score and confidence meet continuation thresholds.",
    ),
]


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
    next_action, branch_id, next_action_reason = _choose_next_action(
        _AssessmentSummary(
            rust_score=rust_score,
            general_programming_score=general_programming_score,
            compiler_error_handling_score=_score_or_default(
                rubric_scores,
                "compiler_error_handling",
            ),
            problem_solving_score=_score_or_default(
                rubric_scores,
                "problem_solving",
                fallback=general_programming_score,
            ),
            confidence=confidence,
            recent_compile_failures=_compile_failure_count(attempt),
        )
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
        branch_id=branch_id,
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
    if _has_text(attempt.code):
        return CODE_WITHOUT_EXECUTION_SCORE, [
            "Code was submitted without clear execution success evidence."
        ]
    return NO_CODE_SCORE, ["No code was submitted for correctness review."]


def _score_compiler_error_handling(
    attempt: AttemptSubmission,
) -> tuple[float, list[str]]:
    if not _has_text(attempt.compiler_output):
        if _has_success_signal(attempt):
            return CODE_WITHOUT_EXECUTION_SCORE, [
                "Command metadata or test output indicates execution completed."
            ]
        return MISSING_COMPILER_OUTPUT_SCORE, ["Compiler output was not submitted."]
    if _text_has_failure(attempt.compiler_output):
        if _has_text(attempt.learner_notes):
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
    if not _has_text(attempt.code):
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
    if not _has_text(attempt.code):
        return FAILURE_SIGNAL_SCORE, ["No code was submitted for solution review."]

    if _has_problem_solving_struggle_signal(attempt):
        return PROBLEM_SOLVING_STRUGGLE_SCORE, [
            "Learner notes indicate the solution approach is not yet understood."
        ]

    score = BASE_PROBLEM_SOLVING_SCORE
    evidence = ["Code was submitted for solution review."]
    if _has_text(attempt.learner_notes):
        score += LEARNER_NOTES_BONUS
        evidence.append("Learner notes explain the approach.")
    if _has_text(attempt.test_output) and not _text_has_failure(attempt.test_output):
        score += TEST_OUTPUT_BONUS
        evidence.append("Test output supports the submitted solution.")
    if rubric_id == "dsa" and any(
        marker in attempt.code.lower()
        for marker in ["vec", "hashmap", "btreemap", "iter", "sort"]
    ):
        score += DSA_MARKER_BONUS
        evidence.append("Code includes a recognizable data-structure or iteration marker.")
    return _clamp(score), evidence


def _has_problem_solving_struggle_signal(attempt: AttemptSubmission) -> bool:
    if not _has_text(attempt.learner_notes):
        return False
    notes = attempt.learner_notes.lower()
    return any(marker in notes for marker in PROBLEM_SOLVING_STRUGGLE_MARKERS)


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
        explanation=_confidence_explanation(attempt, difficulty, observed_score),
    )
    return replace(
        breakdown,
        overall=_overall_confidence(breakdown, required_rubric_ids),
    )


def _critical_evidence_cap(attempt: AttemptSubmission) -> float | None:
    evidence = _confidence_evidence(attempt)
    if not evidence.has_code and not evidence.has_primary_execution_artifact:
        return 0.44
    if not evidence.has_code:
        return 0.59
    return None


def _confidence_explanation(
    attempt: AttemptSubmission,
    difficulty: str,
    observed_score: float,
) -> list[str]:
    reasons = []
    reasons.extend(_critical_evidence_explanation(attempt))
    reasons.extend(_completeness_explanation(attempt))
    reasons.extend(_quality_explanation(attempt))
    reasons.extend(_difficulty_explanation(difficulty, observed_score))
    if not reasons:
        reasons.append("Submitted evidence supports the confidence score.")
    return reasons


def _critical_evidence_explanation(attempt: AttemptSubmission) -> list[str]:
    evidence = _confidence_evidence(attempt)
    if not evidence.has_code and not evidence.has_primary_execution_artifact:
        return ["Code and primary execution evidence were missing, limiting confidence."]
    if not evidence.has_code:
        return ["Code was missing, limiting confidence."]
    return []


def _completeness_explanation(attempt: AttemptSubmission) -> list[str]:
    evidence = _confidence_evidence(attempt)
    reasons = []
    if not evidence.has_compiler_output:
        reasons.append("Compiler output was not submitted.")
    if not evidence.has_primary_execution_artifact:
        reasons.append("Runtime or test execution evidence was not submitted.")
    if not evidence.has_learner_notes:
        reasons.append("Learner notes were not submitted.")
    return reasons


def _quality_explanation(attempt: AttemptSubmission) -> list[str]:
    return [
        adjustment.explanation
        for adjustment in _quality_adjustments(attempt)
    ]


def _difficulty_explanation(difficulty: str, observed_score: float) -> list[str]:
    difficulty_value = _difficulty_or_default(difficulty)
    if (
        difficulty_value in {Difficulty.CHALLENGE, Difficulty.ADVANCED}
        and observed_score < ADVANCED_FAILURE_SCORE_THRESHOLD
    ):
        return ["Low scores on a harder task reduced confidence."]
    return []


def _evidence_completeness(attempt: AttemptSubmission) -> float:
    evidence = _confidence_evidence(attempt)
    score = 0.0
    score += 0.35 if evidence.has_code else 0.0
    score += 0.25 if evidence.has_compiler_output else 0.0
    score += 0.15 if evidence.has_runtime_or_test_output else 0.0
    score += 0.10 if evidence.has_learner_notes else 0.0
    score += 0.10 if evidence.has_command_metadata else 0.0
    score += 0.05 if evidence.has_assignment else 0.0
    return round(min(score, 1.0), 2)


def _evidence_quality(attempt: AttemptSubmission) -> float:
    quality = 1.0
    for adjustment in _quality_adjustments(attempt):
        quality += adjustment.delta
    return round(_clamp(quality), 2)


def _rubric_confidence(attempt: AttemptSubmission, rubric_id: str) -> float:
    weights = RUBRIC_EVIDENCE_WEIGHTS[rubric_id]
    score = 0.0
    for field_name, weight in weights.items():
        if _has_evidence_field(getattr(attempt, field_name, None)):
            score += weight
    capped = _apply_rubric_evidence_cap(attempt, rubric_id, score)
    return round(min(capped * _evidence_quality(attempt), 1.0), 2)


def _apply_rubric_evidence_cap(
    attempt: AttemptSubmission,
    rubric_id: str,
    confidence: float,
) -> float:
    if rubric_id in CODE_DEPENDENT_RUBRICS and not _has_text(attempt.code):
        return min(confidence, 0.35)
    if (
        rubric_id == "compiler_error_handling"
        and not _has_text(attempt.compiler_output)
    ):
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
    summary: _AssessmentSummary,
) -> tuple[NextAction, str | None, str]:
    for rule in NEXT_STEP_RULES:
        if rule.predicate(summary):
            return rule.action, rule.branch_id, rule.reason
    return NextAction.REPEAT, None, "No higher-priority rule matched."


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
    evidence = _confidence_evidence(attempt)
    missing = []
    if not evidence.has_code:
        missing.append("code")
    if not evidence.has_primary_execution_artifact:
        missing.append("execution_output")
    if not evidence.has_learner_notes:
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


def _score_or_default(
    scores: dict[str, SkillScore],
    rubric_id: str,
    fallback: float = 1.0,
) -> float:
    if rubric_id not in scores:
        return fallback
    return scores[rubric_id].score


def _compile_failure_count(attempt: AttemptSubmission) -> int:
    metadata_failure_count = sum(
        1
        for item in attempt.command_run_metadata
        if _metadata_is_primary(item) and item.exit_code not in (None, 0)
    )
    if metadata_failure_count:
        return metadata_failure_count
    if _has_text(attempt.compiler_output) and _text_has_failure(
        attempt.compiler_output
    ):
        return 1
    return 0


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


def _confidence_evidence(attempt: AttemptSubmission) -> _ConfidenceEvidence:
    has_code = _has_text(attempt.code)
    has_compiler_output = _has_text(attempt.compiler_output)
    has_runtime_or_test_output = (
        _has_text(attempt.runtime_output) or _has_text(attempt.test_output)
    )
    has_primary_command_metadata = _has_primary_command_metadata(attempt)
    return _ConfidenceEvidence(
        has_code=has_code,
        has_compiler_output=has_compiler_output,
        has_runtime_or_test_output=has_runtime_or_test_output,
        has_learner_notes=_has_text(attempt.learner_notes),
        has_command_metadata=bool(attempt.command_run_metadata),
        has_primary_command_metadata=has_primary_command_metadata,
        has_assignment=bool(attempt.assignment_id),
        has_primary_execution_artifact=any(
            [
                has_compiler_output,
                has_runtime_or_test_output,
                has_primary_command_metadata,
            ]
        ),
    )


def _quality_adjustments(
    attempt: AttemptSubmission,
) -> list[_ConfidenceQualityAdjustment]:
    adjustments = []
    if _has_text(attempt.code) and len(attempt.code.strip()) < 20:
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=-0.25,
                explanation="Submitted code was very short, reducing evidence quality.",
            )
        )
    if attempt.output_truncated and not attempt.truncation_reason:
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=-0.15,
                explanation="Output was marked truncated without a truncation reason.",
            )
        )
    if _has_text(attempt.compiler_output) and not _output_relevant_to_lesson(
        attempt.compiler_output
    ):
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=-0.20,
                explanation="Compiler output was not clearly related to the lesson.",
            )
        )
    if _evidence_contradicts_agent_notes(attempt):
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=-0.20,
                explanation="Agent notes conflicted with submitted execution evidence.",
            )
        )
    if _has_text(attempt.learner_notes) and len(attempt.learner_notes.strip()) >= 40:
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=0.05,
                explanation="Learner notes added enough context to improve confidence.",
            )
        )
    if attempt.command_run_metadata:
        adjustments.append(
            _ConfidenceQualityAdjustment(
                delta=0.05,
                explanation="Structured command metadata supported the evidence review.",
            )
        )
    return adjustments


def _has_primary_command_metadata(attempt: AttemptSubmission) -> bool:
    return any(_metadata_is_primary(item) for item in attempt.command_run_metadata)


def _metadata_is_primary(item: Any) -> bool:
    return all(
        [
            _has_text(item.command),
            item.source in {"learner", "agent"},
            item.exit_code is not None,
            item.started_at,
            _has_text(item.output_summary),
        ]
    )


def _has_text(value: str | None) -> bool:
    return bool(value and value.strip())


def _has_evidence_field(value: Any) -> bool:
    if isinstance(value, str):
        return _has_text(value)
    return bool(value)


def _clamp(value: float) -> float:
    return max(0.0, min(value, 1.0))
