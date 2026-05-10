from rust_sensei.domain.attempt import CommandRunMetadata
from rust_sensei.domain.curriculum import Concept, LessonCommand, LessonVariant
from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.lesson import LessonAssignment
from rust_sensei.domain.setup import SetupCheck
from rust_sensei.domain.skill import SkillModel, SkillScore
from rust_sensei.dto.lesson import (
    LessonAssignmentDTO,
    LessonCommandDTO,
    LessonPlanDTO,
)
from rust_sensei.dto.attempt import CommandRunMetadataDTO
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
