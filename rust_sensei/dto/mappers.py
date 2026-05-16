from rust_sensei.domain.assessment import (
    AssessmentResult,
    AssessmentScoringProvenance,
    ConfidenceBreakdown,
    FeedbackItem,
)
from rust_sensei.domain.attempt import CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, LessonCommand, LessonVariant
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.progress import ProgressEvent
from rust_sensei.domain.setup import SetupCheck
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.dto.assessment import (
    AssessmentResultDTO,
    AssessmentScoringProvenanceDTO,
    ConfidenceBreakdownDTO,
    FeedbackItemDTO,
)
from rust_sensei.dto.attempt import CommandRunMetadataDTO
from rust_sensei.dto.lesson import (
    CurriculumConceptDTO,
    LessonAssignmentDTO,
    LessonCommandDTO,
    LessonPlanDTO,
)
from rust_sensei.dto.progress import ProgressEventDTO
from rust_sensei.dto.session import LearnerProfileDTO, SkillScoreDTO
from rust_sensei.dto.setup import SetupCheckDTO


def skill_score_to_dto(score: SkillScore) -> SkillScoreDTO:
    return SkillScoreDTO(
        score=score.score,
        confidence=score.confidence,
        evidence=list(score.evidence),
    )


def skill_model_to_dto(model: SkillModel) -> dict[str, dict[str, SkillScoreDTO]]:
    return {
        "rust_concepts": {
            key: skill_score_to_dto(value)
            for key, value in model.rust_concepts.items()
        },
        "programming_dimensions": {
            key: skill_score_to_dto(value)
            for key, value in model.programming_dimensions.items()
        },
    }


def confidence_breakdown_to_dto(
    breakdown: ConfidenceBreakdown,
) -> ConfidenceBreakdownDTO:
    return ConfidenceBreakdownDTO(
        critical_evidence_cap=breakdown.critical_evidence_cap,
        evidence_completeness=breakdown.evidence_completeness,
        evidence_quality=breakdown.evidence_quality,
        rubric_confidences=dict(breakdown.rubric_confidences),
        prior_consistency=breakdown.prior_consistency,
        task_difficulty_weight=breakdown.task_difficulty_weight,
        recency_weight=breakdown.recency_weight,
        overall=breakdown.overall,
        explanation=list(breakdown.explanation),
    )


def feedback_item_to_dto(item: FeedbackItem) -> FeedbackItemDTO:
    return FeedbackItemDTO(
        category=item.category,
        message=item.message,
        evidence=list(item.evidence),
    )


def assessment_scoring_provenance_to_dto(
    provenance: AssessmentScoringProvenance,
) -> AssessmentScoringProvenanceDTO:
    return AssessmentScoringProvenanceDTO(
        scorer_type=provenance.scorer_type,
        scorer_name=provenance.scorer_name,
        scorer_version=provenance.scorer_version,
        model_provider=provenance.model_provider,
        model_name=provenance.model_name,
        model_version=provenance.model_version,
    )


def assessment_result_to_dto(result: AssessmentResult) -> AssessmentResultDTO:
    return AssessmentResultDTO(
        assessment_id=result.assessment_id,
        attempt_id=result.attempt_id,
        assignment_id=result.assignment_id,
        scoring_version=result.scoring_version,
        scoring_provenance=(
            None
            if result.scoring_provenance is None
            else assessment_scoring_provenance_to_dto(result.scoring_provenance)
        ),
        assessment_status=result.assessment_status,
        rubric_scores={
            key: skill_score_to_dto(value)
            for key, value in result.rubric_scores.items()
        },
        confidence_breakdown=confidence_breakdown_to_dto(result.confidence_breakdown),
        missing_evidence=list(result.missing_evidence),
        feedback_items=[
            feedback_item_to_dto(item)
            for item in result.feedback_items
        ],
        next_action=result.next_action,
        branch_id=result.branch_id,
        next_action_reason=result.next_action_reason,
        feedback_summary=result.feedback_summary,
        confidence=result.confidence,
    )


def learner_profile_to_dto(profile: LearnerProfile) -> LearnerProfileDTO:
    rust_scores = {
        key: value.score
        for key, value in profile.skill_model.rust_concepts.items()
    }
    programming_scores = {
        key: value.score
        for key, value in profile.skill_model.programming_dimensions.items()
    }
    return LearnerProfileDTO(
        learner_id=profile.learner_id,
        rust_level_initial=profile.rust_level_initial,
        active_concept_id=profile.active_concept_id,
        skill_summary={**rust_scores, **programming_scores},
    )


def setup_check_to_dto(check: SetupCheck) -> SetupCheckDTO:
    return SetupCheckDTO(
        check_id=check.check_id,
        status=check.status,
        message=check.message,
    )


def lesson_assignment_to_dto(assignment: LessonAssignment) -> LessonAssignmentDTO:
    return LessonAssignmentDTO(
        assignment_id=assignment.assignment_id,
        learner_id=assignment.learner_id,
        lesson_id=assignment.lesson_id,
        concept_id=assignment.concept_id,
        difficulty=assignment.difficulty,
        variant_id=assignment.variant_id,
        status=assignment.status,
        selection_rationale=assignment.selection_rationale,
        curriculum_version=assignment.curriculum_version,
    )


def lesson_plan_to_dto(concept: Concept, variant: LessonVariant) -> LessonPlanDTO:
    return LessonPlanDTO(
        lesson_id=_lesson_id(concept.concept_id, variant.variant_id),
        concept_id=concept.concept_id,
        prompt=variant.prompt,
        success_criteria=list(variant.success_criteria),
        learner_command=concept.learner_command,
        lesson_commands=[
            lesson_command_to_dto(command)
            for command in variant.lesson_commands
        ],
        hints=list(variant.hints),
        rubric_ids=list(concept.rubric_ids),
    )


def lesson_command_to_dto(command: LessonCommand) -> LessonCommandDTO:
    return LessonCommandDTO(
        command=command.command,
        purpose=command.purpose,
        risk_level=command.risk_level,
        required=command.required,
        allowed_for_agent_verification=command.allowed_for_agent_verification,
    )


def curriculum_concept_to_dto(concept: Concept) -> CurriculumConceptDTO:
    return CurriculumConceptDTO(
        concept_id=concept.concept_id,
        title=concept.title,
        order=concept.order,
        default_difficulty=concept.default_difficulty,
        learner_command=concept.learner_command,
        rubric_ids=list(concept.rubric_ids),
        variant_ids=[variant.variant_id for variant in concept.variants],
        branch_target_ids=sorted(concept.branch_targets),
    )


def progress_event_to_dto(event: ProgressEvent) -> ProgressEventDTO:
    return ProgressEventDTO(
        event_id=event.event_id,
        event_type=event.event_type.value,
        assignment_id=event.assignment_id,
        attempt_id=event.attempt_id,
        assessment_id=event.assessment_id,
        details=dict(event.details),
        previous_status=event.previous_status,
        new_status=event.new_status,
        created_at=event.created_at.isoformat() if event.created_at else "",
    )


def _lesson_id(concept_id: str, variant_id: str) -> str:
    return f"{concept_id}:{variant_id}"


def command_metadata_from_dto(dto: CommandRunMetadataDTO) -> CommandRunMetadata:
    return CommandRunMetadata(
        command=dto.command,
        source=dto.source,
        cwd=dto.cwd,
        exit_code=dto.exit_code,
        started_at=dto.started_at,
        duration_ms=dto.duration_ms,
        timed_out=dto.timed_out,
        timeout_ms=dto.timeout_ms,
        output_summary=dto.output_summary,
        output_truncated=dto.output_truncated,
        stdout_truncated=dto.stdout_truncated,
        stderr_truncated=dto.stderr_truncated,
        purpose=dto.purpose,
        risk_level=dto.risk_level,
    )
