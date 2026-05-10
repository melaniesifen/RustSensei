from rust_sensei.domain.learner import LearnerProfile
from rust_sensei.domain.setup import SetupCheck
from rust_sensei.domain.skill import SkillModel, SkillScore
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
